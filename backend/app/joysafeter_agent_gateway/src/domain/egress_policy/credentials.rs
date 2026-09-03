use std::collections::HashMap;

use base64::Engine as _;

use super::model::{
    upstream_cluster_name, ClusterSpec, EgressCredentialRoute, EgressRouteSpec, SandboxEgressPolicy,
};
use crate::ids::SandboxId;

const CREDENTIAL_AUTH_HEADERS: &[&str] =
    &["authorization", "x-api-key", "api-key", "x-goog-api-key"];

/// Orchestrator-facing description of the real secrets for one sandbox,
/// built from decrypted DB rows and converted to [`SandboxEgressPolicy`] before it
/// reaches Envoy rendering. This type holds plaintext secrets and must never be
/// persisted or logged.
///
/// All credential families (LLM, MCP, Git, External) are unified as a flat list
/// of [`EgressCredentialRoute`]. Builders emit routes directly; the `kind` field
/// on each route is diagnostic. To add a new credential type, write a builder
/// that returns `Vec<EgressCredentialRoute>` and `extend` this list — no
/// intermediate struct or `to_routes` change needed.
#[derive(Clone, Default)]
pub struct SandboxCredentials {
    pub routes: Vec<EgressCredentialRoute>,
    /// Per-sandbox bearer material used only to authenticate local proxy access
    /// from the sandbox runner to its own Envoy HTTP listener.
    pub proxy_auth_token: Option<String>,
}

impl std::fmt::Debug for SandboxCredentials {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SandboxCredentials")
            .field("routes", &self.routes)
            .field(
                "proxy_auth_token",
                &self.proxy_auth_token.as_ref().map(|_| "<redacted>"),
            )
            .finish()
    }
}

impl SandboxCredentials {
    pub fn with_proxy_auth_token(mut self, token: Option<String>) -> Self {
        self.proxy_auth_token = token;
        self
    }

    pub fn to_policy(
        &self,
        sandbox_id: &SandboxId,
        allowlist_hosts: Vec<String>,
    ) -> SandboxEgressPolicy {
        SandboxEgressPolicy {
            allowlist_hosts,
            credential_routes: self.to_routes(sandbox_id),
            proxy_auth_token: self.proxy_auth_token.clone(),
        }
    }

    /// Flatten into credential routes. Routes with activation-vetted addresses
    /// receive a sandbox-scoped static cluster; other credential families keep
    /// the shared dynamic-forward-proxy clusters.
    pub fn to_routes(&self, sandbox_id: &SandboxId) -> Vec<EgressCredentialRoute> {
        self.routes
            .iter()
            .map(|r| {
                let mut route = r.clone();
                if route.cluster_name.is_empty() {
                    route.cluster_name = if !route.vetted_addresses.is_empty() {
                        upstream_cluster_name(
                            sandbox_id,
                            &route.upstream_host,
                            route.upstream_port,
                            route.upstream_tls,
                        )
                    } else if route.upstream_tls {
                        "dynamic_forward_proxy_tls".to_string()
                    } else {
                        "dynamic_forward_proxy".to_string()
                    };
                }
                route
            })
            .collect()
    }

    /// The per-upstream STRICT_DNS clusters this sandbox needs, de-duplicated by
    /// cluster name (multiple MCP servers may share a host).
    pub fn to_clusters(&self, sandbox_id: &SandboxId) -> Vec<ClusterSpec> {
        self.to_policy(sandbox_id, vec![]).clusters(sandbox_id)
    }
}

/// Parsed upstream target from a URL. Eliminates the redundant
/// `Url::parse` → host/port/prefix/tls extraction duplicated across the
/// LLM/MCP/Git/External credential builders. `prefix` is the raw URL path
/// (`/` when empty); callers apply their own prefix normalization on top.
#[derive(Debug, Clone)]
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

pub(crate) fn upstream_authority(host: &str, port: u16, tls: bool) -> String {
    if (tls && port == 443) || (!tls && port == 80) {
        host.to_string()
    } else {
        format!("{host}:{port}")
    }
}

/// Escape Envoy StreamInfo substitution markers in literal credential values.
pub(crate) fn escape_envoy_header_value(raw: &str) -> String {
    raw.replace('%', "%%")
}

/// Build the upstream header-removal set for a credential route.
///
/// Callers may provide an explicit removal contract (for example Agent
/// Identity also removes cookies). When they do not, remove every competing
/// credential header except the one being injected. Proxy authentication is
/// listener-local authority and must never be forwarded upstream.
pub(crate) fn upstream_headers_to_remove(route: &EgressRouteSpec) -> Vec<String> {
    let mut headers = if route.remove_headers.is_empty() {
        CREDENTIAL_AUTH_HEADERS
            .iter()
            .filter(|candidate| {
                !route
                    .inject_headers
                    .iter()
                    .any(|(header, _)| header.eq_ignore_ascii_case(candidate))
            })
            .map(|header| (*header).to_string())
            .collect::<Vec<_>>()
    } else {
        route.remove_headers.clone()
    };
    if !headers
        .iter()
        .any(|header| header.eq_ignore_ascii_case("proxy-authorization"))
    {
        headers.push("proxy-authorization".to_string());
    }
    headers
}

pub(crate) fn proxy_authorization_value(token: &str) -> String {
    format!(
        "Basic {}",
        base64::engine::general_purpose::STANDARD.encode(format!("sandbox:{token}"))
    )
}

pub(crate) fn domains_for_credential_host(
    match_host: &str,
    routes: &[EgressCredentialRoute],
) -> Vec<String> {
    let mut domains = vec![
        match_host.to_string(),
        format!("{match_host}:80"),
        format!("{match_host}:443"),
    ];
    for route in routes {
        if route.upstream_port != 80 && route.upstream_port != 443 {
            let with_port = format!("{match_host}:{}", route.upstream_port);
            if !domains.iter().any(|domain| domain == &with_port) {
                domains.push(with_port);
            }
        }
    }
    domains
}

/// Group credential routes by their placeholder `match_host`, returning a stable
/// (host-sorted) list with routes ordered longest exposed path first so more
/// specific prefixes are matched before `/`.
pub(crate) fn group_credentials_by_host(
    credentials: &[EgressCredentialRoute],
) -> Vec<(String, Vec<EgressCredentialRoute>)> {
    let mut by_host: HashMap<String, Vec<EgressCredentialRoute>> = HashMap::new();
    for r in credentials {
        by_host
            .entry(r.match_host.clone())
            .or_default()
            .push(r.clone());
    }
    let mut grouped: Vec<(String, Vec<EgressCredentialRoute>)> = by_host.into_iter().collect();
    grouped.sort_by(|a, b| a.0.cmp(&b.0));
    for (_, routes) in &mut grouped {
        routes.sort_by(|a, b| {
            b.path_mapping
                .exposed_path()
                .len()
                .cmp(&a.path_mapping.exposed_path().len())
        });
    }
    grouped
}

pub(crate) fn group_route_specs_by_host(
    routes: &[EgressRouteSpec],
) -> Vec<(String, Vec<EgressRouteSpec>)> {
    let mut by_host: HashMap<String, Vec<EgressRouteSpec>> = HashMap::new();
    for route in routes {
        by_host
            .entry(route.match_host.clone())
            .or_default()
            .push(route.clone());
    }
    let mut grouped = by_host.into_iter().collect::<Vec<_>>();
    grouped.sort_by(|left, right| left.0.cmp(&right.0));
    for (_, routes) in &mut grouped {
        routes.sort_by(|left, right| {
            right
                .path_mapping
                .exposed_path()
                .len()
                .cmp(&left.path_mapping.exposed_path().len())
        });
    }
    grouped
}
