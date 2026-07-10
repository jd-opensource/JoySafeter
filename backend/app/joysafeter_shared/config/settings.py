"""
Application configuration.
"""

import os
import socket
from pathlib import Path
from typing import Annotated, List, Optional, Union

from loguru import logger
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine.url import make_url

from app import __version__

# get project root directory (backend directory)
# from app/shared/config/settings.py go up three levels to backend/
BASE_DIR = Path(__file__).resolve().parents[3]
ENV_FILE = BASE_DIR / ".env"

# Load .env into os.environ early so that @property helpers using os.getenv()
# (e.g. database_url) pick up .env values even at module-import time.
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ENV_FILE, override=False)


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
    app_version: str = Field(default=__version__, exclude=True, description="Application version")

    @field_validator("app_version", mode="before")
    @classmethod
    def _force_code_version(cls, v: str) -> str:  # noqa: ARG003
        """Always use the version from code, ignore env/config overrides."""
        return __version__

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
    orchestrator_http_host: str = Field(
        default="127.0.0.1",
        validation_alias=AliasChoices("ORCHESTRATOR_HTTP_HOST", "JOYSAFETER_ORCHESTRATOR_HTTP_HOST"),
        description="Orchestrator HTTP bind host for health/internal endpoints",
    )
    worker_http_host: str = Field(
        default="127.0.0.1",
        validation_alias=AliasChoices("WORKER_HTTP_HOST", "JOYSAFETER_WORKER_HTTP_HOST"),
        description="Worker HTTP bind host for health/internal endpoints",
    )
    # API settings — all live endpoints are served under /api/v1.
    reload: bool = Field(
        default=True,
        validation_alias=AliasChoices("RELOAD", "AUTO_RELOAD"),
        description="Enable auto-reload on code changes",
    )
    workers: int = Field(
        default=1, validation_alias=AliasChoices("WORKERS", "UVICORN_WORKERS"), description="Number of worker processes"
    )
    service_role: str = Field(
        default="api",
        validation_alias=AliasChoices("JOYSAFETER_SERVICE_ROLE", "SERVICE_ROLE", "APP_SERVICE_ROLE"),
        description="Python service role to start: api or worker. The orchestrator is the Rust binary.",
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
        default=20,
        validation_alias=AliasChoices("DATABASE_POOL_SIZE", "DB_POOL_SIZE"),
        description="Database connection pool size",
    )
    database_max_overflow: int = Field(
        default=40,
        validation_alias=AliasChoices("DATABASE_MAX_OVERFLOW", "DB_MAX_OVERFLOW"),
        description="Database connection pool max overflow",
    )
    database_pgbouncer: bool = Field(
        default=False,
        validation_alias=AliasChoices("DATABASE_PGBOUNCER", "PGBOUNCER_ENABLED"),
        description="Enable PgBouncer-compatible mode (transaction pooling)",
    )
    checkpointer_pool_min_size: int = Field(
        default=1,
        validation_alias=AliasChoices(
            "DB_POOL_MIN_SIZE",
        ),
        description="Min connections for the LangGraph checkpointer psycopg pool",
    )
    checkpointer_pool_max_size: int = Field(
        default=10,
        validation_alias=AliasChoices(
            "DB_POOL_MAX_SIZE",
        ),
        description="Max connections for the LangGraph checkpointer psycopg pool",
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
        default=50,
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
    max_concurrent_per_project: int = Field(
        default=5,
        validation_alias=AliasChoices("MAX_CONCURRENT_PER_PROJECT", "MAX_PROJECT_CONCURRENCY"),
        description="Default maximum concurrent (non-terminal) tasks per project (tenant). "
        "A project may override this via its max_concurrent_tasks column.",
    )

    # Scheduler (cron-driven task trigger; runs inside the worker service)

    scheduler_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("SCHEDULER_ENABLED"),
        description="Whether the worker runs the cron scheduler poll loop.",
    )
    scheduler_poll_interval_sec: int = Field(
        default=15,
        validation_alias=AliasChoices("SCHEDULER_POLL_INTERVAL_SEC"),
        description="Seconds between scheduler poll ticks.",
    )
    scheduler_claim_batch: int = Field(
        default=50,
        validation_alias=AliasChoices("SCHEDULER_CLAIM_BATCH"),
        description="Max due schedules claimed per tick (FOR UPDATE SKIP LOCKED batch size).",
    )
    scheduler_lock_grace_sec: int = Field(
        default=120,
        validation_alias=AliasChoices("SCHEDULER_LOCK_GRACE_SEC"),
        description="Seconds after which a claimed-but-unreleased schedule lock is considered stale "
        "and reclaimable by another worker (crash recovery).",
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
        default=15,  # 15 minutes — short-lived, use refresh_token to renew
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

    # OpenTelemetry Trace Export
    otel_exporter_otlp_endpoint: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_ENDPOINT"),
        description="OTLP gRPC endpoint for trace export (e.g. http://localhost:4317). Disabled when unset.",
    )
    otel_exporter_otlp_protocol: str = Field(
        default="grpc",
        validation_alias="OTEL_EXPORTER_OTLP_PROTOCOL",
        description="OTLP transport protocol: 'grpc' or 'http/protobuf'",
    )

    # Artifact Storage
    agent_artifacts_root: Optional[str] = Field(
        default=None,
        description="Root directory for agent artifacts (default: ~/.agent-platform/agent-artifacts)",
    )
    deepagents_artifacts_dir: Optional[str] = Field(
        default=None,
        description="Root directory for DeepAgents artifacts",
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

    # Session filesystem root (legacy name: workspace_root)
    workspace_root: str = Field(
        default=str(BASE_DIR / "workspace"),
        validation_alias=AliasChoices("WORKSPACE_ROOT", "WORKSPACE_PATH"),
        description="Root directory for storing session files and sandbox data",
    )

    # Skill security scanning
    skill_security_scan_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("SKILL_SECURITY_SCAN_ENABLED", "JOYSAFETER_SKILL_SECURITY_SCAN_ENABLED"),
        description="Enable Skill security scanning before skill writes.",
    )
    skill_security_scanner_url: str = Field(
        default="http://skillspector:8010",
        validation_alias=AliasChoices("SKILL_SECURITY_SCANNER_URL", "SKILLSPECTOR_URL"),
        description="Internal SkillSpector scanner service URL.",
    )
    skill_security_timeout_seconds: float = Field(
        default=30.0,
        validation_alias=AliasChoices("SKILL_SECURITY_TIMEOUT_SECONDS", "SKILLSPECTOR_TIMEOUT_SECONDS"),
        description="Skill security scanner request timeout.",
    )
    skill_security_fail_closed: bool = Field(
        default=True,
        validation_alias=AliasChoices("SKILL_SECURITY_FAIL_CLOSED", "SKILLSPECTOR_FAIL_CLOSED"),
        description="Reject skill writes when the scanner fails.",
    )
    skill_security_no_llm: bool = Field(
        default=True,
        validation_alias=AliasChoices("SKILL_SECURITY_NO_LLM", "SKILLSPECTOR_NO_LLM"),
        description="Run SkillSpector without LLM analysis by default.",
    )
    skill_security_block_recommendations: Annotated[List[str], NoDecode] = Field(
        default=["DO_NOT_INSTALL"],
        validation_alias=AliasChoices(
            "SKILL_SECURITY_BLOCK_RECOMMENDATIONS",
            "SKILLSPECTOR_BLOCK_RECOMMENDATIONS",
        ),
        description="Scanner recommendations that can reject skill writes when issue details are unavailable.",
    )
    # P2: scans larger than this run as a FastAPI BackgroundTask instead
    # of blocking the request. The unit is total scan-input bytes
    # (SKILL.md frontmatter + concatenated file contents); the call site
    # passes ``mode='auto'`` to ``scan_for_write`` and the service
    # decides per-skill. Set to 0 to force every scan async; set very
    # high to keep the pre-P2 sync-only behavior.
    skill_security_async_threshold_bytes: int = Field(
        default=100 * 1024,
        validation_alias=AliasChoices(
            "SKILL_SECURITY_ASYNC_THRESHOLD_BYTES",
            "SKILLSPECTOR_ASYNC_THRESHOLD_BYTES",
        ),
        description="Total scan-input size above which scan_for_write defers to a background task.",
    )

    @field_validator("skill_security_block_recommendations", mode="before")
    @classmethod
    def parse_skill_security_block_recommendations(cls, v: Union[str, List[str]]) -> List[str]:
        """Parse recommendation names from CSV or JSON-array env vars."""
        if isinstance(v, str):
            value = v.strip()
            if value.startswith("[") and value.endswith("]"):
                try:
                    import json

                    parsed = json.loads(value)
                    if isinstance(parsed, list):
                        return [str(item).strip().upper() for item in parsed if str(item).strip()]
                except Exception:
                    pass
            return [item.strip().upper() for item in value.split(",") if item.strip()]
        if isinstance(v, list):
            return [str(item).strip().upper() for item in v if str(item).strip()]
        return []

    # Skill ZIP import limits — protect against zip bombs / huge uploads while
    # still allowing legitimate skills with many reference files. All four can
    # be tuned independently via env vars.
    skill_import_max_zip_bytes: int = Field(
        default=20 * 1024 * 1024,
        validation_alias=AliasChoices(
            "SKILL_IMPORT_MAX_ZIP_BYTES",
            "JOYSAFETER_SKILL_IMPORT_MAX_ZIP_BYTES",
        ),
        description="Max raw ZIP archive size accepted for skill import (bytes).",
    )
    skill_import_max_files: int = Field(
        default=200,
        validation_alias=AliasChoices(
            "SKILL_IMPORT_MAX_FILES",
            "JOYSAFETER_SKILL_IMPORT_MAX_FILES",
        ),
        description="Max number of files inside a skill-import ZIP.",
    )
    skill_import_max_file_bytes: int = Field(
        default=2 * 1024 * 1024,
        validation_alias=AliasChoices(
            "SKILL_IMPORT_MAX_FILE_BYTES",
            "JOYSAFETER_SKILL_IMPORT_MAX_FILE_BYTES",
        ),
        description="Max size of any single file inside a skill-import ZIP (bytes).",
    )
    skill_import_max_total_file_bytes: int = Field(
        default=10 * 1024 * 1024,
        validation_alias=AliasChoices(
            "SKILL_IMPORT_MAX_TOTAL_FILE_BYTES",
            "JOYSAFETER_SKILL_IMPORT_MAX_TOTAL_FILE_BYTES",
        ),
        description="Max combined uncompressed size of all files in a skill-import ZIP (bytes).",
    )
    max_upload_file_bytes: int = Field(
        default=50 * 1024 * 1024,
        validation_alias=AliasChoices(
            "JOYSAFETER_MAX_UPLOAD_FILE_BYTES",
            "MAX_UPLOAD_FILE_BYTES",
        ),
        description="Max size accepted by the user file upload APIs (bytes).",
    )

    # OAuth Configuration
    oauth_config_path: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("OAUTH_CONFIG_PATH", "OAUTH_PROVIDERS_CONFIG"),
        description="OAuth providers configuration file path (default: config/oauth_providers.yaml)",
    )


settings = Settings()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# JoySafeter Orchestrator Configuration
# ---------------------------------------------------------------------------


class JoySafeterConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JOYSAFETER_", extra="ignore")

    enabled: bool = True

    api_prefix: str = "/api/v1"

    redis_queue_prefix: str = "joysafeter"

    max_concurrent_tasks: int = 200
    max_scheduling_tasks: int = 50
    task_default_timeout: int = 7200
    task_default_max_retries: int = 2
    task_retry_base_ms: int = 2000
    task_retry_max_ms: int = 30000

    # Multi-image map: per-model sandbox images
    image_claude: str = ""
    image_codex: str = ""
    image_native: str = ""

    # Event batching
    event_batch_enabled: bool = True
    event_batch_max_size: int = 200
    event_batch_max_delay_ms: int = 100
    event_stream_enabled: bool = False
    event_stream_key: str = "joysafeter:orchestrator:events"
    event_stream_group: str = "joysafeter-orchestrator-event-workers"
    event_stream_max_len: int = 100000
    event_stream_batch_size: int = 100
    event_stream_block_ms: int = 1000
    event_stream_fallback_to_db: bool = True
    event_stream_pending_idle_ms: int = 60000
    # A message reclaimed this many times without being acked is a poison
    # message; it is moved to the dead-letter stream so it can't loop forever.
    event_stream_max_deliveries: int = 5
    event_stream_dead_letter_suffix: str = ":dead"
    # When the stream length reaches this, an xadd would trim un-consumed
    # entries; producers route events to the DB fallback instead of losing them.
    # <= 0 auto-derives 90% of event_stream_max_len.
    event_stream_high_water_mark: int = 0

    # Sandbox - Docker (default)
    sandbox_provider: str = "docker"
    # Minimum provider isolation accepted by the runtime:
    # shared_container=docker, remote_workspace=daytona+, isolated_vm=e2b only.
    sandbox_min_isolation_class: str = "shared_container"
    sandbox_image: str = "joysafeter-claudecode:latest"
    sandbox_idle_timeout: int = 300
    sandbox_stopped_ttl: int = 600
    # Hard wall-clock cap on any non-terminal sandbox lifetime: reaps zombies
    # whose runner crashed before sending RunnerIdle and whose heartbeat
    # never timed out (e.g. provider froze). 0 disables. Default 6h.
    sandbox_hard_timeout: int = 6 * 3600
    # Grace period for a sandbox whose bridge has been disconnected — once the
    # bridge is gone we can no longer learn anything new about the runner, so
    # we wait this long before declaring it dead. Default 90s.
    sandbox_bridge_disconnect_grace: int = 90
    sandbox_pool_enabled: bool = False
    sandbox_pool_min_size: int = 2
    sandbox_pool_max_age: int = 1800
    sandbox_pool_images: list[str] = []
    sandbox_workspace_root: Optional[str] = None
    sandbox_failure_threshold: int = 3
    # Per-container resource limits, applied to every Docker sandbox via the
    # provider (NanoCpus / Memory). Enforced-by-default so a single tenant's
    # agent cannot exhaust host CPU/RAM on the shared fleet (noisy-neighbor /
    # resource-exhaustion DoS). Override per-deployment via env
    # (JOYSAFETER_SANDBOX_CPU / _MEMORY_MB) or per-project via the Project
    # max_cpu / max_memory_mb columns. Set to None to disable the limit.
    sandbox_cpu: Optional[float] = 2.0
    sandbox_memory_mb: Optional[int] = 4096
    sandbox_disk_mb: Optional[int] = None

    # -- Sandbox container hardening (P0.1) ------------------------------------
    # These default to the values from Anthropic's "Securely deploying AI agents"
    # guide, applied via the docker provider when launching every sandbox
    # container. They tighten the privilege boundary an attacker would need to
    # cross if prompt injection lands code execution inside the sandbox.
    #
    # All four can be disabled per-deployment via env vars (e.g. to debug a
    # stuck capability), but the secure defaults should stay on in any non-dev
    # deployment. Turning them off should be an explicit, recorded decision.
    #
    # Linux capabilities: drop the full default-14 set Docker grants. Coding
    # agents (cc/codex/native) run as non-root inside the container and never
    # call syscalls that require any cap, so this has no operational impact —
    # but it removes the privilege escalation surface that would open up if an
    # attacker found a setuid binary or pivoted to root some other way.
    sandbox_drop_all_caps: bool = True
    # Forbid setuid/file-capability based privilege escalation entirely. With
    # this on, even a setuid-root binary inside the container can't escalate
    # — `sudo`, `mount`, `ping`, etc. simply fail. Coding agents don't need
    # any of these. Safe default.
    sandbox_no_new_privileges: bool = True
    # Cap on the number of processes the sandbox can spawn. Prevents fork
    # bombs and runaway test loops. 256 is generous for a coding agent
    # (compilation can fan out, but rarely past a few dozen).
    sandbox_pids_limit: int = 256
    # Force-run the sandbox process as this uid:gid even if the image's
    # USER directive was overridden / removed. Defense in depth — our base
    # images already USER agent (uid 1000), but this guarantees it.
    # Set to empty string to skip (use the image default).
    sandbox_run_as_user: str = "1000:1000"

    # Sandbox - Daytona
    daytona_api_url: str = ""
    daytona_api_key: str = ""
    daytona_target: Optional[str] = None
    daytona_snapshot: str = ""

    # Sandbox - E2B
    e2b_api_url: Optional[str] = None
    e2b_api_key: str = ""
    e2b_template_id: str = ""

    # gRPC server
    grpc_port: int = 9090
    grpc_host: str = "0.0.0.0"
    grpc_public_url: Optional[str] = None

    # Envoy network isolation
    envoy_enabled: bool = False
    envoy_image: str = "envoyproxy/envoy:v1.31-latest"
    envoy_socket_volume: str = "joysafeter-sockets"
    envoy_config_dir: str = "/tmp/joysafeter-envoy-config"
    envoy_network: str = "joysafeter-net"
    envoy_grpc_host: str = "host.docker.internal"
    envoy_grpc_port: int = 9090
    envoy_container_name: str = "joysafeter-envoy"

    # Image builder
    image_builder_enabled: bool = False
    image_builder_base: str = "joysafeter-claudecode:latest"

    # Vault encryption
    vault_encryption_key: Optional[str] = None

    # HA
    instance_id: str = Field(default_factory=socket.gethostname)
    heartbeat_interval: int = 15
    heartbeat_ttl: int = 30

    # Running-task lease (fast reclaim of tasks orphaned by a crashed instance).
    # The owning instance renews its running tasks' leases every
    # task_lease_renew_interval_sec; a lease older than task_lease_ttl_sec is
    # considered abandoned and reclaimed in seconds instead of waiting for the
    # ~2h timeout_sec upper bound. TTL must be a comfortable multiple of the
    # renew interval so a live owner never lets its own lease lapse.
    task_lease_ttl_sec: int = 45
    task_lease_renew_interval_sec: int = 10

    def image_for_provider(self, engine_kind: str) -> str:
        """Return the sandbox image for the given engine kind (matches Rust)."""
        if engine_kind == "codex" and self.image_codex:
            return self.image_codex
        if engine_kind == "claude" and self.image_claude:
            return self.image_claude
        if engine_kind == "native":
            return (
                self.image_native
                if self.image_native
                else (self.image_claude if self.image_claude else self.sandbox_image)
            )
        return self.sandbox_image


joysafeter_config = JoySafeterConfig()
