use std::env;
use std::net::SocketAddr;

/// JoySafeter kernel configuration.
///
/// Matches the Python `JoySafeterConfig` from `joysafeter_shared/config/settings.py`,
/// reading from `JOYSAFETER_*` environment variables.
#[derive(Debug, Clone)]
pub struct JoySafeterConfig {
    pub instance_id: String,
    pub redis_queue_prefix: String,

    // Single-active control plane
    pub control_plane_ha_enabled: bool,
    pub control_plane_lock_key: i64,
    pub control_plane_standby_retry_ms: u64,
    pub control_plane_lock_probe_interval_ms: u64,
    pub control_plane_lock_probe_timeout_ms: u64,
    pub control_plane_health_bind: String,

    // Task scheduling
    pub max_concurrent_tasks: usize,
    pub max_scheduling_tasks: usize,
    pub task_default_timeout: u64,
    pub task_default_max_retries: u32,
    pub task_retry_base_ms: u64,
    pub task_retry_max_ms: u64,
    pub task_lease_ttl_sec: i64,
    pub task_lease_renew_interval_sec: u64,

    // Sandbox - Docker (default)
    pub sandbox_provider: String,
    pub sandbox_image: String,
    pub sandbox_idle_timeout: u64,
    pub sandbox_stopped_ttl: u64,
    /// Hard wall-clock cap on any non-terminal sandbox lifetime; reaps
    /// zombies whose runner crashed before sending RunnerIdle. 0 disables.
    pub sandbox_hard_timeout: u64,
    /// Grace period for a sandbox whose bridge dropped before we conclude
    /// the runner is gone and reap. Mirrors the Python config of the same
    /// name; keep the defaults in sync.
    pub sandbox_bridge_disconnect_grace: u64,
    pub sandbox_pool_enabled: bool,
    pub sandbox_pool_min_size: usize,
    pub sandbox_pool_max_age: u64,
    pub sandbox_pool_images: Vec<String>,
    pub sandbox_failure_threshold: u32,
    pub sandbox_workspace_root: Option<String>,
    pub sandbox_cpu: Option<f64>,
    pub sandbox_memory_mb: Option<u64>,
    pub sandbox_disk_mb: Option<u64>,

    // -- Sandbox container hardening (P0.1) -----------------------------------
    // Matches the Python `Settings.sandbox_*` block of the same name. See
    // backend/app/joysafeter_shared/config/settings.py for the full rationale.
    // Defaults to the secure values from Anthropic's "Securely deploying AI
    // agents" guide; only flip these off for targeted debugging.
    /// Drop all Linux capabilities (`--cap-drop ALL`). Default true.
    pub sandbox_drop_all_caps: bool,
    /// Forbid setuid / file-cap based privilege escalation
    /// (`--security-opt no-new-privileges`). Default true.
    pub sandbox_no_new_privileges: bool,
    /// Cap on number of processes inside the sandbox. Default 256.
    pub sandbox_pids_limit: i64,
    /// `--user uid:gid` to run the sandbox process as. Empty string means
    /// "use the image's default USER" (less safe).
    pub sandbox_run_as_user: String,

    // Multi-image map
    pub image_claude: String,
    pub image_codex: String,
    pub image_native: String,

    // Event batching
    pub event_batch_enabled: bool,
    pub event_batch_max_size: usize,
    pub event_batch_max_delay_ms: u64,
    pub event_stream_enabled: bool,
    pub event_stream_key: String,
    pub event_stream_group: String,
    pub event_stream_max_len: usize,
    pub event_stream_batch_size: usize,
    pub event_stream_block_ms: u64,
    pub event_stream_fallback_to_db: bool,
    pub event_stream_pending_idle_ms: u64,

    // gRPC server
    pub grpc_host: String,
    pub grpc_port: u16,
    pub grpc_public_url: Option<String>,

    // gRPC server capacity
    pub grpc_max_connections: usize,
    pub grpc_max_executions: usize,
    pub grpc_max_memories_per_store: i64,

    // Scheduler
    pub scheduler_batch_size: usize,

    // Envoy network isolation
    pub envoy_enabled: bool,
    pub envoy_image: String,
    pub envoy_socket_volume: String,
    pub envoy_config_dir: String,
    pub envoy_network: String,
    pub envoy_grpc_host: String,
    pub envoy_grpc_port: u16,
    pub envoy_container_name: String,
    /// LDS transport: `"filesystem"` (default, `lds.json`) or `"grpc"` (Delta xDS).
    pub envoy_xds_mode: String,
    /// Host of the durable ADS endpoint used when `envoy_xds_mode ==
    /// "controller"`.
    pub egress_xds_host: String,
    /// Port of the durable ADS endpoint. Default 18000.
    pub egress_xds_port: u16,
    /// CIDRs removed from dynamic-forward-proxy DNS answers before connecting.
    pub envoy_egress_denied_cidrs: Vec<String>,
    /// Hosts that LLM egress credential routes may target. This protects the
    /// Envoy-side key injection path from sending credentials to arbitrary
    /// user-controlled base URLs.
    pub llm_egress_allowed_hosts: Vec<String>,
    /// Shared Envoy credential-listener URL used by Kubernetes sandboxes.
    pub egress_envoy_credential_url: Option<String>,
    /// Shared Envoy forward-proxy URL used by Kubernetes sandboxes.
    pub egress_envoy_forward_proxy_url: Option<String>,
    /// Public CA ConfigMap and mount path used to extend sandbox trust for the
    /// shared Envoy downstream TLS listeners.
    pub egress_downstream_ca_config_map: String,
    pub egress_downstream_ca_mount_path: String,
    /// Enable the durable PostgreSQL desired-state writer and Envoy ACK gate.
    pub egress_policy_authority_enabled: bool,
    pub egress_policy_deployment_id: String,
    pub egress_policy_environment: String,
    pub egress_policy_region: String,
    pub egress_policy_shard_id: String,
    pub egress_policy_host_id: Option<String>,
    pub egress_policy_envoy_version: String,
    pub egress_policy_config_schema_version: String,
    pub egress_policy_apply_timeout_ms: u64,
    pub egress_policy_poll_interval_ms: u64,
    /// Dedicated Rust ADS listener. When set, xDS is removed from the runner
    /// gRPC listener and served on this address instead.
    pub egress_xds_bind: Option<String>,
    pub egress_xds_mtls: bool,
    pub egress_xds_cert_file: String,
    pub egress_xds_key_file: String,
    pub egress_xds_client_ca_file: String,
    pub egress_xds_client_dns_san: String,
    /// Compile and publish PostgreSQL desired generations into the embedded
    /// Rust ADS state without changing Envoy routing or Go apply status.
    pub egress_xds_shadow_reconcile: bool,
    pub egress_xds_reconcile_interval_ms: u64,
    pub egress_xds_ack_timeout_ms: u64,
    pub egress_xds_node_lease_ttl_ms: u64,
    /// Dedicated Envoy ext_authz listener. `None` keeps only the legacy
    /// orchestrator gRPC registration for Docker compatibility.
    pub egress_authz_bind: Option<String>,
    pub egress_authz_mtls: bool,
    pub egress_authz_cert_file: String,
    pub egress_authz_key_file: String,
    pub egress_authz_client_ca_file: String,
    pub egress_authz_client_dns_san: String,
    /// Explicit feature gate for K8s credential egress. Defaults false so K8s
    /// does not claim production egress capability until operators opt in.
    pub k8s_egress_management_enabled: bool,
    /// Bind address for the credential resolution HTTP endpoint (`/resolve`).
    /// `None` disables the endpoint (data planes then cannot resolve credentials).
    pub credential_resolution_bind: Option<String>,
    /// Shared service token the data planes present to `/resolve`. `None` makes
    /// the endpoint fail closed (deny every request).
    pub credential_resolution_service_token: Option<String>,

    // Image builder
    pub image_builder_enabled: bool,
    pub image_builder_base: String,

    // Vault
    pub vault_encryption_key: Option<String>,

    // HA
    pub heartbeat_interval: u64,
    pub heartbeat_ttl: u64,

    // Sandbox - Daytona
    pub daytona_api_url: String,
    pub daytona_api_key: String,
    pub daytona_target: Option<String>,
    pub daytona_snapshot: String,

    // Sandbox - E2B
    pub e2b_api_url: Option<String>,
    pub e2b_api_key: String,
    pub e2b_template_id: String,

    // Sandbox - Kubernetes
    pub k8s_namespace: String,
    pub k8s_orchestrator_url: Option<String>,

    // Database
    pub database_url: String,

    // Redis
    pub redis_url: Option<String>,
}

impl JoySafeterConfig {
    /// Load configuration from environment variables.
    pub fn from_env() -> Self {
        Self {
            instance_id: env_str("JOYSAFETER_INSTANCE_ID", &hostname()),
            redis_queue_prefix: env_str("JOYSAFETER_REDIS_QUEUE_PREFIX", "joysafeter"),
            control_plane_ha_enabled: env_bool("JOYSAFETER_CONTROL_PLANE_HA_ENABLED", false),
            control_plane_lock_key: env_i64(
                "JOYSAFETER_CONTROL_PLANE_LOCK_KEY",
                7_421_938_472_193_848,
            ),
            control_plane_standby_retry_ms: env_u64(
                "JOYSAFETER_CONTROL_PLANE_STANDBY_RETRY_MS",
                2_000,
            ),
            control_plane_lock_probe_interval_ms: env_u64(
                "JOYSAFETER_CONTROL_PLANE_LOCK_PROBE_INTERVAL_MS",
                2_000,
            ),
            control_plane_lock_probe_timeout_ms: env_u64(
                "JOYSAFETER_CONTROL_PLANE_LOCK_PROBE_TIMEOUT_MS",
                5_000,
            ),
            control_plane_health_bind: env_str(
                "JOYSAFETER_CONTROL_PLANE_HEALTH_BIND",
                "0.0.0.0:8081",
            ),

            max_concurrent_tasks: env_usize("JOYSAFETER_MAX_CONCURRENT_TASKS", 200),
            max_scheduling_tasks: env_usize("JOYSAFETER_MAX_SCHEDULING_TASKS", 50),
            task_default_timeout: env_u64("JOYSAFETER_TASK_DEFAULT_TIMEOUT", 7200),
            task_default_max_retries: env_u32("JOYSAFETER_TASK_DEFAULT_MAX_RETRIES", 2),
            task_retry_base_ms: env_u64("JOYSAFETER_TASK_RETRY_BASE_MS", 2000),
            task_retry_max_ms: env_u64("JOYSAFETER_TASK_RETRY_MAX_MS", 30000),
            task_lease_ttl_sec: env_i64("JOYSAFETER_TASK_LEASE_TTL_SEC", 45),
            task_lease_renew_interval_sec: env_u64("JOYSAFETER_TASK_LEASE_RENEW_INTERVAL_SEC", 10),

            sandbox_provider: env_str("JOYSAFETER_SANDBOX_PROVIDER", "docker"),
            sandbox_image: env_str("JOYSAFETER_SANDBOX_IMAGE", "joysafeter-claudecode:latest"),
            sandbox_idle_timeout: env_u64("JOYSAFETER_SANDBOX_IDLE_TIMEOUT", 300),
            sandbox_stopped_ttl: env_u64("JOYSAFETER_SANDBOX_STOPPED_TTL", 600),
            sandbox_hard_timeout: env_u64("JOYSAFETER_SANDBOX_HARD_TIMEOUT", 6 * 3600),
            sandbox_bridge_disconnect_grace: env_u64(
                "JOYSAFETER_SANDBOX_BRIDGE_DISCONNECT_GRACE",
                90,
            ),
            sandbox_pool_enabled: env_bool("JOYSAFETER_SANDBOX_POOL_ENABLED", false),
            sandbox_pool_min_size: env_usize("JOYSAFETER_SANDBOX_POOL_MIN_SIZE", 2),
            sandbox_pool_max_age: env_u64("JOYSAFETER_SANDBOX_POOL_MAX_AGE", 1800),
            sandbox_pool_images: env_list("JOYSAFETER_SANDBOX_POOL_IMAGES"),
            sandbox_failure_threshold: env_u32("JOYSAFETER_SANDBOX_FAILURE_THRESHOLD", 3),
            sandbox_workspace_root: env::var("JOYSAFETER_SANDBOX_WORKSPACE_ROOT").ok(),
            sandbox_cpu: env::var("JOYSAFETER_SANDBOX_CPU")
                .ok()
                .and_then(|v| v.parse().ok()),
            sandbox_memory_mb: env::var("JOYSAFETER_SANDBOX_MEMORY_MB")
                .ok()
                .and_then(|v| v.parse().ok()),
            sandbox_disk_mb: env::var("JOYSAFETER_SANDBOX_DISK_MB")
                .ok()
                .and_then(|v| v.parse().ok()),

            // Hardening defaults — keep the secure defaults; only flip these
            // off for targeted debugging. See settings.py for rationale.
            sandbox_drop_all_caps: env_bool("JOYSAFETER_SANDBOX_DROP_ALL_CAPS", true),
            sandbox_no_new_privileges: env_bool("JOYSAFETER_SANDBOX_NO_NEW_PRIVILEGES", true),
            sandbox_pids_limit: env::var("JOYSAFETER_SANDBOX_PIDS_LIMIT")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(256),
            sandbox_run_as_user: env_str("JOYSAFETER_SANDBOX_RUN_AS_USER", "1000:1000"),
            image_claude: env_str("JOYSAFETER_IMAGE_CLAUDE", ""),
            image_codex: env_str("JOYSAFETER_IMAGE_CODEX", ""),
            image_native: env_str("JOYSAFETER_IMAGE_NATIVE", ""),

            event_batch_enabled: env_bool("JOYSAFETER_EVENT_BATCH_ENABLED", true),
            event_batch_max_size: env_usize("JOYSAFETER_EVENT_BATCH_MAX_SIZE", 200),
            event_batch_max_delay_ms: env_u64("JOYSAFETER_EVENT_BATCH_MAX_DELAY_MS", 100),
            event_stream_enabled: env_bool("JOYSAFETER_EVENT_STREAM_ENABLED", false),
            event_stream_key: env_str(
                "JOYSAFETER_EVENT_STREAM_KEY",
                "joysafeter:joysafeter:events",
            ),
            event_stream_group: env_str(
                "JOYSAFETER_EVENT_STREAM_GROUP",
                "joysafeter-joysafeter-event-workers",
            ),
            event_stream_max_len: env_usize("JOYSAFETER_EVENT_STREAM_MAX_LEN", 100_000),
            event_stream_batch_size: env_usize("JOYSAFETER_EVENT_STREAM_BATCH_SIZE", 100),
            event_stream_block_ms: env_u64("JOYSAFETER_EVENT_STREAM_BLOCK_MS", 1000),
            event_stream_fallback_to_db: env_bool("JOYSAFETER_EVENT_STREAM_FALLBACK_TO_DB", true),
            event_stream_pending_idle_ms: env_u64("JOYSAFETER_EVENT_STREAM_PENDING_IDLE_MS", 60000),

            grpc_host: env_str("JOYSAFETER_GRPC_HOST", "0.0.0.0"),
            grpc_port: env_u16("JOYSAFETER_GRPC_PORT", 9090),
            grpc_public_url: env::var("JOYSAFETER_GRPC_PUBLIC_URL").ok(),

            grpc_max_connections: env_usize("JOYSAFETER_GRPC_MAX_CONNECTIONS", 2000),
            grpc_max_executions: env_usize("JOYSAFETER_GRPC_MAX_EXECUTIONS", 1000),
            grpc_max_memories_per_store: env::var("JOYSAFETER_MAX_MEMORIES_PER_STORE")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(2000),

            scheduler_batch_size: env_usize("JOYSAFETER_SCHEDULER_BATCH_SIZE", 10),

            envoy_enabled: env_bool("JOYSAFETER_ENVOY_ENABLED", false),
            envoy_image: env_str(
                "JOYSAFETER_ENVOY_IMAGE",
                "envoyproxy/envoy:v1.39.0@sha256:d59f7f5fa10cff6d5892b6c5e7df5c9297ddfb2c3683e33fbfb82da24de4fa66",
            ),
            envoy_socket_volume: env_str("JOYSAFETER_ENVOY_SOCKET_VOLUME", "joysafeter-sockets"),
            envoy_config_dir: env_str(
                "JOYSAFETER_ENVOY_CONFIG_DIR",
                "/tmp/joysafeter-envoy-config",
            ),
            envoy_network: env_str("JOYSAFETER_ENVOY_NETWORK", "joysafeter-net"),
            envoy_grpc_host: env_str("JOYSAFETER_ENVOY_GRPC_HOST", "host.docker.internal"),
            envoy_grpc_port: env_u16("JOYSAFETER_ENVOY_GRPC_PORT", 9090),
            envoy_container_name: env_str("JOYSAFETER_ENVOY_CONTAINER_NAME", "joysafeter-envoy"),
            envoy_xds_mode: env_str("JOYSAFETER_ENVOY_XDS_MODE", "filesystem"),
            egress_xds_host: env_str("JOYSAFETER_EGRESS_XDS_HOST", "joysafeter-orchestrator"),
            egress_xds_port: env_u16("JOYSAFETER_EGRESS_XDS_PORT", 18000),
            envoy_egress_denied_cidrs: env_list_or_default(
                "JOYSAFETER_ENVOY_EGRESS_DENIED_CIDRS",
                &[
                    "0.0.0.0/8",
                    "10.0.0.0/8",
                    "100.64.0.0/10",
                    "127.0.0.0/8",
                    "169.254.0.0/16",
                    "172.16.0.0/12",
                    "192.0.0.0/24",
                    "192.0.2.0/24",
                    "192.168.0.0/16",
                    "198.18.0.0/15",
                    "198.51.100.0/24",
                    "203.0.113.0/24",
                    "224.0.0.0/4",
                    "240.0.0.0/4",
                    "::/128",
                    "::1/128",
                    "fc00::/7",
                    "fe80::/10",
                    "ff00::/8",
                    "2001:db8::/32",
                ],
            ),
            llm_egress_allowed_hosts: env_list("JOYSAFETER_LLM_EGRESS_ALLOWED_HOSTS"),
            egress_envoy_credential_url: env::var("JOYSAFETER_EGRESS_ENVOY_CREDENTIAL_URL")
                .ok()
                .filter(|v| !v.trim().is_empty()),
            egress_envoy_forward_proxy_url: env::var(
                "JOYSAFETER_EGRESS_ENVOY_FORWARD_PROXY_URL",
            )
            .ok()
            .filter(|v| !v.trim().is_empty()),
            egress_downstream_ca_config_map: env_str(
                "JOYSAFETER_EGRESS_DOWNSTREAM_CA_CONFIG_MAP",
                "joysafeter-egress-downstream-ca",
            ),
            egress_downstream_ca_mount_path: env_str(
                "JOYSAFETER_EGRESS_DOWNSTREAM_CA_MOUNT_PATH",
                "/var/run/joysafeter-egress/trust",
            ),
            egress_policy_authority_enabled: env_bool(
                "JOYSAFETER_EGRESS_POLICY_AUTHORITY_ENABLED",
                false,
            ),
            egress_policy_deployment_id: env_str(
                "JOYSAFETER_EGRESS_POLICY_DEPLOYMENT_ID",
                "joysafeter",
            ),
            egress_policy_environment: env_str(
                "JOYSAFETER_EGRESS_POLICY_ENVIRONMENT",
                "local",
            ),
            egress_policy_region: env_str("JOYSAFETER_EGRESS_POLICY_REGION", "local"),
            egress_policy_shard_id: env_str("JOYSAFETER_EGRESS_POLICY_SHARD_ID", "0"),
            egress_policy_host_id: env::var("JOYSAFETER_EGRESS_POLICY_HOST_ID")
                .ok()
                .filter(|value| !value.trim().is_empty()),
            egress_policy_envoy_version: env_str(
                "JOYSAFETER_EGRESS_POLICY_ENVOY_VERSION",
                "1.39.0",
            ),
            egress_policy_config_schema_version: env_str(
                "JOYSAFETER_EGRESS_POLICY_CONFIG_SCHEMA_VERSION",
                "1",
            ),
            egress_policy_apply_timeout_ms: env_u64(
                "JOYSAFETER_EGRESS_POLICY_APPLY_TIMEOUT_MS",
                30_000,
            ),
            egress_policy_poll_interval_ms: env_u64(
                "JOYSAFETER_EGRESS_POLICY_POLL_INTERVAL_MS",
                250,
            ),
            egress_xds_bind: env::var("JOYSAFETER_EGRESS_XDS_BIND")
                .ok()
                .filter(|value| !value.trim().is_empty()),
            egress_xds_mtls: env_bool("JOYSAFETER_EGRESS_XDS_MTLS", true),
            egress_xds_cert_file: env_str(
                "JOYSAFETER_EGRESS_XDS_CERT_FILE",
                "/var/run/joysafeter-egress/xds-server-tls/tls.crt",
            ),
            egress_xds_key_file: env_str(
                "JOYSAFETER_EGRESS_XDS_KEY_FILE",
                "/var/run/joysafeter-egress/xds-server-tls/tls.key",
            ),
            egress_xds_client_ca_file: env_str(
                "JOYSAFETER_EGRESS_XDS_CLIENT_CA_FILE",
                "/var/run/joysafeter-egress/xds-server-tls/ca.crt",
            ),
            egress_xds_client_dns_san: env_str(
                "JOYSAFETER_EGRESS_XDS_CLIENT_DNS_SAN",
                "joysafeter-egress-envoy.joysafeter-egress.svc.cluster.local",
            ),
            egress_xds_shadow_reconcile: env_bool(
                "JOYSAFETER_EGRESS_XDS_SHADOW_RECONCILE",
                false,
            ),
            egress_xds_reconcile_interval_ms: env_u64(
                "JOYSAFETER_EGRESS_XDS_RECONCILE_INTERVAL_MS",
                5_000,
            ),
            egress_xds_ack_timeout_ms: env_u64("JOYSAFETER_EGRESS_XDS_ACK_TIMEOUT_MS", 30_000),
            egress_xds_node_lease_ttl_ms: env_u64(
                "JOYSAFETER_EGRESS_XDS_NODE_LEASE_TTL_MS",
                30_000,
            ),
            egress_authz_bind: env::var("JOYSAFETER_EGRESS_AUTHZ_BIND")
                .ok()
                .filter(|value| !value.trim().is_empty()),
            egress_authz_mtls: env_bool("JOYSAFETER_EGRESS_AUTHZ_MTLS", true),
            egress_authz_cert_file: env_str(
                "JOYSAFETER_EGRESS_AUTHZ_CERT_FILE",
                "/var/run/joysafeter-egress/authz-server-tls/tls.crt",
            ),
            egress_authz_key_file: env_str(
                "JOYSAFETER_EGRESS_AUTHZ_KEY_FILE",
                "/var/run/joysafeter-egress/authz-server-tls/tls.key",
            ),
            egress_authz_client_ca_file: env_str(
                "JOYSAFETER_EGRESS_AUTHZ_CLIENT_CA_FILE",
                "/var/run/joysafeter-egress/authz-server-tls/ca.crt",
            ),
            egress_authz_client_dns_san: env_str(
                "JOYSAFETER_EGRESS_AUTHZ_CLIENT_DNS_SAN",
                "joysafeter-egress-envoy.joysafeter-egress.svc.cluster.local",
            ),
            k8s_egress_management_enabled: env_bool(
                "JOYSAFETER_K8S_EGRESS_MANAGEMENT_ENABLED",
                false,
            ),
            credential_resolution_bind: env::var("JOYSAFETER_CREDENTIAL_RESOLUTION_BIND")
                .ok()
                .filter(|v| !v.trim().is_empty()),
            credential_resolution_service_token: env::var(
                "JOYSAFETER_CREDENTIAL_RESOLUTION_SERVICE_TOKEN",
            )
            .ok()
            .filter(|v| !v.trim().is_empty()),

            image_builder_enabled: env_bool("JOYSAFETER_IMAGE_BUILDER_ENABLED", false),
            image_builder_base: env_str(
                "JOYSAFETER_IMAGE_BUILDER_BASE",
                "joysafeter-claudecode:latest",
            ),

            vault_encryption_key: env::var("JOYSAFETER_VAULT_ENCRYPTION_KEY").ok(),

            heartbeat_interval: env_u64("JOYSAFETER_HEARTBEAT_INTERVAL", 15),
            heartbeat_ttl: env_u64("JOYSAFETER_HEARTBEAT_TTL", 30),

            daytona_api_url: env_str("JOYSAFETER_DAYTONA_API_URL", ""),
            daytona_api_key: env_str("JOYSAFETER_DAYTONA_API_KEY", ""),
            daytona_target: env::var("JOYSAFETER_DAYTONA_TARGET").ok(),
            daytona_snapshot: env_str("JOYSAFETER_DAYTONA_SNAPSHOT", ""),

            e2b_api_url: env::var("JOYSAFETER_E2B_API_URL").ok(),
            e2b_api_key: env_str("JOYSAFETER_E2B_API_KEY", ""),
            e2b_template_id: env_str("JOYSAFETER_E2B_TEMPLATE_ID", ""),

            k8s_namespace: env_str("JOYSAFETER_K8S_NAMESPACE", "joysafeter-sandboxes"),
            k8s_orchestrator_url: env::var("JOYSAFETER_K8S_ORCHESTRATOR_URL")
                .ok()
                .filter(|v| !v.trim().is_empty()),

            database_url: build_database_url(),
            redis_url: env::var("REDIS_URL").ok(),
        }
    }

    /// gRPC server listen address.
    pub fn grpc_addr(&self) -> SocketAddr {
        format!("{}:{}", self.grpc_host, self.grpc_port)
            .parse()
            .expect("invalid gRPC listen address")
    }

    /// Select the Docker image for a given engine_kind (provider).
    /// Falls back to `sandbox_image` if no per-engine image is configured.
    pub fn image_for_provider(&self, engine_kind: &str) -> String {
        match engine_kind {
            "claude" if !self.image_claude.is_empty() => self.image_claude.clone(),
            "codex" if !self.image_codex.is_empty() => self.image_codex.clone(),
            // native needs its OWN image (the claudecode image's runner does not
            // register the native adapter). Do NOT fall back to image_claude here,
            // or native tasks land on a claudecode container that reports
            // "No adapter for provider: native".
            "native" if !self.image_native.is_empty() => self.image_native.clone(),
            _ => self.sandbox_image.clone(),
        }
    }
}

// ---------------------------------------------------------------------------
// Environment helpers
// ---------------------------------------------------------------------------

fn env_str(key: &str, default: &str) -> String {
    env::var(key).unwrap_or_else(|_| default.to_string())
}

fn env_bool(key: &str, default: bool) -> bool {
    env::var(key)
        .map(|v| matches!(v.to_lowercase().as_str(), "1" | "true" | "yes"))
        .unwrap_or(default)
}

fn env_u64(key: &str, default: u64) -> u64 {
    env::var(key)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

fn env_i64(key: &str, default: i64) -> i64 {
    env::var(key)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

fn env_u32(key: &str, default: u32) -> u32 {
    env::var(key)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

fn env_u16(key: &str, default: u16) -> u16 {
    env::var(key)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

fn env_usize(key: &str, default: usize) -> usize {
    env::var(key)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

fn env_list(key: &str) -> Vec<String> {
    env::var(key)
        .ok()
        .map(|v| parse_env_list(&v))
        .unwrap_or_default()
}

fn env_list_or_default(key: &str, defaults: &[&str]) -> Vec<String> {
    let configured = env_list(key);
    if configured.is_empty() {
        defaults.iter().map(|value| (*value).to_string()).collect()
    } else {
        configured
    }
}

fn parse_env_list(value: &str) -> Vec<String> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        return Vec::new();
    }

    // Try JSON array first: ["a","b"]
    if let Ok(items) = serde_json::from_str::<Vec<String>>(trimmed) {
        return items
            .into_iter()
            .map(|item| item.trim().to_string())
            .filter(|item| !item.is_empty())
            .collect();
    }

    // Fallback: comma-separated, strip brackets and quotes
    let stripped = trimmed.trim_start_matches('[').trim_end_matches(']');
    stripped
        .split(',')
        .map(|s| s.trim().trim_matches('"').trim_matches('\'').to_string())
        .filter(|s| !s.is_empty())
        .collect()
}

fn hostname() -> String {
    gethostname::gethostname().to_string_lossy().into_owned()
}

/// Build the Postgres connection URL from `POSTGRES_*` env vars.
fn build_database_url() -> String {
    if let Ok(url) = env::var("DATABASE_URL") {
        return url;
    }

    let host = env_str("POSTGRES_HOST", "localhost");
    let user = env_str("POSTGRES_USER", "postgres");
    let password = env_str("POSTGRES_PASSWORD", "postgres");
    let db = env_str("POSTGRES_DB", "joysafeter");
    let port = env_str("POSTGRES_PORT", "5432");

    format!("postgres://{user}:{password}@{host}:{port}/{db}")
}

#[cfg(test)]
mod tests {
    use super::parse_env_list;

    #[test]
    fn parses_json_array_lists() {
        assert_eq!(
            parse_env_list(r#"["joysafeter-claudecode:latest","joysafeter-codex:latest"]"#),
            vec!["joysafeter-claudecode:latest", "joysafeter-codex:latest"]
        );
    }

    #[test]
    fn parses_comma_separated_lists() {
        assert_eq!(
            parse_env_list("joysafeter-claudecode:latest, joysafeter-codex:latest"),
            vec!["joysafeter-claudecode:latest", "joysafeter-codex:latest"]
        );
    }

    #[test]
    fn ignores_empty_list_items() {
        assert_eq!(parse_env_list(r#"["", "codex"]"#), vec!["codex"]);
        assert_eq!(parse_env_list(" , codex, "), vec!["codex"]);
    }

    #[test]
    fn egress_xds_endpoint_has_defaults() {
        // Ensure the env is clean for a defaults check.
        std::env::remove_var("JOYSAFETER_EGRESS_XDS_HOST");
        std::env::remove_var("JOYSAFETER_EGRESS_XDS_PORT");
        let config = super::JoySafeterConfig::from_env();
        assert_eq!(config.egress_xds_host, "joysafeter-orchestrator");
        assert_eq!(config.egress_xds_port, 18000);
    }
}
