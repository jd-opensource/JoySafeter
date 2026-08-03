//! The sandbox egress data plane a sandbox runs on.
//!
//! The IDENTITY binding — setting a credential env var / header to the
//! per-sandbox `runner_token` so Envoy `ext_authz` (`kernel/ext_authz.rs::
//! identity_header_matches`) accepts the request before it strips the
//! placeholder and injects the real platform credential — is IDENTICAL on both
//! planes and lives at each finalization site. The ONLY per-plane difference is
//! the sandbox-facing URL, captured here. Centralizing the URL choice (instead
//! of scattering `match sandbox_provider {}` gates) is what keeps a provider —
//! historically Docker — from being silently excluded from identity binding.
use uuid::Uuid;

use crate::egress::policy::synthetic_credential_route_url;

#[derive(Debug, Clone)]
pub enum EgressPlane {
    /// Per-sandbox Envoy reached over a unix socket. The runner's `socat`
    /// forward proxy preserves the Host header, so placeholder hosts
    /// (`*-egress.internal`) route to the sandbox's Envoy and transparent
    /// (real-host) routes keep their real URL.
    Docker,
    /// Shared Envoy reached over TCP. Sandbox-facing URLs are rewritten to a
    /// per-sandbox synthetic path rooted at `credential_route_base_url`
    /// (the shared Envoy credential endpoint).
    K8s { credential_route_base_url: String },
}

impl EgressPlane {
    /// Select the plane when the egress policy authority is enabled. Returns
    /// `None` when the authority is disabled (no egress finalization runs), or
    /// when K8s is missing its shared-Envoy credential URL (preserves the prior
    /// lenient behavior of simply not finalizing rather than erroring).
    pub fn resolve(
        authority_enabled: bool,
        provider: &str,
        credential_route_base_url: Option<String>,
    ) -> Option<Self> {
        if !authority_enabled {
            return None;
        }
        if matches!(provider, "k8s" | "kubernetes") {
            credential_route_base_url.map(|base| EgressPlane::K8s {
                credential_route_base_url: base,
            })
        } else {
            Some(EgressPlane::Docker)
        }
    }

    /// Sandbox-facing URL for a placeholder-host credential route (LLM / MCP /
    /// Git): K8s → per-sandbox synthetic path; Docker → the placeholder host on
    /// the per-sandbox Envoy UDS (`http://<placeholder_host><suffix>`).
    pub fn placeholder_route_url(
        &self,
        sandbox_id: Uuid,
        route_id: &str,
        placeholder_host: &str,
        suffix: &str,
    ) -> String {
        match self {
            EgressPlane::K8s {
                credential_route_base_url,
            } => format!(
                "{}{}",
                synthetic_credential_route_url(credential_route_base_url, sandbox_id, route_id),
                suffix
            ),
            EgressPlane::Docker => format!("http://{placeholder_host}{suffix}"),
        }
    }

    /// Sandbox-facing URL for a TRANSPARENT external route (whose match host is
    /// the REAL upstream host): K8s → `Some(synthetic per-sandbox path)`; Docker
    /// → `None`, meaning keep the real configured URL — the runner's forward
    /// proxy + Envoy's real-host vhost route it, and only the identity credential
    /// is bound.
    pub fn transparent_route_url(
        &self,
        sandbox_id: Uuid,
        route_id: &str,
        suffix: &str,
    ) -> Option<String> {
        match self {
            EgressPlane::K8s {
                credential_route_base_url,
            } => Some(format!(
                "{}{}",
                synthetic_credential_route_url(credential_route_base_url, sandbox_id, route_id),
                suffix
            )),
            EgressPlane::Docker => None,
        }
    }
}
