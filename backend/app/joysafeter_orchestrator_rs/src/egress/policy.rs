use std::collections::HashSet;

use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// Credential family used for diagnostics and future policy decisions. Provider
/// renderers should treat all kinds through the same allowlist + injection
/// contract unless a kind explicitly needs stricter validation.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum EgressKind {
    Llm,
    Mcp,
    Git,
    External,
}

/// How the sandbox discovers the route.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum EgressExposure {
    /// The sandbox calls a platform placeholder host; the egress boundary
    /// rewrites to the real upstream. This is required for credential injection
    /// without TLS MITM when the upstream is HTTPS.
    Placeholder,
    /// The sandbox calls the real upstream host and the egress boundary injects
    /// credentials transparently. This only works for plaintext HTTP unless the
    /// boundary terminates TLS for that upstream.
    Transparent,
}

/// A non-secret reference to where a credential's secret material lives. The
/// orchestrator's `CredentialBroker` resolves this to the actual secret at
/// request time; it is safe to persist and log because it contains no secret
/// values — only lookup coordinates (names, ids, urls).
///
/// This type lives in `egress::policy` (the lib-crate-safe subgraph) and must
/// never gain a `VaultCipher` or secret-string field: the resolution logic
/// lives outside this subgraph, in the orchestrator-only broker.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum CredentialRef {
    /// LLM model key sourced from a managed Secret (`joysafeter_secrets.data[key]`).
    /// The credential value never enters the sandbox env; the resolver records
    /// this identity instead of decrypting.
    Llm {
        secret_name: String,
        secret_key: String,
        project_id: Option<String>,
    },
    /// MCP server token from a session vault credential
    /// (`joysafeter_vault_credentials.token_value`), matched by URL.
    Mcp {
        vault_id: Uuid,
        mcp_server_url: String,
    },
    /// Git token from a session repo (`joysafeter_session_repos.encrypted_token`).
    Git {
        session_id: Uuid,
        mount_name: String,
    },
    /// External-service secret field (`joysafeter_secrets.data[key]`).
    External {
        secret_name: String,
        secret_key: String,
        project_id: Option<String>,
    },
}

/// How the broker formats a resolved secret into the injected header value.
/// Mirrors the historical inline formatting (`Bearer {token}` / `Basic {b64}` /
/// raw) so the byte-identical header can be reconstructed from a ref + scheme.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum InjectScheme {
    /// `<header>: Bearer <secret>`.
    Bearer,
    /// HTTP Basic with a fixed username: `<header>: Basic base64("{username}:{secret}")`.
    Basic { username: String },
    /// The resolved secret is used verbatim as the header value (api-key,
    /// cookie, `x-goog-api-key`, …).
    Raw,
}

/// A single credential-injection route in the provider-neutral egress policy.
///
/// Renderers match `match_host` + `match_prefix`, remove any sandbox-supplied
/// auth headers, inject the platform credential (resolved from `credential_ref`
/// at request time), rewrite the upstream authority and path when needed, and
/// forward to `upstream_host:upstream_port`. This type carries only a
/// **non-secret** `credential_ref`; it is safe to persist and log.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EgressCredentialRoute {
    /// Stable route id scoped by the owning sandbox policy.
    pub id: String,
    /// Credential family.
    pub kind: EgressKind,
    /// Placeholder vs transparent exposure.
    pub exposure: EgressExposure,
    /// Host the sandbox targets or the transparent upstream host.
    pub match_host: String,
    /// Path prefix the sandbox uses, e.g. `/`, `/mcp/<name>/`, `/git/<slug>/`,
    /// or `/services/<name>/`. When `exact_path` is true this is matched as an
    /// exact path instead of a prefix.
    pub match_prefix: String,
    /// When true, `match_prefix` is matched as an exact path instead of a
    /// prefix. Used by external-service path allowlists.
    pub exact_path: bool,
    /// Real upstream authority to rewrite Host/SNI to.
    pub upstream_host: String,
    /// Real upstream port.
    pub upstream_port: u16,
    /// Prefix to substitute for `match_prefix` on the upstream, e.g. `/` or the
    /// real MCP/git base path.
    pub upstream_prefix: String,
    /// Whether to TLS-originate to the upstream.
    pub upstream_tls: bool,
    /// Provider-rendered cluster/upstream name. Empty means the renderer should
    /// derive one from sandbox id + upstream.
    pub cluster_name: String,
    /// Non-secret reference to the credential's secret material. Resolved to the
    /// formatted header value by the `CredentialBroker` at request time.
    pub credential_ref: CredentialRef,
    /// Header NAME the resolved credential is injected into, e.g.
    /// `"authorization"`, `"x-api-key"`, `"cookie"`.
    pub inject_header: String,
    /// How the broker formats the resolved secret into the header value.
    pub inject_scheme: InjectScheme,
    /// Headers to remove before injection.
    pub remove_headers: Vec<String>,
}

/// Backward-compatible alias while call sites migrate to the unified egress
/// policy vocabulary.
pub type CredentialRoute = EgressCredentialRoute;

/// A per-upstream cluster/target spec. The sandbox never sees this.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ClusterSpec {
    /// Cluster name referenced by [`EgressCredentialRoute::cluster_name`].
    pub name: String,
    /// Real upstream host to resolve + connect to.
    pub upstream_host: String,
    /// Upstream port.
    pub upstream_port: u16,
    /// Whether to TLS-originate to the upstream.
    pub upstream_tls: bool,
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

/// Deterministic upstream name for a sandbox's upstream host. Scoped per
/// sandbox so rendered upstream sets never collide across sandboxes.
pub fn upstream_cluster_name(sandbox_id: &Uuid, upstream_host: &str, upstream_port: u16) -> String {
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
    format!("up_{sandbox_id}_{safe}_{upstream_port}")
}

/// Unified egress policy for one sandbox.
///
/// `allowlist_hosts` is non-sensitive. `credential_routes` carry only non-secret
/// `credential_ref`s (no decrypted secrets), so this policy is safe to persist
/// and log.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SandboxEgressPolicy {
    pub allowlist_hosts: Vec<String>,
    pub credential_routes: Vec<EgressCredentialRoute>,
}

impl SandboxEgressPolicy {
    pub fn clusters(&self, sandbox_id: &Uuid) -> Vec<ClusterSpec> {
        let mut seen = HashSet::new();
        let mut clusters = Vec::new();
        for route in &self.credential_routes {
            let name = if route.cluster_name.is_empty() {
                upstream_cluster_name(sandbox_id, &route.upstream_host, route.upstream_port)
            } else {
                route.cluster_name.clone()
            };
            if seen.insert(name.clone()) {
                clusters.push(ClusterSpec {
                    name,
                    upstream_host: route.upstream_host.clone(),
                    upstream_port: route.upstream_port,
                    upstream_tls: route.upstream_tls,
                });
            }
        }
        clusters
    }
}

/// Orchestrator-facing set of credential routes for one sandbox, built from DB
/// rows. Converted to [`SandboxEgressPolicy`] before it reaches provider-specific
/// rendering. Routes carry only non-secret `credential_ref`s.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SandboxCredentials {
    pub routes: Vec<EgressCredentialRoute>,
}

impl SandboxCredentials {
    pub fn to_policy(
        &self,
        sandbox_id: &Uuid,
        allowlist_hosts: Vec<String>,
    ) -> SandboxEgressPolicy {
        SandboxEgressPolicy {
            allowlist_hosts,
            credential_routes: self.to_routes(sandbox_id),
        }
    }

    /// Fill each route's renderer-specific upstream name when the builder left
    /// it empty.
    pub fn to_routes(&self, sandbox_id: &Uuid) -> Vec<CredentialRoute> {
        self.routes
            .iter()
            .map(|r| {
                let mut route = r.clone();
                if route.cluster_name.is_empty() {
                    route.cluster_name = upstream_cluster_name(
                        sandbox_id,
                        &route.upstream_host,
                        route.upstream_port,
                    );
                }
                route
            })
            .collect()
    }

    /// The per-upstream targets this sandbox needs, de-duplicated by name.
    pub fn to_clusters(&self, sandbox_id: &Uuid) -> Vec<ClusterSpec> {
        self.to_policy(sandbox_id, vec![]).clusters(sandbox_id)
    }
}

/// Ensure a path prefix is non-empty and starts with `/`.
#[allow(dead_code)]
pub(crate) fn normalize_prefix(p: &str) -> String {
    if p.is_empty() {
        "/".to_string()
    } else if p.starts_with('/') {
        p.to_string()
    } else {
        format!("/{p}")
    }
}

#[allow(dead_code)]
pub(crate) fn normalize_rewrite_base_prefix(p: &str) -> String {
    let mut prefix = normalize_prefix(p);
    if prefix != "/" && !prefix.ends_with('/') {
        prefix.push('/');
    }
    prefix
}

/// Parsed upstream target from a URL.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UpstreamTarget {
    pub host: String,
    pub port: u16,
    pub prefix: String,
    pub tls: bool,
}

impl UpstreamTarget {
    /// Parse a URL into upstream target components. Errors on unsupported
    /// schemes (only http/https) or a missing host.
    pub fn from_url(raw: &str) -> anyhow::Result<Self> {
        let url = url::Url::parse(raw)?;
        let tls = match url.scheme() {
            "https" => true,
            "http" => false,
            other => anyhow::bail!("unsupported scheme: {other}"),
        };
        let host = url
            .host_str()
            .ok_or_else(|| anyhow::anyhow!("URL has no host"))?
            .to_string();
        let port = url.port().unwrap_or(if tls { 443 } else { 80 });
        let prefix = if url.path().is_empty() {
            "/".to_string()
        } else {
            url.path().to_string()
        };
        Ok(Self {
            host,
            port,
            prefix,
            tls,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn route(id: &str, kind: EgressKind, host: &str, port: u16) -> EgressCredentialRoute {
        EgressCredentialRoute {
            id: id.to_string(),
            kind,
            exposure: EgressExposure::Placeholder,
            match_host: LLM_EGRESS_HOST.to_string(),
            match_prefix: "/".to_string(),
            exact_path: false,
            upstream_host: host.to_string(),
            upstream_port: port,
            upstream_prefix: "/".to_string(),
            upstream_tls: true,
            cluster_name: String::new(),
            credential_ref: CredentialRef::Llm {
                secret_name: "test-secret".to_string(),
                secret_key: "ANTHROPIC_API_KEY".to_string(),
                project_id: None,
            },
            inject_header: "authorization".to_string(),
            inject_scheme: InjectScheme::Bearer,
            remove_headers: vec!["authorization".to_string()],
        }
    }

    #[test]
    fn provider_conformance_credentials_to_policy_fills_stable_cluster_names() {
        let sandbox_id =
            Uuid::parse_str("018ff000-0000-7000-8000-000000000001").expect("valid sandbox uuid");
        let credentials = SandboxCredentials {
            routes: vec![route("llm", EgressKind::Llm, "api.anthropic.com", 443)],
        };

        let policy = credentials.to_policy(&sandbox_id, vec!["example.com".to_string()]);

        assert_eq!(policy.allowlist_hosts, vec!["example.com".to_string()]);
        assert_eq!(policy.credential_routes.len(), 1);
        assert_eq!(
            policy.credential_routes[0].cluster_name,
            format!("up_{sandbox_id}_api_anthropic_com_443")
        );
        assert_eq!(policy.clusters(&sandbox_id).len(), 1);
    }

    #[test]
    fn provider_conformance_policy_clusters_dedupe_shared_upstreams_across_kinds() {
        let sandbox_id =
            Uuid::parse_str("018ff000-0000-7000-8000-000000000002").expect("valid sandbox uuid");
        let policy = SandboxEgressPolicy {
            allowlist_hosts: vec![],
            credential_routes: vec![
                route("llm", EgressKind::Llm, "gateway.example.com", 443),
                route("mcp:primary", EgressKind::Mcp, "gateway.example.com", 443),
                route("git:repo", EgressKind::Git, "git.example.com", 443),
            ],
        };

        let clusters = policy.clusters(&sandbox_id);

        assert_eq!(clusters.len(), 2);
        assert!(clusters
            .iter()
            .any(|cluster| cluster.upstream_host == "gateway.example.com"));
        assert!(clusters
            .iter()
            .any(|cluster| cluster.upstream_host == "git.example.com"));
    }

    #[test]
    fn provider_conformance_upstream_target_rejects_non_http_schemes() {
        let err = UpstreamTarget::from_url("file:///tmp/socket")
            .expect_err("only HTTP(S) upstreams are valid for egress policy");

        assert!(format!("{err}").contains("unsupported scheme"));
    }
}
