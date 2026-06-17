use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::time::Duration;
use thiserror::Error;

use crate::environment::Networking;

#[derive(Debug, Error)]
pub enum SandboxError {
    #[error("failed to create sandbox: {0}")]
    CreateFailed(String),
    #[error("sandbox not found: {0}")]
    NotFound(String),
    #[error("failed to destroy sandbox: {0}")]
    DestroyFailed(String),
    #[error("failed to stop sandbox: {0}")]
    StopFailed(String),
    #[error("failed to start sandbox: {0}")]
    StartFailed(String),
    #[error("provider error: {0}")]
    Provider(String),
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SandboxStatus {
    Creating,
    Provisioning,
    Running,
    Idle,
    Stopping,
    Stopped,
    Error,
    Destroyed,
    Pooled,
}

impl std::fmt::Display for SandboxStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Creating => write!(f, "creating"),
            Self::Provisioning => write!(f, "provisioning"),
            Self::Running => write!(f, "running"),
            Self::Idle => write!(f, "idle"),
            Self::Stopping => write!(f, "stopping"),
            Self::Stopped => write!(f, "stopped"),
            Self::Error => write!(f, "error"),
            Self::Destroyed => write!(f, "destroyed"),
            Self::Pooled => write!(f, "pooled"),
        }
    }
}

impl SandboxStatus {
    pub fn from_str_lossy(s: &str) -> Self {
        match s {
            "creating" => Self::Creating,
            "provisioning" => Self::Provisioning,
            "running" => Self::Running,
            "idle" => Self::Idle,
            "stopping" => Self::Stopping,
            "stopped" => Self::Stopped,
            "error" => Self::Error,
            "destroyed" => Self::Destroyed,
            "pooled" => Self::Pooled,
            _ => Self::Stopped,
        }
    }
}

#[derive(Debug, Clone)]
pub struct SandboxInstance {
    pub id: String,
    pub provider: String,
    pub status: SandboxStatus,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SandboxProvisionStatus {
    pub stage: String,
    pub progress: u8,
    pub message: String,
    pub complete: bool,
    pub error: bool,
    pub error_message: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MemoryMount {
    pub store_id: uuid::Uuid,
    pub mount_name: String,
    pub host_path: String,
    pub access: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SandboxConfig {
    pub image: String,
    pub env: HashMap<String, String>,
    pub cpu: Option<f32>,
    pub memory_mb: Option<u32>,
    pub disk_mb: Option<u32>,
    pub timeout: Duration,
    pub workspace_host_path: Option<String>,
    pub networking: Networking,
    #[serde(default)]
    pub memory_mounts: Vec<MemoryMount>,
}

#[async_trait]
pub trait SandboxProvider: Send + Sync {
    async fn create(&self, config: SandboxConfig) -> Result<SandboxInstance, SandboxError>;
    async fn stop(&self, id: &str) -> Result<(), SandboxError>;
    async fn start(&self, id: &str) -> Result<(), SandboxError>;
    async fn destroy(&self, id: &str) -> Result<(), SandboxError>;
    async fn status(&self, id: &str) -> Result<SandboxStatus, SandboxError>;

    async fn provisioning_status(
        &self,
        _id: &str,
    ) -> Result<Option<SandboxProvisionStatus>, SandboxError> {
        Ok(None)
    }

    async fn list_active(&self) -> Result<Vec<SandboxInstance>, SandboxError>;
    fn provider_name(&self) -> &str;

    async fn setup_networking(
        &self,
        _sandbox_id: uuid::Uuid,
        networking: &Networking,
    ) -> Result<(), SandboxError> {
        if networking.net_type == "limited" {
            return Err(SandboxError::Provider(format!(
                "Provider '{}' does not support limited networking",
                self.provider_name()
            )));
        }
        Ok(())
    }

    async fn teardown_networking(&self, _sandbox_id: uuid::Uuid) -> Result<(), SandboxError> {
        Ok(())
    }
}
