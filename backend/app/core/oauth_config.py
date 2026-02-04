"""
OAuth/OIDC 提供商配置加载器

从 YAML 配置文件加载 OAuth 提供商配置，支持：
- 内置提供商模板（GitHub、Google 等）
- 自定义 OIDC 提供商
- 环境变量替换 ${VAR_NAME}
- OIDC Discovery 自动获取 endpoints
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

import httpx
import yaml
from loguru import logger

LOG_PREFIX = "[OAuthConfig]"

# ==================== 内置提供商模板 ====================
# 这些模板包含常见 OAuth 提供商的默认配置
# 用户只需提供 client_id 和 client_secret 即可使用

PROVIDER_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "github": {
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "userinfo_url": "https://api.github.com/user",
        "scope": "read:user user:email",
        "user_mapping": {
            "id": "id",
            "email": "email",
            "name": "name",
            "avatar": "avatar_url",
        },
        # GitHub 特殊配置
        "token_endpoint_auth_method": "client_secret_post",
        "userinfo_headers": {"Accept": "application/vnd.github+json"},
    },
    "google": {
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": "openid email profile",
        "user_mapping": {
            "id": "sub",
            "email": "email",
            "name": "name",
            "avatar": "picture",
        },
    },
    "microsoft": {
        # Microsoft 使用 {tenant} 占位符，默认为 common（支持所有账户）
        "authorize_url": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        "userinfo_url": "https://graph.microsoft.com/oidc/userinfo",
        "scope": "openid email profile",
        "user_mapping": {
            "id": "sub",
            "email": "email",
            "name": "name",
            "avatar": "picture",
        },
        "default_tenant": "common",
    },
    "gitlab": {
        "authorize_url": "https://gitlab.com/oauth/authorize",
        "token_url": "https://gitlab.com/oauth/token",
        "userinfo_url": "https://gitlab.com/api/v4/user",
        "scope": "read_user",
        "user_mapping": {
            "id": "id",
            "email": "email",
            "name": "name",
            "avatar": "avatar_url",
        },
    },
}


@dataclass
class OAuthProviderConfig:
    """单个 OAuth 提供商的配置"""

    name: str  # 提供商标识（如 "github"）
    display_name: str  # 显示名称（如 "GitHub"）
    icon: str  # 图标标识
    client_id: str
    client_secret: str
    authorize_url: str
    token_url: str
    userinfo_url: Optional[str] = None
    scope: str = "openid email profile"
    issuer: Optional[str] = None  # OIDC issuer URL
    user_mapping: Dict[str, str] = field(
        default_factory=lambda: {
            "id": "sub",
            "email": "email",
            "name": "name",
            "avatar": "picture",
        }
    )
    # 额外配置
    token_endpoint_auth_method: str = "client_secret_basic"
    userinfo_headers: Dict[str, str] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OAuthSettings:
    """OAuth 全局设置"""

    default_redirect_url: str = "/chat"
    allow_registration: bool = True
    auto_link_by_email: bool = True


class OAuthConfigLoader:
    """OAuth 配置加载器"""

    def __init__(self, config_path: Optional[str] = None):
        """
        初始化配置加载器

        Args:
            config_path: 配置文件路径，如果为 None 则使用默认路径
        """
        if config_path:
            self.config_path = Path(config_path)
        else:
            # 默认路径：backend/config/oauth_providers.yaml
            self.config_path = Path(__file__).parent.parent.parent / "config" / "oauth_providers.yaml"

        self._providers: Dict[str, OAuthProviderConfig] = {}
        self._settings: OAuthSettings = OAuthSettings()
        self._loaded: bool = False
        self._oidc_discovery_cache: Dict[str, Dict[str, Any]] = {}

    def load(self, force_reload: bool = False) -> None:
        """
        加载配置文件

        Args:
            force_reload: 是否强制重新加载
        """
        if self._loaded and not force_reload:
            return

        self._providers.clear()
        self._settings = OAuthSettings()

        if not self.config_path.exists():
            logger.warning(f"{LOG_PREFIX} Config file not found: {self.config_path}")
            self._loaded = True
            return

        try:
            with open(self.config_path, encoding="utf-8") as f:
                raw = yaml.safe_load(f)

            if not raw:
                logger.warning(f"{LOG_PREFIX} Config file is empty: {self.config_path}")
                self._loaded = True
                return

            # 加载全局设置
            settings_raw = raw.get("settings", {})
            self._settings = OAuthSettings(
                default_redirect_url=settings_raw.get("default_redirect_url", "/chat"),
                allow_registration=settings_raw.get("allow_registration", True),
                auto_link_by_email=settings_raw.get("auto_link_by_email", True),
            )

            # 加载提供商配置
            for name, config in raw.get("providers", {}).items():
                if not config.get("enabled", False):
                    logger.debug(f"{LOG_PREFIX} Provider '{name}' is disabled, skipping")
                    continue

                try:
                    provider = self._parse_provider(name, config)
                    if provider:
                        self._providers[name] = provider
                        logger.info(f"{LOG_PREFIX} Loaded provider: {name}")
                except Exception as e:
                    logger.error(f"{LOG_PREFIX} Failed to load provider '{name}': {e}")

            self._loaded = True
            logger.info(f"{LOG_PREFIX} Loaded {len(self._providers)} OAuth providers")

        except Exception as e:
            logger.error(f"{LOG_PREFIX} Failed to load config: {e}")
            self._loaded = True

    def _parse_provider(self, name: str, config: Dict[str, Any]) -> Optional[OAuthProviderConfig]:
        """解析单个提供商配置"""
        # 展开环境变量
        config = self._expand_env_vars(config)

        # 获取模板配置
        template_name = config.get("template")
        template = PROVIDER_TEMPLATES.get(template_name, {}) if template_name else {}

        # 合并配置（用户配置覆盖模板）
        merged = {**template, **config}

        # 验证必要字段
        client_id = merged.get("client_id", "").strip()
        client_secret = merged.get("client_secret", "").strip()

        if not client_id or not client_secret:
            logger.warning(f"{LOG_PREFIX} Provider '{name}' missing client_id or client_secret")
            return None

        # 处理 Microsoft 的 tenant 占位符
        tenant = merged.get("tenant", merged.get("default_tenant", "common"))
        authorize_url = merged.get("authorize_url", "").replace("{tenant}", tenant)
        token_url = merged.get("token_url", "").replace("{tenant}", tenant)

        # 构建配置对象
        return OAuthProviderConfig(
            name=name,
            display_name=merged.get("display_name", name.capitalize()),
            icon=merged.get("icon", name),
            client_id=client_id,
            client_secret=client_secret,
            authorize_url=authorize_url,
            token_url=token_url,
            userinfo_url=merged.get("userinfo_url"),
            scope=merged.get("scope", "openid email profile"),
            issuer=merged.get("issuer"),
            user_mapping=merged.get(
                "user_mapping",
                {
                    "id": "sub",
                    "email": "email",
                    "name": "name",
                    "avatar": "picture",
                },
            ),
            token_endpoint_auth_method=merged.get("token_endpoint_auth_method", "client_secret_basic"),
            userinfo_headers=merged.get("userinfo_headers", {}),
            extra={
                k: v
                for k, v in merged.items()
                if k
                not in {
                    "enabled",
                    "template",
                    "display_name",
                    "icon",
                    "client_id",
                    "client_secret",
                    "authorize_url",
                    "token_url",
                    "userinfo_url",
                    "scope",
                    "issuer",
                    "user_mapping",
                    "token_endpoint_auth_method",
                    "userinfo_headers",
                    "tenant",
                    "default_tenant",
                }
            },
        )

    def _expand_env_vars(self, obj: Any) -> Any:
        """递归替换 ${VAR_NAME} 为环境变量值"""
        if isinstance(obj, str):
            return re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), ""), obj)
        elif isinstance(obj, dict):
            return {k: self._expand_env_vars(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._expand_env_vars(i) for i in obj]
        return obj

    async def discover_oidc_config(self, issuer: str) -> Dict[str, Any]:
        """
        从 OIDC Discovery endpoint 获取配置

        Args:
            issuer: OIDC issuer URL

        Returns:
            OIDC 配置字典
        """
        if issuer in self._oidc_discovery_cache:
            return self._oidc_discovery_cache[issuer]

        discovery_url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(discovery_url)
                response.raise_for_status()
                config: Dict[str, Any] = response.json()
                self._oidc_discovery_cache[issuer] = config
                logger.info(f"{LOG_PREFIX} OIDC Discovery successful: {issuer}")
                return config
        except Exception as e:
            logger.error(f"{LOG_PREFIX} OIDC Discovery failed for {issuer}: {e}")
            raise

    def get_provider(self, name: str) -> Optional[OAuthProviderConfig]:
        """获取指定提供商配置"""
        self.load()
        return self._providers.get(name)

    def list_providers(self) -> List[Dict[str, str]]:
        """
        获取所有已启用提供商的列表（供前端渲染按钮）

        Returns:
            提供商信息列表，不含敏感信息
        """
        self.load()
        return [
            {
                "id": name,
                "display_name": provider.display_name,
                "icon": provider.icon,
            }
            for name, provider in self._providers.items()
        ]

    def get_all_providers(self) -> Dict[str, OAuthProviderConfig]:
        """获取所有提供商配置"""
        self.load()
        return self._providers.copy()

    @property
    def settings(self) -> OAuthSettings:
        """获取全局设置"""
        self.load()
        return self._settings

    def is_provider_enabled(self, name: str) -> bool:
        """检查提供商是否启用"""
        self.load()
        return name in self._providers


# 全局配置加载器实例（延迟初始化）
_oauth_config: Optional[OAuthConfigLoader] = None


def get_oauth_config() -> OAuthConfigLoader:
    """获取全局 OAuth 配置加载器实例"""
    global _oauth_config
    if _oauth_config is None:
        from app.core.settings import settings

        config_path = getattr(settings, "oauth_config_path", None)
        _oauth_config = OAuthConfigLoader(config_path)
    return _oauth_config


def reload_oauth_config() -> None:
    """重新加载 OAuth 配置"""
    config = get_oauth_config()
    config.load(force_reload=True)
