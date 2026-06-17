"""
OAuth/OIDC provider config loader.

Loads provider configs from YAML with support for:
- built-in provider templates (GitHub, Google, etc.)
- custom OIDC providers
- env var expansion ${VAR_NAME}
- OIDC Discovery endpoints
- multi-protocol support (oauth2, jd_sso, etc.)
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import yaml
from loguru import logger

LOG_PREFIX = "[OAuthConfig]"

# ==================== Built-in Provider Templates ====================
# Common OAuth provider defaults
# Users only need client_id/client_secret

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
        # GitHub-specific config
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
        # Microsoft uses {tenant} placeholder; default "common" (all accounts)
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
    """Single OAuth provider config."""

    name: str  # Provider key (e.g. "github")
    display_name: str  # Display name (e.g. "GitHub")
    icon: str  # Icon key
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
    # Extra config
    token_endpoint_auth_method: str = "client_secret_basic"
    userinfo_headers: Dict[str, str] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)
    # Protocol type: oauth2 (standard), jd_sso (JD SSA)
    # Non-standard protocols are handled by a ProtocolHandler
    protocol: str = "oauth2"


@dataclass
class OAuthSettings:
    """OAuth global settings."""

    default_redirect_url: str = "/managed/quickstart"
    allow_registration: bool = True
    auto_link_by_email: bool = True


class OAuthConfigLoader:
    """OAuth config loader."""

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize the config loader.

        Args:
            config_path: Config file path; use default when None
        """
        if config_path:
            self.config_path = Path(config_path)
        else:
            # Default path: backend/config/oauth_providers.yaml
            # From app/core/oauth/config.py up to app/, then to backend/
            self.config_path = Path(__file__).parent.parent.parent.parent / "config" / "oauth_providers.yaml"

        self._providers: Dict[str, OAuthProviderConfig] = {}
        self._settings: OAuthSettings = OAuthSettings()
        self._loaded: bool = False
        self._oidc_discovery_cache: Dict[str, Dict[str, Any]] = {}

    def load(self, force_reload: bool = False) -> None:
        """
        Load config file.

        Args:
            force_reload: Force reload
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

            # Load global settings
            settings_raw = raw.get("settings", {})
            self._settings = OAuthSettings(
                default_redirect_url=settings_raw.get("default_redirect_url", "/managed/quickstart"),
                allow_registration=settings_raw.get("allow_registration", True),
                auto_link_by_email=settings_raw.get("auto_link_by_email", True),
            )

            # Load provider configs
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
        """Parse a single provider config."""
        # Expand env vars
        config = self._expand_env_vars(config)

        # Get template config
        template_name = config.get("template")
        template = PROVIDER_TEMPLATES.get(template_name, {}) if template_name else {}

        # Merge config (user overrides template)
        merged = {**template, **config}

        # Validate required fields
        client_id = merged.get("client_id", "").strip()
        client_secret = merged.get("client_secret", "").strip()

        if not client_id or not client_secret:
            logger.warning(f"{LOG_PREFIX} Provider '{name}' missing client_id or client_secret")
            return None

        # Replace Microsoft tenant placeholder
        tenant = merged.get("tenant", merged.get("default_tenant", "common"))
        authorize_url = merged.get("authorize_url", "").replace("{tenant}", tenant)
        token_url = merged.get("token_url", "").replace("{tenant}", tenant)

        # Protocol (default oauth2; jd_sso for JD SSA)
        protocol = merged.get("protocol", "oauth2")

        # Build config object
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
                    "protocol",
                }
            },
            protocol=protocol,
        )

    def _expand_env_vars(self, obj: Any) -> Any:
        """Recursively replace ${VAR_NAME} with env var values."""
        if isinstance(obj, str):
            return re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), ""), obj)
        elif isinstance(obj, dict):
            return {k: self._expand_env_vars(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._expand_env_vars(i) for i in obj]
        return obj

    async def discover_oidc_config(self, issuer: str) -> Dict[str, Any]:
        """
        Fetch config from OIDC Discovery endpoint.

        Args:
            issuer: OIDC issuer URL

        Returns:
            OIDC config dict
        """
        if issuer in self._oidc_discovery_cache:
            return self._oidc_discovery_cache[issuer]

        discovery_url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"

        # SSRF protection: validate OIDC issuer URL
        from app.joysafeter_shared.security.ssrf_guard import validate_url
        validate_url(discovery_url, context="OIDC discovery issuer")

        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
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
        """Get provider config by name."""
        self.load()
        return self._providers.get(name)

    def list_providers(self) -> List[Dict[str, str]]:
        """
        List enabled providers (for frontend buttons).

        Returns:
            Provider info list without secrets
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
        """Get all provider configs."""
        self.load()
        return self._providers.copy()

    @property
    def settings(self) -> OAuthSettings:
        """Get global settings."""
        self.load()
        return self._settings

    def is_provider_enabled(self, name: str) -> bool:
        """Check if provider is enabled."""
        self.load()
        return name in self._providers


# Global config loader (lazy init)
_oauth_config: Optional[OAuthConfigLoader] = None


def get_oauth_config() -> OAuthConfigLoader:
    """Get global OAuth config loader."""
    global _oauth_config
    if _oauth_config is None:
        from app.joysafeter_shared.config.settings import settings

        config_path = getattr(settings, "oauth_config_path", None)
        _oauth_config = OAuthConfigLoader(config_path)
    return _oauth_config


def reload_oauth_config() -> None:
    """Reload OAuth config."""
    config = get_oauth_config()
    config.load(force_reload=True)
