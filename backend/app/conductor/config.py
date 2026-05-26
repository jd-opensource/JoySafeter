import socket
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConductorConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CONDUCTOR_", extra="ignore")

    enabled: bool = False

    api_prefix: str = "/api/v2/conductor"

    redis_queue_prefix: str = "conductor"

    max_concurrent_tasks: int = 200
    task_default_timeout: int = 7200
    task_default_max_retries: int = 2
    task_retry_base_ms: int = 2000
    task_retry_max_ms: int = 30000

    # Multi-image map: per-model sandbox images
    image_claude: str = "conductor-claudecode:arm64"
    image_codex: str = "conductor-codex:arm64"

    # Event batching
    event_batch_enabled: bool = False
    event_batch_max_size: int = 50
    event_batch_max_delay_ms: int = 50

    # Sandbox - Docker (default)
    sandbox_provider: str = "docker"
    sandbox_image: str = "joysafeter/cli-agent:latest"
    sandbox_idle_timeout: int = 300
    sandbox_stopped_ttl: int = 600
    sandbox_pool_enabled: bool = False
    sandbox_pool_min_size: int = 2
    sandbox_pool_max_age: int = 1800
    sandbox_pool_images: list[str] = []
    sandbox_workspace_root: Optional[str] = None
    sandbox_failure_threshold: int = 3
    sandbox_cpu: Optional[float] = None
    sandbox_memory_mb: Optional[int] = None
    sandbox_disk_mb: Optional[int] = None

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
    envoy_socket_volume: str = "conductor-sockets"
    envoy_config_dir: str = "/tmp/conductor-envoy-config"
    envoy_network: str = "conductor-net"
    envoy_grpc_host: str = "host.docker.internal"
    envoy_grpc_port: int = 9090
    envoy_container_name: str = "conductor-envoy"

    # Image builder
    image_builder_enabled: bool = False
    image_builder_base: str = "joysafeter/cli-agent:latest"

    # Vault encryption
    vault_encryption_key: Optional[str] = None

    # HA
    instance_id: str = Field(default_factory=socket.gethostname)
    heartbeat_interval: int = 15
    heartbeat_ttl: int = 30


conductor_config = ConductorConfig()
