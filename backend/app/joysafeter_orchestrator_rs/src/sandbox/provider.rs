use std::collections::HashMap;

use async_trait::async_trait;
use sqlx::PgPool;
use uuid::Uuid;

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

    #[test]
    fn provider_conformance_k8s_requires_durable_authority_for_egress_management() {
        let mut config = JoySafeterConfig::from_env();
        config.k8s_namespace = "joysafeter-sandboxes".to_string();

        // Without durable authority + explicit enablement, no enforcer is built
        // — the resolver then fails closed for secret-backed sandboxes.
        assert!(
            crate::egress::enforcer::build_enforcer(&config, "k8s", None)
                .expect("build_enforcer")
                .is_none()
        );
    }

    #[test]
    fn provider_conformance_remote_platforms_do_not_claim_credential_egress_yet() {
        let config = JoySafeterConfig::from_env();

        // Remote platforms never get an enforcer → fail-closed for secrets.
        assert!(
            crate::egress::enforcer::build_enforcer(&config, "daytona", None)
                .expect("build_enforcer")
                .is_none()
        );
        assert!(
            crate::egress::enforcer::build_enforcer(&config, "e2b", None)
                .expect("build_enforcer")
                .is_none()
        );
    }
}
