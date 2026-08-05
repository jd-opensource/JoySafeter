use std::collections::HashMap;

use async_trait::async_trait;
use sqlx::PgPool;
use uuid::Uuid;

use crate::sandbox::file_injection::{FileToInject, InjectionStrategy};
use crate::sandbox::lds_backend::SandboxCredentials;
use crate::sandbox::mounts::SandboxMount;

/// Status of a sandbox container.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SandboxStatus {
    Running,
    Stopped,
    NotFound,
    Unknown(String),
}

/// Network isolation level provided by this sandbox backend.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum NetworkIsolation {
    /// No network isolation — sandbox has full outbound access.
    None,
    /// Platform-managed isolation (E2B/Daytona handle it internally).
    Platform,
    /// Envoy sidecar proxy with per-sandbox listeners (Docker provider).
    Envoy,
}

/// Capabilities declared by a provider, used by the framework to select
/// strategies (e.g., file injection, networking) without provider-specific
/// branching.
#[derive(Debug, Clone)]
pub struct ProviderCapabilities {
    /// Provider supports host filesystem bind-mounts (Docker volumes).
    /// When true, the HostMount file injection strategy is available.
    pub has_host_mount: bool,
    /// Provider manages egress networking (allowlist + credential injection).
    pub has_egress_management: bool,
    /// Network isolation mechanism.
    pub network_isolation: NetworkIsolation,
}

/// Configuration for creating a sandbox container.
#[derive(Debug, Clone)]
pub struct SandboxCreateConfig {
    pub sandbox_id: Uuid,
    pub image: String,
    pub env: HashMap<String, String>,
    pub labels: HashMap<String, String>,
    pub cpu_limit: Option<f64>,
    pub memory_limit_mb: Option<u64>,
    pub network: Option<String>,
    /// Whether the provider should start the sandbox immediately after
    /// creating it. Docker/Envoy restricted networking sets this to false so
    /// the per-sandbox sockets can be created before the runner process starts.
    pub start_immediately: bool,
    pub workspace_path: Option<String>,
    /// Memory store mounts: (host_path, container_mount_path).
    /// Each entry maps a host directory to a container path like `/mnt/memory/<mount_name>`.
    pub memory_mounts: Vec<(String, String)>,
    /// Platform-authorized external filesystem mounts. Credentials and backing
    /// host/PVC details are resolved outside the sandbox from deployment config.
    pub mounts: Vec<SandboxMount>,
}

/// Active sandbox known by a provider.
#[derive(Debug, Clone)]
pub struct ProviderSandboxInfo {
    pub id: String,
    pub name: String,
    pub status: String,
    pub image: String,
    pub labels: HashMap<String, String>,
}

/// The SandboxProvider trait — the complete execution-plane abstraction.
///
/// Covers the full sandbox lifecycle: container management, networking/egress,
/// file injection, and runtime hooks. Each provider (Docker, Daytona, E2B, K8s)
/// implements its own strategy internally; the orchestrator framework never
/// contains provider-specific logic.
#[async_trait]
pub trait SandboxProvider: Send + Sync + 'static {
    // =====================================================================
    // Lifecycle (existing)
    // =====================================================================

    /// Create and start a new sandbox container.
    /// Returns the external container ID.
    async fn create(&self, config: &SandboxCreateConfig) -> anyhow::Result<String>;

    /// Start a stopped sandbox.
    async fn start(&self, external_id: &str) -> anyhow::Result<()>;

    /// Stop a running sandbox.
    async fn stop(&self, external_id: &str) -> anyhow::Result<()>;

    /// Destroy (remove) a sandbox completely.
    async fn destroy(&self, external_id: &str) -> anyhow::Result<()>;

    /// Get the current status of a sandbox.
    async fn status(&self, external_id: &str) -> anyhow::Result<SandboxStatus>;

    /// Execute a command inside the sandbox.
    async fn exec(&self, external_id: &str, cmd: &[&str]) -> anyhow::Result<String>;

    /// List active provider sandboxes for orphan cleanup.
    async fn list_active(&self) -> anyhow::Result<Vec<ProviderSandboxInfo>> {
        Ok(vec![])
    }

    /// Return provider-specific provisioning progress when supported.
    async fn provisioning_status(
        &self,
        _external_id: &str,
    ) -> anyhow::Result<Option<serde_json::Value>> {
        Ok(None)
    }

    /// Provider name (e.g., "docker", "daytona", "e2b").
    fn provider_name(&self) -> &'static str;

    // =====================================================================
    // Startup / Shutdown hooks
    // =====================================================================

    /// Called once when the orchestrator starts, after DB pool is ready.
    ///
    /// Docker: initializes Envoy container, writes bootstrap config, recovers
    /// LDS state from DB, initializes ImageBuilder.
    /// Daytona/E2B: no-op or platform health check.
    async fn on_startup(&self, _pool: &PgPool) -> anyhow::Result<()> {
        Ok(())
    }

    /// Called on graceful orchestrator shutdown.
    async fn on_shutdown(&self) -> anyhow::Result<()> {
        Ok(())
    }

    // =====================================================================
    // Networking / Egress
    // =====================================================================

    /// Configure sandbox egress networking (allowlist + credential injection).
    ///
    /// Docker: calls EnvoyManager.setup_for_sandbox() to create per-sandbox
    /// listeners with credential-injecting routes.
    /// Daytona/E2B: platform-managed or no-op.
    async fn setup_networking(
        &self,
        _sandbox_id: Uuid,
        _sandbox_external_id: &str,
        _networking: Option<&serde_json::Value>,
        _credentials: SandboxCredentials,
    ) -> anyhow::Result<()> {
        Ok(())
    }

    /// Refresh an existing sandbox's egress networking policy.
    ///
    /// Docker/Envoy can hot-replace listeners and clusters for a sandbox. Other
    /// providers may keep the default setup implementation if their networking
    /// API is idempotent, or override this with a cheaper patch call.
    async fn refresh_networking(
        &self,
        sandbox_id: Uuid,
        sandbox_external_id: &str,
        networking: Option<&serde_json::Value>,
        credentials: SandboxCredentials,
    ) -> anyhow::Result<()> {
        self.setup_networking(sandbox_id, sandbox_external_id, networking, credentials)
            .await
    }

    /// Tear down sandbox networking configuration.
    ///
    /// Docker: calls EnvoyManager.teardown_for_sandbox() to remove listeners.
    async fn teardown_networking(&self, _sandbox_id: Uuid) -> anyhow::Result<()> {
        Ok(())
    }

    // =====================================================================
    // Runtime
    // =====================================================================

    /// Return the URL that a sandbox runner should use to connect back to
    /// the orchestrator's gRPC server.
    ///
    /// Docker: `http://host.docker.internal:{grpc_port}`
    /// Daytona/E2B: the configured `JOYSAFETER_GRPC_PUBLIC_URL` (must be
    /// a publicly routable address).
    fn orchestrator_url(&self, grpc_port: u16) -> String {
        format!("http://host.docker.internal:{grpc_port}")
    }

    /// Declare provider capabilities so the framework can select strategies
    /// (file injection, networking) without provider-specific branching.
    fn capabilities(&self) -> ProviderCapabilities {
        ProviderCapabilities {
            has_host_mount: false,
            has_egress_management: false,
            network_isolation: NetworkIsolation::None,
        }
    }

    // =====================================================================
    // File injection
    // =====================================================================

    /// Inject already-loaded session files into a running sandbox.
    ///
    /// Docker: uses `docker cp` (bollard upload_to_container).
    /// Daytona: uses Daytona Files API.
    /// E2B: uses E2B Files API.
    async fn inject_files(&self, _external_id: &str, files: &[FileToInject]) -> anyhow::Result<()> {
        if !files.is_empty() {
            anyhow::bail!(
                "sandbox provider '{}' does not implement session file injection",
                self.provider_name()
            );
        }
        Ok(())
    }

    /// Return the file injection strategies this provider supports,
    /// in priority order.
    ///
    /// Docker: `[HostMount, ProviderFallback]`
    /// Daytona/E2B: `[ProviderFallback]`
    fn supported_injection_strategies(&self) -> Vec<InjectionStrategy> {
        vec![InjectionStrategy::ProviderFallback]
    }
}
