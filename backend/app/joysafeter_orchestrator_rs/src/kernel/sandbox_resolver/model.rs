use std::collections::HashMap;

use sha2::{Digest, Sha256};

use crate::ids::{ProjectId, SandboxId, SessionId};
use crate::kernel::network_policy::envoy_model::SandboxCredentials;
use crate::sandbox::mounts::{SandboxMount, SandboxMountFingerprint};

#[derive(Debug, Clone)]
pub(crate) struct ExpectedFingerprint {
    pub(crate) image: String,
    pub(crate) engine_kind: String,
    pub(crate) networking: Option<serde_json::Value>,
    pub(crate) env: HashMap<String, String>,
    pub(crate) mounts: Vec<SandboxMountFingerprint>,
    pub(crate) egress_policy_hash: String,
}

#[derive(Debug, Clone)]
pub(crate) struct ResolveContext {
    pub(crate) session_id: Option<SessionId>,
    pub(crate) project_id: Option<ProjectId>,
    pub(crate) runtime_config_generation: i64,
    pub(crate) network: Option<String>,
    pub(crate) expected: ExpectedFingerprint,
    /// Memory store bind mounts: (host_path, container_mount_path).
    pub(crate) memory_mounts: Vec<(String, String)>,
    /// Platform-resolved sandbox mounts.
    pub(crate) mounts: Vec<SandboxMount>,
    /// Secret-bearing egress routes resolved for this task. These remain
    /// process-local and are never serialized into PostgreSQL or Redis.
    pub(crate) credentials: SandboxCredentials,
    /// Provider-advertised lifetime for task-scoped identity credentials.
    pub(crate) identity_refresh_after_seconds: Option<u64>,
}

impl ResolveContext {
    pub(crate) fn is_limited_networking(&self) -> bool {
        self.network.as_deref() == Some("none")
    }

    pub(crate) fn resolved(&self, sandbox_id: SandboxId, external_id: String) -> ResolvedSandbox {
        ResolvedSandbox {
            sandbox_id,
            external_id,
            runtime_config_generation: self.runtime_config_generation,
            identity_refresh_after_seconds: self.identity_refresh_after_seconds,
        }
    }

    pub(crate) fn has_task_identity(&self) -> bool {
        self.credentials.routes.iter().any(|route| {
            route.id.starts_with("external-identity:") && !route.inject_headers.is_empty()
        })
    }
}

#[derive(Debug, Clone)]
pub struct ResolvedSandbox {
    pub sandbox_id: SandboxId,
    pub external_id: String,
    pub runtime_config_generation: i64,
    pub identity_refresh_after_seconds: Option<u64>,
}

impl ExpectedFingerprint {
    pub(crate) fn to_json(&self) -> serde_json::Value {
        let env_hashes = self
            .env
            .iter()
            .map(|(key, value)| {
                let mut hasher = Sha256::new();
                hasher.update(value.as_bytes());
                (
                    key.clone(),
                    serde_json::Value::String(hex::encode(hasher.finalize())),
                )
            })
            .collect::<serde_json::Map<_, _>>();
        serde_json::json!({
            "image": self.image,
            "engine_kind": self.engine_kind,
            "networking": self.networking.clone().unwrap_or_else(|| serde_json::json!({})),
            "env": env_hashes,
            "mounts": self.mounts,
            "egress_policy_hash": self.egress_policy_hash,
        })
    }
}
