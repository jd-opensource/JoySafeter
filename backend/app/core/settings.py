"""
Application configuration.
"""

import os
import socket
from pathlib import Path
from typing import List, Optional, Union

from loguru import logger
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine.url import make_url

from app import __version__

# get project root directory (backend directory)
# from app/core/settings.py go up two levels to backend/
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = BASE_DIR / ".env"


def _is_tcp_port_open(host: str, port: int, timeout_seconds: float = 0.5) -> bool:
    """Check whether a TCP port is open."""
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


class Settings(BaseSettings):
    """Application configuration."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = Field(default="JoySafeter", description="Application name")
    app_version: str = Field(default=__version__, description="Application version")
    debug: bool = Field(
        default=False, validation_alias=AliasChoices("DEBUG", "APP_DEBUG"), description="Enable debug mode"
    )
    environment: str = Field(
        default="development",
        validation_alias=AliasChoices("ENVIRONMENT", "ENV", "APP_ENV"),
        description="Application environment (development, staging, production)",
    )

    # Server
    backend_port: int = Field(
        default=8000,
        validation_alias=AliasChoices("BACKEND_PORT", "PORT"),
        description="Backend server port",
    )
    # API settings
    api_v1_prefix: str = "/api/v1"
    reload: bool = Field(
        default=True,
        validation_alias=AliasChoices("RELOAD", "AUTO_RELOAD"),
        description="Enable auto-reload on code changes",
    )
    workers: int = Field(
        default=1, validation_alias=AliasChoices("WORKERS", "UVICORN_WORKERS"), description="Number of worker processes"
    )
    run_runtime_instance_id: str = Field(
        default=socket.gethostname(),
        validation_alias=AliasChoices("RUN_RUNTIME_INSTANCE_ID", "APP_RUNTIME_INSTANCE_ID"),
        description="Stable runtime owner id for in-process long-task recovery",
    )
    run_heartbeat_interval_seconds: int = Field(
        default=15,
        validation_alias=AliasChoices("RUN_HEARTBEAT_INTERVAL_SECONDS", "AGENT_RUN_HEARTBEAT_INTERVAL_SECONDS"),
        description="Heartbeat interval for active durable runs",
    )
    run_heartbeat_timeout_seconds: int = Field(
        default=90,
        validation_alias=AliasChoices("RUN_HEARTBEAT_TIMEOUT_SECONDS", "AGENT_RUN_HEARTBEAT_TIMEOUT_SECONDS"),
        description="Heartbeat timeout before a running durable run is considered orphaned",
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
        Build database connection URL from POSTGRES_* environment variables.

        Automatically handle two scenarios:
        1. Backend running locally: use localhost + POSTGRES_PORT_HOST (if set) or 5432
        2. Inside the same docker-compose: use service name (e.g. "db") + container-internal port 5432
        """
        postgres_host = os.getenv("POSTGRES_HOST", "localhost")
        postgres_user = os.getenv("POSTGRES_USER", "postgres")
        postgres_password = os.getenv("POSTGRES_PASSWORD", "postgres")
        postgres_db = os.getenv("POSTGRES_DB", "joysafeter")

        # determine port:
        if postgres_host in ("localhost", "127.0.0.1", "::1"):
            # local startup: check for Docker mapped port config
            postgres_port_host = os.getenv("POSTGRES_PORT_HOST")
            postgres_port = postgres_port_host if postgres_port_host else os.getenv("POSTGRES_PORT", "5432")
        else:
            # remote or docker-compose: prefer POSTGRES_PORT, default 5432 (container-internal port)
            postgres_port = os.getenv("POSTGRES_PORT", "5432")

        database_url = (
            f"postgresql+asyncpg://{postgres_user}:{postgres_password}@{postgres_host}:{postgres_port}/{postgres_db}"
        )

        # auto-fix port for localhost (see scripts/view_db.py)
        # resolve common issue: .env has 5433 (docker) but local startup needs 5432, or vice versa
        try:
            url = make_url(database_url)
            host = url.host
            port = url.port

            if host in ("localhost", "127.0.0.1", "::1") and port:
                if not _is_tcp_port_open(host, port):
                    # if the configured port is unreachable but 5432 is, auto-switch
                    if port != 5432 and _is_tcp_port_open(host, 5432):
                        url = url.set(port=5432)
                        database_url = url.render_as_string(hide_password=False)
                        logger.warning(f"Database connection to {host}:{port} failed, auto-switched to 5432")
        except Exception:
            pass  # Fall through to use original database_url; port auto-detect is best-effort

        return database_url

    # Sync database URL for Alembic
    @property
    def database_url_sync(self) -> str:
        """Synchronous database URL (for Alembic)."""
        return self.database_url.replace("+asyncpg", "")

    # Redis (cache & rate limiting)
    redis_url: Optional[str] = Field(default=None, validation_alias="REDIS_URL", description="Redis connection URL")
    redis_pool_size: int = Field(
        default=10,
        validation_alias=AliasChoices("REDIS_POOL_SIZE", "REDIS_CONNECTION_POOL_SIZE"),
        description="Redis connection pool size",
    )

    # rate limiting
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

    # concurrency control
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
        ...,  # required — no default value provided
        validation_alias=AliasChoices("SECRET_KEY", "JWT_SECRET_KEY", "AUTH_SECRET_KEY"),
        description="JWT secret key (REQUIRED - must be set in environment)",
    )
    algorithm: str = Field(
        default="HS256",
        validation_alias=AliasChoices("JWT_ALGORITHM", "AUTH_ALGORITHM"),
        description="JWT signing algorithm",
    )
    access_token_expire_minutes: int = Field(
        default=60 * 24 * 3,  # 3 days (security: shortened from 7 days)
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
        default=False,  # auth enabled by default (security first)
        description="Disable API authentication (ONLY for development - NOT recommended)",
    )
    require_email_verification: bool = Field(
        default=False,  # not enforced by default (for backward compatibility)
        description="Require email verification before login (recommended for production)",
    )

    # Cookie configuration
    cookie_name: str = Field(
        default="auth_token",
        validation_alias=AliasChoices("COOKIE_NAME", "AUTH_COOKIE_NAME"),
        description="Authentication cookie name",
    )
    cookie_domain: Optional[str] = Field(
        default=None,  # set to ".example.com" in production
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
    cookie_max_age: int = Field(
        default=259200,  # 3 days in seconds
        validation_alias=AliasChoices("COOKIE_MAX_AGE", "AUTH_COOKIE_MAX_AGE"),
        description="Cookie max-age in seconds (default: 3 days)",
    )

    @property
    def cookie_secure_effective(self) -> bool:
        """Auto-set Cookie Secure flag based on environment."""
        # auto-enable Secure in production
        if self.environment == "production":
            return True
        # in development, follow explicit config
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
        """Parse CORS origins; accept a string (comma-separated or single value) or list."""
        if isinstance(v, str):
            v = v.strip()
            # support JSON array format, e.g. ["http://localhost:3000"]
            if v.startswith("[") and v.endswith("]"):
                try:
                    import json

                    parsed = json.loads(v)
                    if isinstance(parsed, list):
                        return [str(origin).strip() for origin in parsed if origin]
                except Exception:
                    pass  # JSON parse failed; fall through to comma-split
            # plain comma-separated string
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        elif isinstance(v, list):
            return [str(origin).strip() for origin in v if origin]
        else:
            return []

    cors_origin_regex: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("CORS_ORIGIN_REGEX"),
        description="Regex string for allowed CORS origins",
    )

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

    # Note: all model configuration and credentials should be managed via the frontend UI
    # and stored in the database. Environment-variable-based model/credential config is no longer supported.
    # - Model config: stored in the ModelInstance table (including default model flag)
    # - Credentials: stored in the ModelCredential table (encrypted)

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
        default="https://pypi.org/simple",
        validation_alias=AliasChoices("UV_INDEX_URL", "PIP_INDEX_URL"),
        description="PyPI index URL for UV and pip",
    )

    # Credential Encryption
    credential_encryption_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("ENCRYPTION_KEY", "CREDENTIAL_ENCRYPTION_KEY"),
        description="Credential encryption key (must be set in production; otherwise a random key is generated on each restart, making decryption impossible)",
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


settings = Settings()  # type: ignore[call-arg]
