use std::collections::HashMap;

use base64::Engine as _;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use crate::ids::SandboxId;

/// Which sandbox listener this is.
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
    /// Credential-injection routes (only meaningful for [`ListenerKind::Http`]).
    /// When present, the HTTP listener gains extra virtual hosts / routes that
    /// match plaintext requests from the sandbox, inject the real secret at the
    /// egress boundary, and forward (optionally over TLS) to the true upstream.
    /// The sandbox itself never holds these secrets.
    pub credentials: Vec<EgressCredentialRoute>,
    /// Expected HTTP proxy authorization token for this sandbox listener.
    pub proxy_auth_token: Option<String>,
}

/// Credential family used for diagnostics and future policy decisions. Envoy
/// rendering is intentionally generic: all kinds reduce to the same route +
/// injected-header shape so LLM, MCP, Git, and external services share one
/// egress boundary implementation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EgressKind {
    Llm,
    Mcp,
    Git,
    External,
}

/// How the sandbox discovers the route.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
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

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum EgressPathMatcher {
    Any,
    Exact(String),
    Prefix(String),
}

#[derive(Debug, Clone, PartialEq, Eq)]
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

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
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
    /// Headers to inject (real secret). Overwrites any client-provided value.
    pub inject_headers: Vec<(String, String)>,
    /// Headers to remove before injection. This prevents sandbox-supplied auth
    /// from shadowing or mixing with platform credentials.
    pub remove_headers: Vec<String>,
}

impl std::fmt::Debug for EgressCredentialRoute {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let inject_header_names: Vec<&str> = self
            .inject_headers
            .iter()
            .map(|(name, _)| name.as_str())
            .collect();
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
            .field("inject_header_names", &inject_header_names)
            .field("inject_header_values", &"<redacted>")
            .field("remove_headers", &self.remove_headers)
            .finish()
    }
}

/// A per-upstream cluster spec delivered via CDS. MCP routes carry vetted IPs
/// and render as STATIC clusters; legacy callers without pinned addresses keep
/// using the existing DNS behavior.
#[derive(Debug, Clone)]
pub struct ClusterSpec {
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

const CREDENTIAL_AUTH_HEADERS: &[&str] =
    &["authorization", "x-api-key", "api-key", "x-goog-api-key"];

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
/// allowlist hosts for ordinary egress plus credential-injection routes for any
/// credential family. The routes hold plaintext secrets and must never be
/// persisted or logged.
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

    pub fn clusters(&self, _sandbox_id: &SandboxId) -> Vec<ClusterSpec> {
        let mut clusters = std::collections::BTreeMap::new();
        for route in &self.credential_routes {
            if route.vetted_addresses.is_empty() {
                continue;
            }
            clusters
                .entry(route.cluster_name.clone())
                .or_insert_with(|| ClusterSpec {
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

pub fn validate_egress_policy(
    sandbox_id: &SandboxId,
    policy: &SandboxEgressPolicy,
) -> anyhow::Result<()> {
    let mut route_ids = std::collections::HashSet::new();
    const SHARED_CLUSTERS: &[&str] = &["dynamic_forward_proxy", "dynamic_forward_proxy_tls"];
    let pinned_clusters = policy
        .clusters(sandbox_id)
        .into_iter()
        .map(|cluster| cluster.name)
        .collect::<std::collections::HashSet<_>>();

    for host in &policy.allowlist_hosts {
        validate_route_host(host)
            .map_err(|e| anyhow::anyhow!("invalid allowlist host {host}: {e}"))?;
    }

    for route in &policy.credential_routes {
        if !route_ids.insert(route.id.as_str()) {
            anyhow::bail!("duplicate egress route id: {}", route.id);
        }
        validate_route_host(&route.match_host)
            .map_err(|e| anyhow::anyhow!("invalid egress match_host {}: {e}", route.match_host))?;
        validate_route_host(&route.upstream_host).map_err(|e| {
            anyhow::anyhow!("invalid egress upstream_host {}: {e}", route.upstream_host)
        })?;
        match &route.path_mapping {
            EgressPathMapping::Passthrough {
                matcher: EgressPathMatcher::Any,
            } => {}
            EgressPathMapping::Passthrough {
                matcher: EgressPathMatcher::Exact(path),
            }
            | EgressPathMapping::Passthrough {
                matcher: EgressPathMatcher::Prefix(path),
            } => validate_route_path(path)
                .map_err(|e| anyhow::anyhow!("invalid egress path {path}: {e}"))?,
            EgressPathMapping::RewriteExact {
                exposed_path,
                upstream_path,
            }
            | EgressPathMapping::RewritePrefix {
                exposed_prefix: exposed_path,
                upstream_prefix: upstream_path,
            } => {
                validate_route_path(exposed_path).map_err(|e| {
                    anyhow::anyhow!("invalid exposed egress path {exposed_path}: {e}")
                })?;
                validate_route_path(upstream_path).map_err(|e| {
                    anyhow::anyhow!("invalid upstream egress path {upstream_path}: {e}")
                })?;
            }
        }
        if route.cluster_name.is_empty()
            || (!SHARED_CLUSTERS.contains(&route.cluster_name.as_str())
                && !pinned_clusters.contains(&route.cluster_name))
        {
            anyhow::bail!(
                "egress route {} references unknown cluster {}",
                route.id,
                route.cluster_name
            );
        }
        for address in &route.vetted_addresses {
            address.parse::<std::net::IpAddr>().map_err(|_| {
                anyhow::anyhow!("invalid vetted address {address} on route {}", route.id)
            })?;
        }
        for (header, _) in &route.inject_headers {
            validate_header_name(header).map_err(|e| {
                anyhow::anyhow!(
                    "invalid injected header {header} on route {}: {e}",
                    route.id
                )
            })?;
        }
        for header in &route.remove_headers {
            validate_header_name(header).map_err(|e| {
                anyhow::anyhow!("invalid removed header {header} on route {}: {e}", route.id)
            })?;
        }
    }

    let mut domains = std::collections::HashMap::<String, String>::new();
    let credential_match_hosts: Vec<String> = policy
        .credential_routes
        .iter()
        .map(|route| canonical_policy_host(&route.match_host))
        .collect::<anyhow::Result<Vec<_>>>()?;
    for (host, routes) in group_credentials_by_host(&policy.credential_routes) {
        for domain in domains_for_credential_host(&host, &routes) {
            let domain = canonical_policy_domain(&domain)?;
            if let Some(existing) = domains.insert(domain.clone(), format!("credential:{host}")) {
                anyhow::bail!("duplicate Envoy virtual-host domain {domain} between {existing} and credential:{host}");
            }
        }
    }
    for host in &policy.allowlist_hosts {
        for credential_host in &credential_match_hosts {
            if allowlist_host_covers_credential_host(host, credential_host)? {
                anyhow::bail!(
                    "allowlist host {host} overlaps credential-injection host {credential_host}; remove it to prevent CONNECT/plain egress bypass"
                );
            }
        }
        for domain in domains_for_allowlist_host(host) {
            let domain = canonical_policy_domain(&domain)?;
            if let Some(existing) = domains.insert(domain.clone(), "allowlist".to_string()) {
                anyhow::bail!(
                    "duplicate Envoy virtual-host domain {domain} between {existing} and allowlist"
                );
            }
        }
    }
    Ok(())
}

pub fn rendered_egress_policy_summary(
    sandbox_id: &SandboxId,
    policy: &SandboxEgressPolicy,
) -> Value {
    let routes: Vec<Value> = policy
        .credential_routes
        .iter()
        .map(|route| {
            let inject_headers: Vec<Value> = route
                .inject_headers
                .iter()
                .map(|(name, value)| {
                    let mut hasher = Sha256::new();
                    hasher.update(value.as_bytes());
                    json!({
                        "name": name.to_ascii_lowercase(),
                        "value_sha256": hex::encode(hasher.finalize()),
                    })
                })
                .collect();
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
                "inject_headers": inject_headers,
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

pub(crate) fn auth_headers_to_remove(inject_headers: &[(String, String)]) -> Vec<String> {
    CREDENTIAL_AUTH_HEADERS
        .iter()
        .filter(|candidate| {
            !inject_headers
                .iter()
                .any(|(header, _)| header.eq_ignore_ascii_case(candidate))
        })
        .map(|header| header.to_string())
        .collect()
}

/// Escape `%` → `%%` in header values so Envoy treats them as literal
/// characters instead of StreamInfo substitution format markers.
///
/// Without this, a credential value like `session_id=abc%7Cdef` causes
/// Envoy to interpret `%7C` as a format variable and reject the listener
/// with `Not supported field in StreamInfo: 7C`.
pub(crate) fn escape_envoy_header_value(raw: &str) -> String {
    raw.replace('%', "%%")
}

pub(crate) fn proxy_authorization_value(token: &str) -> String {
    format!(
        "Basic {}",
        base64::engine::general_purpose::STANDARD.encode(format!("sandbox:{token}"))
    )
}

pub(crate) fn sha256_hex(value: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(value.as_bytes());
    hex::encode(hasher.finalize())
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

fn domains_for_allowlist_host(host: &str) -> Vec<String> {
    let mut domains = vec![host.to_string()];
    if !host.contains(':') {
        domains.push(format!("{host}:443"));
        domains.push(format!("{host}:80"));
    }
    domains
}

fn canonical_policy_domain(domain: &str) -> anyhow::Result<String> {
    let trimmed = domain.trim().trim_end_matches('.').to_ascii_lowercase();
    validate_route_host(&trimmed)?;
    Ok(trimmed)
}

fn canonical_policy_host(host: &str) -> anyhow::Result<String> {
    let domain = canonical_policy_domain(host)?;
    Ok(domain
        .rsplit_once(':')
        .and_then(|(base, port)| port.parse::<u16>().ok().map(|_| base.to_string()))
        .unwrap_or(domain))
}

fn allowlist_host_covers_credential_host(
    allowlist_host: &str,
    credential_host: &str,
) -> anyhow::Result<bool> {
    let allow = canonical_policy_host(allowlist_host)?;
    let credential = canonical_policy_host(credential_host)?;
    if allow == credential {
        return Ok(true);
    }
    if let Some(suffix) = allow.strip_prefix("*.") {
        return Ok(credential == suffix || credential.ends_with(&format!(".{suffix}")));
    }
    Ok(false)
}

fn validate_route_host(host: &str) -> anyhow::Result<()> {
    let trimmed = host.trim();
    if trimmed.is_empty() {
        anyhow::bail!("host is empty");
    }
    if trimmed.contains('/') || trimmed.contains(' ') || trimmed.contains('\t') {
        anyhow::bail!("host must not contain path, whitespace, or scheme");
    }
    if trimmed.contains("://") {
        anyhow::bail!("host must not include scheme");
    }
    Ok(())
}

fn validate_route_path(path: &str) -> anyhow::Result<()> {
    if !path.starts_with('/') {
        anyhow::bail!("path must start with '/'");
    }
    if path.contains('\n') || path.contains('\r') || path.contains('\0') {
        anyhow::bail!("path contains control characters");
    }
    Ok(())
}

fn validate_header_name(name: &str) -> anyhow::Result<()> {
    let trimmed = name.trim();
    if trimmed.is_empty() {
        anyhow::bail!("header name is empty");
    }
    if !trimmed.bytes().all(|byte| {
        byte.is_ascii_alphanumeric()
            || matches!(
                byte,
                b'!' | b'#'
                    | b'$'
                    | b'%'
                    | b'&'
                    | b'\''
                    | b'*'
                    | b'+'
                    | b'-'
                    | b'.'
                    | b'^'
                    | b'_'
                    | b'`'
                    | b'|'
                    | b'~'
            )
    }) {
        anyhow::bail!("header name is not a valid HTTP token");
    }
    Ok(())
}

impl ListenerSpec {
    /// Resource name Envoy sees, e.g. `"<uuid>_http"`.
    pub fn resource_name(&self) -> String {
        match self.kind {
            ListenerKind::Http => format!("{}_http", self.sandbox_id.as_uuid()),
        }
    }
}
