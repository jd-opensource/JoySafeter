"""
应用配置
"""

import os
import socket
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine.url import make_url

# 获取项目根目录（backend 目录）
# 从 app/core/settings.py 向上两级到 backend/
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = BASE_DIR / ".env"


def _is_tcp_port_open(host: str, port: int, timeout_seconds: float = 0.5) -> bool:
    """检查 TCP 端口是否开放"""
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


class Settings(BaseSettings):
    """应用配置"""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = Field(default="JoySafeter", description="Application name")
    app_version: str = Field(default="0.1.0", description="Application version")
    debug: bool = Field(
        default=False, validation_alias=AliasChoices("DEBUG", "APP_DEBUG"), description="Enable debug mode"
    )
    environment: str = Field(
        default="development",
        validation_alias=AliasChoices("ENVIRONMENT", "ENV", "APP_ENV"),
        description="Application environment (development, staging, production)",
    )

    # Server
    host: str = Field(
        default="0.0.0.0",
        validation_alias=AliasChoices("BACKEND_HOST", "HOST", "SERVER_HOST"),
        description="Backend server host",
    )
    port: int = Field(
        default=8000,
        validation_alias=AliasChoices("BACKEND_PORT", "PORT", "SERVER_PORT"),
        description="Backend server port",
    )
    reload: bool = Field(
        default=True,
        validation_alias=AliasChoices("RELOAD", "AUTO_RELOAD"),
        description="Enable auto-reload on code changes",
    )
    workers: int = Field(
        default=1, validation_alias=AliasChoices("WORKERS", "UVICORN_WORKERS"), description="Number of worker processes"
    )

    # Database
    database_echo: bool = Field(
        default=False,
        validation_alias=AliasChoices("DATABASE_ECHO", "DB_ECHO", "SQL_ECHO"),
        description="Enable SQL query logging",
    )
    database_pool_size: int = Field(
        default=10,
        validation_alias=AliasChoices("DATABASE_POOL_SIZE", "DB_POOL_SIZE"),
        description="Database connection pool size",
    )
    database_max_overflow: int = Field(
        default=20,
        validation_alias=AliasChoices("DATABASE_MAX_OVERFLOW", "DB_MAX_OVERFLOW"),
        description="Database connection pool max overflow",
    )

    @property
    def database_url(self) -> str:
        """
        从 POSTGRES_* 环境变量构建数据库连接 URL

        自动处理两种场景：
        1. Backend 在本机启动：使用 localhost + POSTGRES_PORT_HOST（如果设置）或 5432
        2. 在同一个 docker-compose：使用服务名（如 "db"）+ 容器内部端口 5432
        """
        postgres_host = os.getenv("POSTGRES_HOST", "localhost")
        postgres_user = os.getenv("POSTGRES_USER", "postgres")
        postgres_password = os.getenv("POSTGRES_PASSWORD", "postgres")
        postgres_db = os.getenv("POSTGRES_DB", "joysafeter")

        # 确定端口：
        if postgres_host in ("localhost", "127.0.0.1", "::1"):
            # 本地启动：检查是否有 Docker 映射端口配置
            postgres_port_host = os.getenv("POSTGRES_PORT_HOST")
            postgres_port = postgres_port_host if postgres_port_host else os.getenv("POSTGRES_PORT", "5432")
        else:
            # docker-compose 场景：使用容器内部端口 5432（忽略 POSTGRES_PORT）
            postgres_port = "5432"

        database_url = (
            f"postgresql+asyncpg://{postgres_user}:{postgres_password}@{postgres_host}:{postgres_port}/{postgres_db}"
        )

        # 针对 localhost 的端口自动修复逻辑 (参考 scripts/view_db.py)
        # 解决常见问题：.env 配置了 5433 (docker) 但本地直接启动需要 5432，或者反之
        try:
            url = make_url(database_url)
            host = url.host
            port = url.port

            if host in ("localhost", "127.0.0.1", "::1") and port:
                if not _is_tcp_port_open(host, port):
                    # 如果当前配置的端口不通，但 5432 通，则自动切换
                    if port != 5432 and _is_tcp_port_open(host, 5432):
                        url = url.set(port=5432)
                        database_url = url.render_as_string(hide_password=False)
                        print(f"   ⚠️  Database connection to {host}:{port} failed, auto-switched to 5432")
        except Exception:
            pass

        return database_url

    # Sync database URL for Alembic
    @property
    def database_url_sync(self) -> str:
        """同步数据库 URL (用于 Alembic)"""
        return self.database_url.replace("+asyncpg", "")

    # Redis (缓存 & 限流)
    redis_url: Optional[str] = Field(default=None, validation_alias="REDIS_URL", description="Redis connection URL")
    redis_pool_size: int = Field(
        default=10,
        validation_alias=AliasChoices("REDIS_POOL_SIZE", "REDIS_CONNECTION_POOL_SIZE"),
        description="Redis connection pool size",
    )

    # 限流配置
    rate_limit_rpm: int = Field(
        default=60,
        validation_alias=AliasChoices("RATE_LIMIT_RPM", "RATE_LIMIT_PER_MINUTE"),
        description="Rate limit: requests per minute",
    )
    rate_limit_rph: int = Field(
        default=1000,
        validation_alias=AliasChoices("RATE_LIMIT_RPH", "RATE_LIMIT_PER_HOUR"),
        description="Rate limit: requests per hour",
    )

    # 并发控制
    max_concurrent_llm_calls: int = Field(
        default=50,
        validation_alias=AliasChoices("MAX_CONCURRENT_LLM_CALLS", "MAX_LLM_CONCURRENCY"),
        description="Maximum concurrent LLM calls",
    )
    max_concurrent_per_user: int = Field(
        default=5,
        validation_alias=AliasChoices("MAX_CONCURRENT_PER_USER", "MAX_USER_CONCURRENCY"),
        description="Maximum concurrent requests per user",
    )

    # Auth
    secret_key: str = Field(
        ...,  # 强制要求配置，不提供默认值
        validation_alias=AliasChoices("SECRET_KEY", "JWT_SECRET_KEY", "AUTH_SECRET_KEY"),
        description="JWT secret key (REQUIRED - must be set in environment)",
    )
    algorithm: str = Field(
        default="HS256",
        validation_alias=AliasChoices("JWT_ALGORITHM", "AUTH_ALGORITHM"),
        description="JWT signing algorithm",
    )
    access_token_expire_minutes: int = Field(
        default=60 * 24 * 3,  # 3 days (安全优化：从 7 天缩短到 3 天)
        validation_alias=AliasChoices(
            "ACCESS_TOKEN_EXPIRE_MINUTES", "JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "AUTH_ACCESS_TOKEN_EXPIRE_MINUTES"
        ),
        description="Access token expiration time in minutes",
    )
    refresh_token_expire_days: int = Field(
        default=30,  # 30 days
        validation_alias=AliasChoices(
            "REFRESH_TOKEN_EXPIRE_DAYS", "JWT_REFRESH_TOKEN_EXPIRE_DAYS", "AUTH_REFRESH_TOKEN_EXPIRE_DAYS"
        ),
        description="Refresh token expiration time in days",
    )
    disable_auth: bool = Field(
        default=False,  # 默认启用认证（安全第一）
        description="Disable API authentication (ONLY for development - NOT recommended)",
    )
    require_email_verification: bool = Field(
        default=False,  # 默认不强制（兼容性考虑）
        description="Require email verification before login (recommended for production)",
    )

    # Cookie 配置
    cookie_name: str = Field(
        default="auth_token",
        validation_alias=AliasChoices("COOKIE_NAME", "AUTH_COOKIE_NAME"),
        description="Authentication cookie name",
    )
    cookie_domain: Optional[str] = Field(
        default=None,  # 生产环境设置为 ".example.com"
        validation_alias=AliasChoices("COOKIE_DOMAIN", "AUTH_COOKIE_DOMAIN"),
        description="Cookie domain (e.g., '.example.com' for production)",
    )
    cookie_secure: bool = Field(
        default=False,
        validation_alias=AliasChoices("COOKIE_SECURE", "AUTH_COOKIE_SECURE"),
        description="Cookie Secure flag (auto-enabled in production)",
    )
    cookie_samesite: str = Field(
        default="lax",  # "lax" | "strict" | "none"
        validation_alias=AliasChoices("COOKIE_SAMESITE", "AUTH_COOKIE_SAMESITE"),
        description="Cookie SameSite attribute (lax, strict, none)",
    )

    @property
    def cookie_secure_effective(self) -> bool:
        """根据环境自动设置 Cookie Secure 标志"""
        # 生产环境自动启用 Secure
        if self.environment == "production":
            return True
        # 开发环境根据配置决定
        return self.cookie_secure

    # CORS
    cors_origins: List[str] = Field(
        default=["http://localhost:3000", "http://localhost:3001"],
        validation_alias=AliasChoices("CORS_ORIGINS", "CORS_ALLOWED_ORIGINS"),
        description="Allowed CORS origins (comma-separated string or JSON array)",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        """解析 CORS origins，支持字符串（逗号分隔或单个值）和列表格式"""
        if isinstance(v, str):
            # 如果是字符串，按逗号分割并去除空白
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        elif isinstance(v, list):
            return v
        else:
            return []

    # Frontend URL (for email links)
    frontend_url: str = Field(
        default="http://localhost:3001",
        validation_alias=AliasChoices("FRONTEND_URL", "FRONTEND_URI", "APP_FRONTEND_URL"),
        description="Frontend URL for email links and redirects",
    )

    # Email / SMTP
    smtp_host: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("SMTP_HOST", "EMAIL_HOST"), description="SMTP server host"
    )
    smtp_port: int = Field(
        default=587, validation_alias=AliasChoices("SMTP_PORT", "EMAIL_PORT"), description="SMTP server port"
    )
    smtp_user: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("SMTP_USER", "SMTP_USERNAME", "EMAIL_USER", "EMAIL_USERNAME"),
        description="SMTP authentication username",
    )
    smtp_password: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("SMTP_PASSWORD", "EMAIL_PASSWORD"),
        description="SMTP authentication password",
    )
    from_email: str = Field(
        default="noreply@joysafeter.ai",
        validation_alias=AliasChoices("FROM_EMAIL", "EMAIL_FROM", "SMTP_FROM_EMAIL"),
        description="Default sender email address",
    )
    from_name: str = Field(
        default="JoySafeter",
        validation_alias=AliasChoices("FROM_NAME", "EMAIL_FROM_NAME", "SMTP_FROM_NAME"),
        description="Default sender name",
    )

    # 注意：所有模型配置和凭据应通过前端页面配置，存储在数据库中
    # 不再支持通过环境变量配置模型和凭据
    # - 模型配置：存储在 ModelInstance 表中（包括默认模型标记）
    # - 凭据配置：存储在 ModelCredential 表中（加密存储）

    # Langfuse (Observability)
    langfuse_public_key: Optional[str] = Field(default=None, description="Langfuse public key for observability")
    langfuse_secret_key: Optional[str] = Field(default=None, description="Langfuse secret key for observability")
    langfuse_host: Optional[str] = Field(
        default="https://cloud.langfuse.com", description="Langfuse host URL (default: cloud.langfuse.com)"
    )
    langfuse_enabled: bool = Field(
        default=False, description="Enable Langfuse tracing (requires langfuse_public_key and langfuse_secret_key)"
    )

    # UV Package Manager Configuration
    uv_index_url: str = Field(
        default="https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple",
        validation_alias=AliasChoices("UV_INDEX_URL", "PIP_INDEX_URL"),
        description="PyPI index URL for UV and pip",
    )

    # Model Provider Sync
    auto_sync_providers_on_startup: bool = Field(
        default=False,
        description="[已废弃] 供应商信息现在直接从代码加载，此配置已不再使用。如需同步模型列表和全局凭据，请手动调用 /api/v1/model-providers/sync 接口",
    )

    # Credential Encryption
    credential_encryption_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("ENCRYPTION_KEY", "CREDENTIAL_ENCRYPTION_KEY"),
        description="凭据加密密钥（生产环境必须配置，否则每次重启会生成随机密钥导致无法解密）",
    )

    # Workspace
    workspace_root: str = Field(
        default=str(BASE_DIR / "workspace"),
        validation_alias=AliasChoices("WORKSPACE_ROOT", "WORKSPACE_PATH"),
        description="Workspace root directory for storing session files and workspace data",
    )

    @property
    def WORKSPACE_ROOT(self) -> str:
        """Alias for workspace_root for backward compatibility"""
        return self.workspace_root

    # OAuth Configuration
    oauth_config_path: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("OAUTH_CONFIG_PATH", "OAUTH_PROVIDERS_CONFIG"),
        description="OAuth providers configuration file path (default: config/oauth_providers.yaml)",
    )

    # Default Model Cache (runtime cache, not from env)
    _default_model_config: Optional[Dict[str, Any]] = None


settings = Settings()  # type: ignore[call-arg]


def get_default_model_config() -> Optional[Dict[str, Any]]:
    """获取缓存的默认模型配置"""
    return settings._default_model_config


def set_default_model_config(config: Dict[str, Any]) -> None:
    """设置默认模型配置缓存"""
    settings._default_model_config = config


def clear_default_model_config() -> None:
    """清除默认模型配置缓存"""
    settings._default_model_config = None
