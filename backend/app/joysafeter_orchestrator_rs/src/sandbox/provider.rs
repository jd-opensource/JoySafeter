use std::collections::HashMap;

use crate::ids::SandboxId;
use crate::sandbox::file_injection::{FileToInject, InjectionStrategy};
use crate::sandbox::mounts::SandboxMount;
use async_trait::async_trait;

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
    /// Whether `start()` can resume the same runtime after `stop()`.
    pub stop_preserves_state: bool,
}

#[derive(Clone)]
pub struct SandboxRuntimeCredentials {
    runner_session_token: String,
    egress_proxy_token: String,
}

impl SandboxRuntimeCredentials {
    pub(crate) fn new(runner_session_token: String, egress_proxy_token: String) -> Self {
        Self {
            runner_session_token,
            egress_proxy_token,
        }
    }

    #[cfg(test)]
    pub(crate) fn runner_session_token(&self) -> &str {
        &self.runner_session_token
    }

    #[cfg(test)]
    pub(crate) fn egress_proxy_token(&self) -> &str {
        &self.egress_proxy_token
    }

    fn apply_to_environment(&self, env: &mut HashMap<String, String>) {
        env.insert(
            "JOYSAFETER_RUNNER_TOKEN".to_string(),
            self.runner_session_token.clone(),
        );
        env.insert(
            "JOYSAFETER_EGRESS_PROXY_TOKEN".to_string(),
            self.egress_proxy_token.clone(),
        );
    }
}

impl std::fmt::Debug for SandboxRuntimeCredentials {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("SandboxRuntimeCredentials")
            .field("runner_session_token", &"<redacted>")
            .field("egress_proxy_token", &"<redacted>")
            .finish()
    }
}

/// Configuration for creating a sandbox container.
#[derive(Clone)]
pub struct SandboxCreateConfig {
    pub sandbox_id: SandboxId,
    pub image: String,
    pub env: HashMap<String, String>,
    pub(crate) runtime_credentials: SandboxRuntimeCredentials,
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

impl SandboxCreateConfig {
    pub(crate) fn provider_environment(&self) -> HashMap<String, String> {
        let mut env = self.env.clone();
        self.runtime_credentials.apply_to_environment(&mut env);
        env
    }
}

impl std::fmt::Debug for SandboxCreateConfig {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("SandboxCreateConfig")
            .field("sandbox_id", &self.sandbox_id)
            .field("image", &self.image)
            .field(
                "env",
                &format_args!("{} entries <redacted>", self.env.len()),
            )
            .field("runtime_credentials", &self.runtime_credentials)
            .field("labels", &self.labels)
            .field("cpu_limit", &self.cpu_limit)
            .field("memory_limit_mb", &self.memory_limit_mb)
            .field("network", &self.network)
            .field("start_immediately", &self.start_immediately)
            .field("workspace_path", &self.workspace_path)
            .field("memory_mounts", &self.memory_mounts)
            .field("mounts", &self.mounts)
            .finish()
    }
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

    /// Update sandbox metadata labels when a provider supports live metadata patches.
    async fn patch_labels(
        &self,
        _external_id: &str,
        _labels: &HashMap<String, String>,
    ) -> anyhow::Result<()> {
        Ok(())
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
            stop_preserves_state: false,
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
mod tests {
    use super::{SandboxCreateConfig, SandboxRuntimeCredentials};
    use crate::ids::SandboxId;

    #[test]
    fn sandbox_create_debug_redacts_environment_and_runtime_credentials() {
        let config = SandboxCreateConfig {
            sandbox_id: SandboxId::new(),
            image: "runtime:test".to_string(),
            env: [("MODEL_API_KEY".to_string(), "model-secret".to_string())]
                .into_iter()
                .collect(),
            runtime_credentials: SandboxRuntimeCredentials::new(
                "runner-secret".to_string(),
                "egress-secret".to_string(),
            ),
            labels: Default::default(),
            cpu_limit: None,
            memory_limit_mb: None,
            network: None,
            start_immediately: true,
            workspace_path: None,
            memory_mounts: vec![],
            mounts: vec![],
        };

        let rendered = format!("{config:?}");
        for secret in ["model-secret", "runner-secret", "egress-secret"] {
            assert!(!rendered.contains(secret));
        }
        assert!(rendered.contains("<redacted>"));
    }
}
