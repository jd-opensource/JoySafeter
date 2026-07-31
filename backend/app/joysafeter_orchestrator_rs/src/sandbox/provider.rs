use std::collections::HashMap;

use async_trait::async_trait;
use sqlx::PgPool;
use uuid::Uuid;

use crate::egress::policy::SandboxCredentials;
use crate::sandbox::file_injection::{FileToInject, InjectionStrategy};
use crate::sandbox::mounts::SandboxMount;

/// Status of a sandbox container.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SandboxStatus {
    Running,
    Stopped,
    NotFound,
    Unknown(String),
}

/// What egress isolation a provider can actually enforce for a sandbox.
///
/// Only `Mediated` is a credential boundary; it is the sole profile permitted to
/// run secret-backed or limited-networking sandboxes.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum IsolationProfile {
    /// No isolation — sandbox has full outbound access.
    Open,
    /// The platform (E2B/Daytona) isolates the sandbox internally, but JoySafeter
    /// does not mediate credentialed egress. Not a credential boundary.
    PlatformManaged,
    /// JoySafeter mediates credentialed egress (allowlist + credential injection)
    /// through the given boundary.
    Mediated { boundary: EgressBoundary },
}

/// Where and how a sandbox reaches its mediated egress boundary.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum EgressBoundary {
    /// Docker: per-sandbox Envoy listeners over a Unix socket volume.
    EnvoySocket,
    /// K8s: an in-cluster egress gateway HTTP(S) service.
    Gateway,
}

impl IsolationProfile {
    /// True when this profile mediates credentialed egress — the replacement for
    /// the former `has_egress_management` boolean.
    pub fn manages_egress(&self) -> bool {
        matches!(self, IsolationProfile::Mediated { .. })
    }
}

/// Capabilities declared by a provider, used by the framework to select
/// strategies (e.g., file injection, networking) without provider-specific
/// branching.
#[derive(Debug, Clone)]
pub struct ProviderCapabilities {
    /// Provider supports host filesystem bind-mounts (Docker volumes).
    /// When true, the HostMount file injection strategy is available.
    pub has_host_mount: bool,
    /// Egress isolation this provider can enforce.
    pub isolation: IsolationProfile,
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
        _sandbox_token: Option<&str>,
        _networking: Option<&serde_json::Value>,
        _credentials: SandboxCredentials,
    ) -> anyhow::Result<()> {
        Ok(())
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
            isolation: IsolationProfile::Open,
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

#[cfg(test)]
mod provider_conformance_tests {
    use super::*;
    use crate::config::JoySafeterConfig;
    use crate::sandbox::daytona::DaytonaProvider;
    use crate::sandbox::e2b::E2bProvider;
    use crate::sandbox::k8s::K8sProvider;

    fn assert_no_credential_egress_boundary(provider: &impl SandboxProvider) {
        let capabilities = provider.capabilities();

        assert!(
            !capabilities.isolation.manages_egress(),
            "{} must not claim egress management until it can enforce allowlist + credential injection",
            provider.provider_name()
        );
    }

    #[test]
    fn provider_conformance_k8s_does_not_claim_egress_management_until_gateway_exists() {
        let mut config = JoySafeterConfig::from_env();
        config.k8s_namespace = "joysafeter-sandboxes".to_string();
        config.k8s_kubectl_path = "kubectl".to_string();
        let provider = K8sProvider::new(&config);

        assert_no_credential_egress_boundary(&provider);
        assert_eq!(provider.capabilities().isolation, IsolationProfile::Open);
    }

    #[test]
    fn provider_conformance_remote_platforms_do_not_claim_credential_egress_yet() {
        let daytona = DaytonaProvider::new("https://daytona.example", "test-key", "", "");
        let e2b = E2bProvider::new("https://e2b.example", "test-key", "template");

        assert_no_credential_egress_boundary(&daytona);
        assert_no_credential_egress_boundary(&e2b);
        assert_eq!(
            daytona.capabilities().isolation,
            IsolationProfile::PlatformManaged
        );
        assert_eq!(
            e2b.capabilities().isolation,
            IsolationProfile::PlatformManaged
        );
    }
}
