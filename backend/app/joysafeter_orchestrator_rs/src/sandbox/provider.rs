use std::collections::HashMap;

use async_trait::async_trait;
use uuid::Uuid;

use crate::sandbox::file_injection::FileToInject;

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

/// The SandboxProvider trait — all sandbox backends must implement this.
///
/// Mirrors the Python `SandboxProvider` ABC.
#[async_trait]
pub trait SandboxProvider: Send + Sync + 'static {
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

    /// Inject already-loaded session files into a running sandbox.
    async fn inject_files(
        &self,
        _external_id: &str,
        _files: &[FileToInject],
    ) -> anyhow::Result<()> {
        Ok(())
    }

    /// Provider name (e.g., "docker", "daytona", "e2b").
    fn provider_name(&self) -> &'static str;
}
