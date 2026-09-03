//! Versioned transport types shared by Agent Gateway clients and servers.
//!
//! The contract deliberately contains no database or Envoy types. Policy
//! publication carries sensitive credential material over the authenticated
//! management channel for direct xDS injection.

use serde::{Deserialize, Serialize};

pub const MANAGEMENT_API_VERSION: &str = "v1";
pub const MANAGEMENT_AUTH_HEADER: &str = "authorization";

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct PolicyGeneration {
    pub policy_hash: String,
    pub policy_version: i64,
}

#[derive(Clone, Serialize, Deserialize)]
pub struct ApplySandboxPolicyRequest {
    pub generation: PolicyGeneration,
    #[serde(default)]
    pub allowlist_hosts: Vec<String>,
    #[serde(default)]
    pub credential_routes: Vec<CredentialRoute>,
    /// Per-sandbox credential that authenticates access to its local Envoy
    /// listener. This is unrelated to provider BotToken material.
    #[serde(default)]
    pub proxy_auth_token: Option<String>,
}

/// Conditional policy deletion. The generation fences delayed cleanup from
/// deleting a newer policy installed for the same sandbox runtime.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct RemoveSandboxPolicyRequest {
    pub generation: PolicyGeneration,
}

impl std::fmt::Debug for ApplySandboxPolicyRequest {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("ApplySandboxPolicyRequest")
            .field("generation", &self.generation)
            .field("allowlist_hosts", &self.allowlist_hosts)
            .field("credential_routes", &self.credential_routes)
            .field(
                "proxy_auth_token",
                &self.proxy_auth_token.as_ref().map(|_| "<redacted>"),
            )
            .finish()
    }
}

#[derive(Clone, Serialize, Deserialize)]
pub struct CredentialRoute {
    pub id: String,
    pub kind: EgressKind,
    pub exposure: EgressExposure,
    pub match_host: String,
    pub path_mapping: PathMapping,
    #[serde(default)]
    pub retry_mode: RetryMode,
    pub upstream_host: String,
    pub upstream_port: u16,
    pub upstream_tls: bool,
    #[serde(default)]
    pub vetted_addresses: Vec<String>,
    /// Resolved credential material for direct xDS injection. Values must never
    /// be included in logs or error messages.
    #[serde(default)]
    pub inject_headers: Vec<ResolvedHeader>,
    #[serde(default)]
    pub remove_headers: Vec<String>,
}

impl std::fmt::Debug for CredentialRoute {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("CredentialRoute")
            .field("id", &self.id)
            .field("kind", &self.kind)
            .field("exposure", &self.exposure)
            .field("match_host", &self.match_host)
            .field("path_mapping", &self.path_mapping)
            .field("retry_mode", &self.retry_mode)
            .field("upstream_host", &self.upstream_host)
            .field("upstream_port", &self.upstream_port)
            .field("upstream_tls", &self.upstream_tls)
            .field("vetted_addresses", &self.vetted_addresses)
            .field(
                "inject_headers",
                &self
                    .inject_headers
                    .iter()
                    .map(|header| &header.name)
                    .collect::<Vec<_>>(),
            )
            .field("inject_header_values", &"<redacted>")
            .field("remove_headers", &self.remove_headers)
            .finish()
    }
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EgressKind {
    Llm,
    Mcp,
    Git,
    External,
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EgressExposure {
    Placeholder,
    Transparent,
}

#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RetryMode {
    #[default]
    Disabled,
    SafeIdempotent,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum PathMapping {
    PassthroughAny,
    PassthroughExact {
        path: String,
    },
    PassthroughPrefix {
        path: String,
    },
    RewriteExact {
        exposed_path: String,
        upstream_path: String,
    },
    RewritePrefix {
        exposed_prefix: String,
        upstream_prefix: String,
    },
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct AssignSandboxPlacementRequest {
    pub node_id: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ReconcilePlacementsRequest {
    pub assignments: Vec<SandboxPlacement>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PruneSandboxPoliciesRequest {
    pub live_sandbox_ids: Vec<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PruneSandboxPoliciesResponse {
    pub removed_sandbox_ids: Vec<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SandboxPlacement {
    pub sandbox_id: String,
    pub node_id: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PolicyAcceptedResponse {
    pub sandbox_id: String,
    pub generation: PolicyGeneration,
    pub status: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct GatewayStatusResponse {
    pub instance_id: String,
    pub boot_id: String,
    pub authority_epoch: u64,
    pub authority_phase: String,
    pub generations: Vec<AppliedSandboxGeneration>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct AppliedSandboxGeneration {
    pub sandbox_id: String,
    pub generation: PolicyGeneration,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CompleteRecoveryRequest {
    pub boot_id: String,
    pub authority_epoch: u64,
    pub generations: Vec<AppliedSandboxGeneration>,
}

#[derive(Clone, Serialize, Deserialize)]
pub struct ResolvedHeader {
    pub name: String,
    pub value: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ErrorResponse {
    pub code: String,
    pub message: String,
}
