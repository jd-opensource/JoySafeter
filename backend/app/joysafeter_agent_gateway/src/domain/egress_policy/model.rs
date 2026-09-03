use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::ids::SandboxId;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ListenerKind {
    /// HTTP connection-manager pipe enforcing the egress allowlist.
    Http,
}

/// Backend-neutral description of a single sandbox listener. Each backend renders
/// this to its own wire form (JSON for filesystem, typed protobuf for gRPC).
#[derive(Debug, Clone)]
pub struct ListenerSpec {
    pub sandbox_id: SandboxId,
    pub kind: ListenerKind,
    /// Egress allowlist (only meaningful for [`ListenerKind::Http`]).
    pub allowed_hosts: Vec<String>,
    /// Credential routes containing material supplied by the trusted management
    /// plane for direct xDS injection.
    pub credentials: Vec<EgressRouteSpec>,
    /// Expected HTTP proxy authorization token for this sandbox listener.
    pub proxy_auth_token: Option<String>,
}

/// Route projection delivered to Envoy. It can contain credential material and
/// therefore must only be observed through redacting diagnostics.
#[derive(Debug, Clone)]
pub struct EgressRouteSpec {
    pub id: String,
    pub exposure: EgressExposure,
    pub match_host: String,
    pub path_mapping: EgressPathMapping,
    pub retry_mode: EgressRetryMode,
    pub upstream_host: String,
    pub upstream_port: u16,
    pub upstream_tls: bool,
    pub cluster_name: String,
    /// Debug output for the parent policy never includes these values.
    pub inject_headers: Vec<(String, String)>,
    pub remove_headers: Vec<String>,
}

/// Credential family used for diagnostics and future policy decisions. Envoy
/// rendering is intentionally generic: all kinds reduce to the same route +
/// injected-header shape so LLM, MCP, Git, and external services share one
/// egress boundary implementation.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EgressKind {
    Llm,
    Mcp,
    Git,
    External,
}

/// How the sandbox discovers the route.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EgressExposure {
    /// The sandbox calls a platform placeholder host; Envoy rewrites to the real
    /// upstream. This is required for credential injection without TLS MITM when
    /// the upstream is HTTPS.
    Placeholder,
    /// The sandbox calls the real upstream host and Envoy injects credentials
    /// transparently. This only works for plaintext HTTP unless Envoy terminates
    /// TLS for that upstream.
    Transparent,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum EgressPathMatcher {
    Any,
    Exact(String),
    Prefix(String),
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum EgressPathMapping {
    Passthrough {
        matcher: EgressPathMatcher,
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

impl EgressPathMapping {
    pub(crate) fn exposed_path(&self) -> &str {
        match self {
            Self::Passthrough {
                matcher: EgressPathMatcher::Any,
            } => "/",
            Self::Passthrough {
                matcher: EgressPathMatcher::Exact(path),
            }
            | Self::Passthrough {
                matcher: EgressPathMatcher::Prefix(path),
            }
            | Self::RewriteExact {
                exposed_path: path, ..
            }
            | Self::RewritePrefix {
                exposed_prefix: path,
                ..
            } => path,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EgressRetryMode {
    Disabled,
    SafeIdempotent,
}

/// A single credential-injection route rendered into the HTTP listener.
///
/// Envoy matches `match_host` + `match_prefix` on the sandbox's own listener,
/// removes any sandbox-supplied auth headers, injects the real secret headers,
/// rewrites the authority/path when needed, and forwards via a per-upstream
/// STRICT_DNS cluster (`cluster_name`). Because the cluster endpoint is the real
/// host (resolved independently of request authority), `host_rewrite` only fixes
/// the Host header + TLS SNI.
#[derive(Clone)]
pub struct EgressCredentialRoute {
    /// Stable route id scoped by the owning sandbox policy.
    pub id: String,
    /// Credential family. Not used by Envoy rendering.
    pub kind: EgressKind,
    /// Placeholder vs transparent exposure. Not used by Envoy rendering yet, but
    /// kept on the route so external-service policies can validate HTTPS rules.
    pub exposure: EgressExposure,
    /// Host the sandbox targets or the transparent upstream host.
    pub match_host: String,
    /// Explicit match and rewrite behavior for the request path.
    pub path_mapping: EgressPathMapping,
    /// Whether Envoy may retry upstream failures for this route.
    pub retry_mode: EgressRetryMode,
    /// Real upstream authority to rewrite the Host header + SNI to.
    pub upstream_host: String,
    /// Real upstream port.
    pub upstream_port: u16,
    /// Whether to TLS-originate to the upstream.
    pub upstream_tls: bool,
    /// Name of the per-upstream STRICT_DNS cluster to route to.
    pub cluster_name: String,
    /// Activation-time DNS results. Non-empty values force a static cluster so
    /// Envoy cannot independently re-resolve a different destination.
    pub vetted_addresses: Vec<String>,
    /// Credential material accepted from the trusted management plane.
    pub inject_headers: Vec<(String, String)>,
    /// Headers to remove before injection. This prevents sandbox-supplied auth
    /// from shadowing or mixing with platform credentials.
    pub remove_headers: Vec<String>,
}

impl std::fmt::Debug for EgressCredentialRoute {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("EgressCredentialRoute")
            .field("id", &self.id)
            .field("kind", &self.kind)
            .field("exposure", &self.exposure)
            .field("match_host", &self.match_host)
            .field("path_mapping", &self.path_mapping)
            .field("retry_mode", &self.retry_mode)
            .field("upstream_host", &self.upstream_host)
            .field("upstream_port", &self.upstream_port)
            .field("upstream_tls", &self.upstream_tls)
            .field("cluster_name", &self.cluster_name)
            .field("vetted_addresses", &self.vetted_addresses)
            .field(
                "inject_headers",
                &self
                    .inject_headers
                    .iter()
                    .map(|(name, _)| name)
                    .collect::<Vec<_>>(),
            )
            .field("inject_header_values", &"<redacted>")
            .field("remove_headers", &self.remove_headers)
            .finish()
    }
}

impl EgressCredentialRoute {
    pub fn to_route_spec(&self) -> EgressRouteSpec {
        EgressRouteSpec {
            id: self.id.clone(),
            exposure: self.exposure,
            match_host: self.match_host.clone(),
            path_mapping: self.path_mapping.clone(),
            retry_mode: self.retry_mode,
            upstream_host: self.upstream_host.clone(),
            upstream_port: self.upstream_port,
            upstream_tls: self.upstream_tls,
            cluster_name: self.cluster_name.clone(),
            inject_headers: self.inject_headers.clone(),
            remove_headers: self.remove_headers.clone(),
        }
    }
}

/// A per-upstream cluster spec delivered via CDS. MCP routes carry vetted IPs
/// and render as STATIC clusters; legacy callers without pinned addresses keep
/// using the existing DNS behavior.
#[derive(Debug, Clone)]
pub struct ClusterSpec {
    /// Sandbox that owns this cluster.
    pub sandbox_id: SandboxId,
    /// Cluster name referenced by [`EgressCredentialRoute::cluster_name`].
    pub name: String,
    /// Real upstream host to resolve + connect to.
    pub upstream_host: String,
    /// Upstream port (443 for TLS, 80 otherwise unless the URL specified one).
    pub upstream_port: u16,
    /// Whether to TLS-originate to the upstream.
    pub upstream_tls: bool,
    /// Activation-time DNS answers. Non-empty means Envoy must use STATIC
    /// endpoints and must not resolve `upstream_host` itself.
    pub vetted_addresses: Vec<String>,
}

/// Placeholder host the sandbox uses for LLM API calls.
pub const LLM_EGRESS_HOST: &str = "llm-egress.internal";
/// Placeholder host the sandbox uses for MCP server calls.
pub const MCP_EGRESS_HOST: &str = "mcp-egress.internal";
/// Placeholder host the sandbox uses for git remote operations.
pub const GIT_EGRESS_HOST: &str = "git-egress.internal";
/// Placeholder host the sandbox uses for external service calls.
pub const EXTERNAL_EGRESS_HOST: &str = "external-egress.internal";

/// Stable slug for a session repo, used in the `/git/<slug>/` egress path. Both
/// the egress-route builder and the clone-URL rewrite must agree on this.
pub fn git_repo_slug(mount_name: &str, idx: usize) -> String {
    let trimmed = mount_name.trim();
    if trimmed.is_empty() {
        format!("repo{idx}")
    } else {
        trimmed
            .chars()
            .map(|c| {
                if c.is_ascii_alphanumeric() || c == '-' || c == '_' {
                    c
                } else {
                    '-'
                }
            })
            .collect()
    }
}

/// Deterministic cluster name for a sandbox's upstream host. Scoped per sandbox
/// so cluster sets never collide across sandboxes sharing the Envoy.
pub fn upstream_cluster_name(
    sandbox_id: &SandboxId,
    upstream_host: &str,
    upstream_port: u16,
    upstream_tls: bool,
) -> String {
    // Envoy cluster names must be simple; sanitise host to alnum/_/-.
    let safe: String = upstream_host
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '-' {
                c
            } else {
                '_'
            }
        })
        .collect();
    let scheme = if upstream_tls { "tls" } else { "plain" };
    format!(
        "up_{}_{safe}_{upstream_port}_{scheme}",
        sandbox_id.as_uuid()
    )
}

/// Unified egress policy for one sandbox. This is the Envoy-facing abstraction:
/// allowlist hosts for ordinary egress plus direct-xDS credential routes.
#[derive(Clone, Default)]
pub struct SandboxEgressPolicy {
    pub allowlist_hosts: Vec<String>,
    pub credential_routes: Vec<EgressCredentialRoute>,
    pub proxy_auth_token: Option<String>,
}

impl std::fmt::Debug for SandboxEgressPolicy {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SandboxEgressPolicy")
            .field("allowlist_hosts", &self.allowlist_hosts)
            .field("credential_routes", &self.credential_routes)
            .field(
                "proxy_auth_token",
                &self.proxy_auth_token.as_ref().map(|_| "<redacted>"),
            )
            .finish()
    }
}

impl SandboxEgressPolicy {
    pub fn with_proxy_auth_token(mut self, token: Option<String>) -> Self {
        self.proxy_auth_token = token;
        self
    }

    pub fn clusters(&self, sandbox_id: &SandboxId) -> Vec<ClusterSpec> {
        let mut clusters = std::collections::BTreeMap::new();
        for route in &self.credential_routes {
            if route.vetted_addresses.is_empty() {
                continue;
            }
            clusters
                .entry(route.cluster_name.clone())
                .or_insert_with(|| ClusterSpec {
                    sandbox_id: *sandbox_id,
                    name: route.cluster_name.clone(),
                    upstream_host: route.upstream_host.clone(),
                    upstream_port: route.upstream_port,
                    upstream_tls: route.upstream_tls,
                    vetted_addresses: route.vetted_addresses.clone(),
                });
        }
        clusters.into_values().collect()
    }
}

impl ListenerSpec {
    /// Resource name Envoy sees, e.g. `"<uuid>_http"`.
    pub fn resource_name(&self) -> String {
        match self.kind {
            ListenerKind::Http => format!("{}_http", self.sandbox_id.as_uuid()),
        }
    }
}

/// Diagnostic JSON view of a rendered egress policy (no secret material).
pub fn rendered_egress_policy_summary(
    sandbox_id: &SandboxId,
    policy: &SandboxEgressPolicy,
) -> Value {
    let routes: Vec<Value> = policy
        .credential_routes
        .iter()
        .map(|route| {
            json!({
                "id": route.id,
                "kind": format!("{:?}", route.kind),
                "exposure": format!("{:?}", route.exposure),
                "match_host": route.match_host,
                "path_mapping": format!("{:?}", route.path_mapping),
                "retry_mode": format!("{:?}", route.retry_mode),
                "upstream_host": route.upstream_host,
                "upstream_port": route.upstream_port,
                "upstream_tls": route.upstream_tls,
                "cluster_name": route.cluster_name,
                "vetted_addresses": route.vetted_addresses,
                "inject_header_names": route.inject_headers.iter().map(|(name, _)| name).collect::<Vec<_>>(),
                "remove_headers": route.remove_headers,
            })
        })
        .collect();
    let clusters: Vec<Value> = policy
        .clusters(sandbox_id)
        .into_iter()
        .map(|cluster| {
            json!({
                "name": cluster.name,
                "upstream_host": cluster.upstream_host,
                "upstream_port": cluster.upstream_port,
                "upstream_tls": cluster.upstream_tls,
                "vetted_addresses": cluster.vetted_addresses,
            })
        })
        .collect();
    json!({
        "allowlist_hosts": policy.allowlist_hosts,
        "credential_routes": routes,
        "clusters": clusters,
    })
}
