use std::net::SocketAddr;
use std::{env, path::Path};

/// JoySafeter kernel configuration.
///
/// Matches the Python `JoySafeterConfig` from `joysafeter_shared/config/settings.py`,
/// reading from `JOYSAFETER_*` environment variables.
#[derive(Debug, Clone)]
pub struct JoySafeterConfig {
    pub instance_id: String,
    pub redis_queue_prefix: String,

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
    pub sandbox_timezone: String,
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
    pub image_pi: String,

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
    /// Host directory containing the shared Unix socket used by restricted
    /// sandbox runners to connect to the orchestrator control-plane gRPC API.
    pub runner_control_socket_host_dir: String,
    /// Optional Docker volume name for the shared runner control socket. This
    /// is primarily for Docker Desktop/macOS where Unix sockets on host bind
    /// mounts cannot be connected to from Linux containers.
    pub runner_control_socket_volume: Option<String>,
    /// Container-side path mounted into restricted sandboxes for runner gRPC.
    pub runner_control_socket_container_path: String,

    // Scheduler
    pub scheduler_batch_size: usize,

    // Envoy network isolation
    pub envoy_enabled: bool,
    pub envoy_image: String,
    pub envoy_socket_volume: String,
    pub envoy_socket_host_dir: Option<String>,
    pub envoy_config_dir: String,
    pub envoy_network: String,
    pub envoy_grpc_host: String,
    pub envoy_grpc_port: u16,
    pub envoy_container_name: String,
    /// LDS transport: `"filesystem"` (default, `lds.json`) or `"grpc"` (Delta xDS).
    pub envoy_xds_mode: String,
    /// Write per-sandbox non-secret debug entry files under Envoy config dir.
    /// Disabled by default because gRPC xDS recovery derives state from DB and
    /// these files add one Docker exec/tar upload per policy push.
    pub envoy_write_debug_entries: bool,
    /// Mount only this sandbox's socket subdirectory via Docker volume subpath.
    /// Disable only if the target Docker Engine/API rejects volume subpaths.
    pub envoy_socket_subpath_mount: bool,
    /// Max time to wait for Envoy to materialize per-sandbox Unix sockets after
    /// listener config is accepted. xDS ACK only proves config acceptance; the
    /// runner cannot start until the UDS files actually exist on the bind mount.
    pub envoy_socket_ready_timeout_ms: u64,
    /// Health-check interval for the shared Envoy container. 0 disables checks.
    pub envoy_health_check_interval_sec: u64,
    /// Consecutive failed checks before restarting Envoy and recovering xDS.
    pub envoy_health_failure_threshold: u64,
    /// Hosts that LLM egress credential routes may target. This protects the
    /// Envoy-side key injection path from sending credentials to arbitrary
    /// user-controlled base URLs.
    pub llm_egress_allowed_hosts: Vec<String>,

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
    pub k8s_kubectl_path: String,
    pub k8s_orchestrator_url: Option<String>,

    // Leader Election (K8s Lease-based HA)
    pub leader_election_enabled: bool,
    pub leader_lease_name: String,
    pub leader_lease_duration_sec: u64,
    pub leader_renew_interval_sec: u64,
    pub leader_identity: String,

    // HA mode
    pub ha_mode: String,

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
            sandbox_timezone: env::var("JOYSAFETER_SANDBOX_TIMEZONE")
                .ok()
                .filter(|value| !value.trim().is_empty())
                .unwrap_or_else(|| env_str("JOYSAFETER_TIMEZONE", &env_str("TZ", "UTC"))),
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
            image_pi: env_str("JOYSAFETER_IMAGE_PI", ""),

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
            runner_control_socket_host_dir: env_str(
                "JOYSAFETER_RUNNER_CONTROL_SOCKET_HOST_DIR",
                "/tmp/joysafeter-runner-control",
            ),
            runner_control_socket_volume: env::var("JOYSAFETER_RUNNER_CONTROL_SOCKET_VOLUME")
                .ok()
                .filter(|v| !v.trim().is_empty()),
            runner_control_socket_container_path: env_str(
                "JOYSAFETER_RUNNER_CONTROL_SOCKET_CONTAINER_PATH",
                "/control/grpc.sock",
            ),

            scheduler_batch_size: env_usize("JOYSAFETER_SCHEDULER_BATCH_SIZE", 10),

            envoy_enabled: env_bool("JOYSAFETER_ENVOY_ENABLED", false),
            envoy_image: env_str("JOYSAFETER_ENVOY_IMAGE", "envoyproxy/envoy:v1.31-latest"),
            envoy_socket_volume: env_str("JOYSAFETER_ENVOY_SOCKET_VOLUME", "joysafeter-sockets"),
            envoy_socket_host_dir: env::var("JOYSAFETER_ENVOY_SOCKET_HOST_DIR")
                .ok()
                .filter(|v| !v.trim().is_empty()),
            envoy_config_dir: env_str(
                "JOYSAFETER_ENVOY_CONFIG_DIR",
                "/tmp/joysafeter-envoy-config",
            ),
            envoy_network: env_str("JOYSAFETER_ENVOY_NETWORK", "joysafeter-net"),
            envoy_grpc_host: env_str("JOYSAFETER_ENVOY_GRPC_HOST", "host.docker.internal"),
            envoy_grpc_port: env_u16("JOYSAFETER_ENVOY_GRPC_PORT", 9090),
            envoy_container_name: env_str("JOYSAFETER_ENVOY_CONTAINER_NAME", "joysafeter-envoy"),
            envoy_xds_mode: env_str("JOYSAFETER_ENVOY_XDS_MODE", "filesystem"),
            envoy_write_debug_entries: env_bool("JOYSAFETER_ENVOY_WRITE_DEBUG_ENTRIES", false),
            envoy_socket_subpath_mount: env_bool("JOYSAFETER_ENVOY_SOCKET_SUBPATH_MOUNT", true),
            envoy_socket_ready_timeout_ms: env_u64(
                "JOYSAFETER_ENVOY_SOCKET_READY_TIMEOUT_MS",
                30_000,
            ),
            envoy_health_check_interval_sec: env_u64(
                "JOYSAFETER_ENVOY_HEALTH_CHECK_INTERVAL_SEC",
                30,
            ),
            envoy_health_failure_threshold: env_u64("JOYSAFETER_ENVOY_HEALTH_FAILURE_THRESHOLD", 3),
            llm_egress_allowed_hosts: env_list("JOYSAFETER_LLM_EGRESS_ALLOWED_HOSTS"),

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
            k8s_kubectl_path: env_str("JOYSAFETER_K8S_KUBECTL_PATH", "kubectl"),
            k8s_orchestrator_url: env::var("JOYSAFETER_K8S_ORCHESTRATOR_URL")
                .ok()
                .filter(|v| !v.trim().is_empty()),

            leader_election_enabled: env_bool("JOYSAFETER_LEADER_ELECTION_ENABLED", false),
            leader_lease_name: env_str(
                "JOYSAFETER_LEADER_LEASE_NAME",
                "joysafeter-orchestrator-leader",
            ),
            leader_lease_duration_sec: env_u64("JOYSAFETER_LEADER_LEASE_DURATION_SEC", 10),
            leader_renew_interval_sec: env_u64("JOYSAFETER_LEADER_RENEW_INTERVAL_SEC", 3),
            leader_identity: env::var("POD_NAME")
                .or_else(|_| env::var("HOSTNAME"))
                .unwrap_or_else(|_| format!("orch-{}", uuid::Uuid::now_v7())),

            ha_mode: env_str("JOYSAFETER_HA_MODE", "standalone"),

            database_url: build_database_url(),
            redis_url: build_redis_url(),
        }
    }

    /// gRPC server listen address.
    pub fn grpc_addr(&self) -> SocketAddr {
        format!("{}:{}", self.grpc_host, self.grpc_port)
            .parse()
            .expect("invalid gRPC listen address")
    }

    pub fn validate(&self) -> anyhow::Result<()> {
        if let Some(control_volume) = self.runner_control_socket_volume.as_deref() {
            if control_volume == self.envoy_socket_volume {
                anyhow::bail!(
                    "JOYSAFETER_RUNNER_CONTROL_SOCKET_VOLUME and JOYSAFETER_ENVOY_SOCKET_VOLUME must be different; both are {:?}. Leave JOYSAFETER_RUNNER_CONTROL_SOCKET_VOLUME empty when using host-dir control sockets.",
                    control_volume
                );
            }
        }
        if let Some(envoy_socket_host_dir) = self.envoy_socket_host_dir.as_deref() {
            ensure_distinct_host_dirs(
                "JOYSAFETER_RUNNER_CONTROL_SOCKET_HOST_DIR",
                &self.runner_control_socket_host_dir,
                "JOYSAFETER_ENVOY_SOCKET_HOST_DIR",
                envoy_socket_host_dir,
            )?;
        }
        if !self.runner_control_socket_container_path.starts_with('/')
            || self.runner_control_socket_container_path.ends_with('/')
        {
            anyhow::bail!(
                "JOYSAFETER_RUNNER_CONTROL_SOCKET_CONTAINER_PATH must be an absolute Unix socket file path, got {:?}",
                self.runner_control_socket_container_path
            );
        }
        // HA mode validation
        if self.ha_mode == "multi" && self.leader_election_enabled {
            anyhow::bail!(
                "JOYSAFETER_HA_MODE=multi and JOYSAFETER_LEADER_ELECTION_ENABLED=true are mutually exclusive. \
                 Multi mode is leaderless; disable leader election or use ha_mode=leader."
            );
        }
        if self.ha_mode == "multi" && self.redis_url.is_none() {
            anyhow::bail!(
                "JOYSAFETER_HA_MODE=multi requires Redis. Set REDIS_URL or REDIS_HOST."
            );
        }
        Ok(())
    }

    /// Select the Docker image for a given engine_kind (provider).
    ///
    /// Every non-claude engine ships its OWN image whose runner registers only
    /// that engine's adapter. Silently falling back to the default sandbox image
    /// (claudecode) lands the task on a container that then fails at execution
    /// time with "No adapter for provider: <engine>" — a confusing runtime error
    /// for what is really a missing-config problem. So a known non-claude engine
    /// with an unconfigured image is a hard error here, surfaced at sandbox
    /// resolution with an actionable message. Only `claude` (and unknown kinds)
    /// fall back to `sandbox_image`, which is itself the claudecode image.
    pub fn image_for_provider(&self, engine_kind: &str) -> anyhow::Result<String> {
        let resolve = |image: &str, env_var: &str| -> anyhow::Result<String> {
            if image.is_empty() {
                anyhow::bail!(
                    "engine '{engine_kind}' has no image configured; set {env_var} \
                     (the {engine_kind} runner only registers its own adapter, so \
                     falling back to the default claudecode image would fail at \
                     task execution with \"No adapter for provider: {engine_kind}\")"
                );
            }
            Ok(image.to_string())
        };
        match engine_kind {
            "codex" => resolve(&self.image_codex, "JOYSAFETER_IMAGE_CODEX"),
            "native" => resolve(&self.image_native, "JOYSAFETER_IMAGE_NATIVE"),
            "pi" => resolve(&self.image_pi, "JOYSAFETER_IMAGE_PI"),
            "claude" if !self.image_claude.is_empty() => Ok(self.image_claude.clone()),
            _ => Ok(self.sandbox_image.clone()),
        }
    }
}

fn ensure_distinct_host_dirs(
    left_name: &str,
    left: &str,
    right_name: &str,
    right: &str,
) -> anyhow::Result<()> {
    let left_path = normalize_path(left);
    let right_path = normalize_path(right);
    if left_path == right_path {
        anyhow::bail!(
            "{left_name} and {right_name} must be different directories; both resolve to {}. The runner control directory should contain only grpc.sock and must not be shared with Envoy sandbox sockets.",
            left_path.display()
        );
    }
    if left_path.starts_with(&right_path) || right_path.starts_with(&left_path) {
        anyhow::bail!(
            "{left_name} ({}) and {right_name} ({}) must not be nested. Use separate host directories for runner control grpc.sock and Envoy sandbox sockets.",
            left_path.display(),
            right_path.display()
        );
    }
    Ok(())
}

fn normalize_path(value: &str) -> std::path::PathBuf {
    let path = Path::new(value);
    let mut normalized = std::path::PathBuf::new();
    for component in path.components() {
        match component {
            std::path::Component::CurDir => {}
            std::path::Component::ParentDir => {
                normalized.pop();
            }
            _ => normalized.push(component.as_os_str()),
        }
    }
    normalized
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
/// Falls back to `DATABASE_URL` if set directly.
/// Automatically URL-encodes user/password to handle special chars (@, #, !, etc.).
fn build_database_url() -> String {
    let database_url = env::var("DATABASE_URL").ok();
    let host = env::var("POSTGRES_HOST").ok();
    let port = env::var("POSTGRES_PORT").ok();
    let user = env::var("POSTGRES_USER").ok();
    let password = env::var("POSTGRES_PASSWORD").ok();
    let db = env::var("POSTGRES_DB").ok();

    build_database_url_from_values(
        database_url.as_deref(),
        host.as_deref(),
        port.as_deref(),
        user.as_deref(),
        password.as_deref(),
        db.as_deref(),
    )
}

fn build_database_url_from_values(
    database_url: Option<&str>,
    postgres_host: Option<&str>,
    postgres_port: Option<&str>,
    postgres_user: Option<&str>,
    postgres_password: Option<&str>,
    postgres_db: Option<&str>,
) -> String {
    let split_values = [
        postgres_host,
        postgres_port,
        postgres_user,
        postgres_password,
        postgres_db,
    ];
    let has_explicit_split_value = split_values
        .iter()
        .flatten()
        .any(|value| !value.trim().is_empty());

    if !has_explicit_split_value {
        if let Some(url) = database_url.map(str::trim).filter(|url| !url.is_empty()) {
            return url.to_string();
        }
    }

    fn value_or_default<'a>(value: Option<&'a str>, default: &'a str) -> &'a str {
        value
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .unwrap_or(default)
    }
    let host = value_or_default(postgres_host, "localhost");
    let port = value_or_default(postgres_port, "5432");
    let user = value_or_default(postgres_user, "postgres");
    let password = value_or_default(postgres_password, "postgres");
    let db = value_or_default(postgres_db, "joysafeter");

    // URL-encode user/password so special chars don't break the URL structure
    let safe_user = url_encode(user);
    let safe_password = url_encode(password);

    format!("postgres://{safe_user}:{safe_password}@{host}:{port}/{db}")
}

/// Percent-encode a string for use in a URL (user/password component).
fn url_encode(s: &str) -> String {
    s.chars()
        .map(|c| match c {
            'A'..='Z' | 'a'..='z' | '0'..='9' | '-' | '_' | '.' | '~' => c.to_string(),
            _ => format!("%{:02X}", c as u8),
        })
        .collect()
}

/// Build Redis URL from `REDIS_*` env vars with auto-encoding.
/// Falls back to `REDIS_URL` if set directly.
fn build_redis_url() -> Option<String> {
    // Priority 1: explicit REDIS_URL (user must encode themselves)
    if let Ok(url) = env::var("REDIS_URL") {
        if !url.trim().is_empty() {
            return Some(url);
        }
    }

    // Priority 2: build from REDIS_HOST + REDIS_PASSWORD + REDIS_PORT + REDIS_DB
    let host = env::var("REDIS_HOST")
        .ok()
        .filter(|v| !v.trim().is_empty())?;
    let port = env_str("REDIS_PORT", "6379");
    let password = env::var("REDIS_PASSWORD").unwrap_or_default();
    let db = env_str("REDIS_DB", "0");
    let scheme = env_str("REDIS_SCHEME", "redis"); // "redis" or "rediss" (TLS)

    if password.is_empty() {
        Some(format!("{scheme}://{host}:{port}/{db}"))
    } else {
        let safe_password = url_encode(&password);
        Some(format!("{scheme}://:{safe_password}@{host}:{port}/{db}"))
    }
}

#[cfg(test)]
mod tests {
    use super::build_database_url_from_values;
    use super::parse_env_list;
    use super::JoySafeterConfig;

    #[test]
    fn database_url_prefers_split_password_over_conflicting_url() {
        assert_eq!(
            build_database_url_from_values(
                Some("postgresql://postgres:stale@postgres:5432/joysafeter"),
                None,
                None,
                None,
                Some("current"),
                None,
            ),
            "postgres://postgres:current@localhost:5432/joysafeter"
        );
    }

    #[test]
    fn database_url_prefers_any_explicit_split_value() {
        assert_eq!(
            build_database_url_from_values(
                Some("postgresql://postgres:stale@postgres:5432/joysafeter"),
                Some("postgres"),
                None,
                None,
                None,
                None,
            ),
            "postgres://postgres:postgres@postgres:5432/joysafeter"
        );
    }

    #[test]
    fn database_url_falls_back_to_non_empty_explicit_url() {
        assert_eq!(
            build_database_url_from_values(
                Some(" postgresql://external:secret@db.example.com:5432/app "),
                None,
                None,
                None,
                None,
                None,
            ),
            "postgresql://external:secret@db.example.com:5432/app"
        );
    }

    #[test]
    fn database_url_treats_empty_explicit_url_as_unset() {
        assert_eq!(
            build_database_url_from_values(Some("  "), None, None, None, None, None),
            "postgres://postgres:postgres@localhost:5432/joysafeter"
        );
    }

    #[test]
    fn database_url_percent_encodes_split_credentials() {
        assert_eq!(
            build_database_url_from_values(
                None,
                Some("postgres"),
                Some("5433"),
                Some("user@example.com"),
                Some("p@ss word"),
                Some("app"),
            ),
            "postgres://user%40example.com:p%40ss%20word@postgres:5433/app"
        );
    }

    #[test]
    fn image_for_provider_pi_uses_image_pi() {
        let mut cfg = JoySafeterConfig::from_env();
        cfg.image_pi = "joysafeter-pi:latest".to_string();
        assert_eq!(
            cfg.image_for_provider("pi").unwrap(),
            "joysafeter-pi:latest"
        );
    }

    #[test]
    fn image_for_provider_errors_when_engine_image_unset() {
        let mut cfg = JoySafeterConfig::from_env();
        cfg.sandbox_image = "joysafeter-claudecode:latest".to_string();
        // A known non-claude engine with no configured image must fail loudly
        // instead of silently returning the default claudecode image.
        for engine in ["pi", "codex", "native"] {
            cfg.image_pi = String::new();
            cfg.image_codex = String::new();
            cfg.image_native = String::new();
            let err = cfg
                .image_for_provider(engine)
                .expect_err("unset engine image should be an error");
            let msg = err.to_string();
            assert!(
                msg.contains(engine),
                "message should name the engine: {msg}"
            );
            assert_ne!(msg, "joysafeter-claudecode:latest");
        }
    }

    #[test]
    fn image_for_provider_claude_falls_back_to_sandbox_image() {
        let mut cfg = JoySafeterConfig::from_env();
        cfg.image_claude = String::new();
        cfg.sandbox_image = "joysafeter-claudecode:latest".to_string();
        // claude legitimately falls back: the default sandbox image IS claudecode.
        assert_eq!(
            cfg.image_for_provider("claude").unwrap(),
            "joysafeter-claudecode:latest"
        );
    }

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
}
