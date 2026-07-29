//! Pluggable LDS (Listener Discovery Service) backends for the per-sandbox
//! Envoy proxy.
//!
//! `EnvoyManager` describes each sandbox's two listeners (a gRPC TCP-proxy pipe
//! and an HTTP allowlist pipe) as neutral [`ListenerSpec`]s and hands them to an
//! [`LdsBackend`]. Two backends exist, selected at startup by
//! `JOYSAFETER_ENVOY_XDS_MODE`:
//!
//! * [`FilesystemLds`] — renders listeners to canonical Envoy JSON and writes
//!   `/envoy-config/lds.json` into the Envoy container (the historical path;
//!   Envoy watches the file via `path_config_source`). O(N) per update.
//!
//! * [`GrpcLds`] — a Delta ADS gRPC server. Renders listeners to typed protobuf,
//!   keeps them in memory, and pushes only the changed resources to Envoy over a
//!   long-lived stream (`api_type: DELTA_GRPC`). O(1) per update, no file I/O.
//!
//! The sandbox data plane (network=none + shared `/sockets` volume + the runner's
//! socat bridge) is identical regardless of backend — only the transport of the
//! Listener config differs.

use std::collections::HashMap;
use std::pin::Pin;
use std::sync::Arc;

use async_trait::async_trait;
use base64::Engine as _;
use bollard::Docker;
use futures::Stream;
use prost::Message;
use serde_json::{json, Value};
use tokio::sync::{watch, Mutex};
use tokio_stream::wrappers::ReceiverStream;
use tonic::{Request, Response, Status, Streaming};
use tracing::{debug, warn};
use uuid::Uuid;

use envoy_types::pb::envoy::service::discovery::v3::{
    aggregated_discovery_service_server::AggregatedDiscoveryService, DeltaDiscoveryRequest,
    DeltaDiscoveryResponse, DiscoveryRequest, DiscoveryResponse, Resource,
};
use envoy_types::pb::google::protobuf::Any;

/// The Envoy type URL for a Listener resource. Delta responses tag each resource
/// with this so Envoy routes it to LDS.
const LISTENER_TYPE_URL: &str = "type.googleapis.com/envoy.config.listener.v3.Listener";

// ---------------------------------------------------------------------------
// Neutral listener description
// ---------------------------------------------------------------------------

/// Which of a sandbox's two listeners this is.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ListenerKind {
    /// TCP-proxy pipe forwarding the runner's gRPC to the orchestrator.
    Grpc,
    /// HTTP connection-manager pipe enforcing the egress allowlist.
    Http,
}

/// Backend-neutral description of a single sandbox listener. Each backend renders
/// this to its own wire form (JSON for filesystem, typed protobuf for gRPC).
#[derive(Debug, Clone)]
pub struct ListenerSpec {
    pub sandbox_id: Uuid,
    pub kind: ListenerKind,
    /// Egress allowlist (only meaningful for [`ListenerKind::Http`]).
    pub allowed_hosts: Vec<String>,
    /// Credential-injection routes (only meaningful for [`ListenerKind::Http`]).
    /// When present, the HTTP listener gains extra virtual hosts / routes that
    /// match plaintext requests from the sandbox, inject the real secret at the
    /// egress boundary, and forward (optionally over TLS) to the true upstream.
    /// The sandbox itself never holds these secrets.
    pub credentials: Vec<EgressCredentialRoute>,
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

/// A single credential-injection route rendered into the HTTP listener.
///
/// Envoy matches `match_host` + `match_prefix` on the sandbox's own listener,
/// removes any sandbox-supplied auth headers, injects the real secret headers,
/// rewrites the authority/path when needed, and forwards via a per-upstream
/// STRICT_DNS cluster (`cluster_name`). Because the cluster endpoint is the real
/// host (resolved independently of request authority), `host_rewrite` only fixes
/// the Host header + TLS SNI.
#[derive(Debug, Clone)]
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
    /// Path prefix the sandbox uses, e.g. `/`, `/mcp/<name>/`, `/git/<slug>/`,
    /// or `/services/<name>/`. When `exact_path` is true this is matched as an
    /// exact path instead of a prefix.
    pub match_prefix: String,
    /// When true, `match_prefix` is matched as an exact path (Envoy `path`)
    /// rather than a prefix (Envoy `prefix`). Used by the external-service path
    /// allowlist so only whitelisted endpoints get credential injection.
    pub exact_path: bool,
    /// Real upstream authority to rewrite the Host header + SNI to.
    pub upstream_host: String,
    /// Real upstream port.
    pub upstream_port: u16,
    /// Prefix to substitute for `match_prefix` on the upstream, e.g. `/` or the
    /// real MCP/git base path.
    pub upstream_prefix: String,
    /// Whether to TLS-originate to the upstream.
    pub upstream_tls: bool,
    /// Name of the per-upstream STRICT_DNS cluster to route to.
    pub cluster_name: String,
    /// Headers to inject (real secret). Overwrites any client-provided value.
    pub inject_headers: Vec<(String, String)>,
    /// Headers to remove before injection. This prevents sandbox-supplied auth
    /// from shadowing or mixing with platform credentials.
    pub remove_headers: Vec<String>,
}

/// Backward-compatible alias while call sites migrate to the unified egress
/// policy vocabulary.
pub type CredentialRoute = EgressCredentialRoute;

/// A per-upstream STRICT_DNS cluster spec, delivered via CDS. One per unique
/// real upstream host so credential routes can `host_rewrite` + forward with the
/// correct TLS SNI. The sandbox never sees this — it only knows the placeholder.
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
pub fn upstream_cluster_name(sandbox_id: &Uuid, upstream_host: &str, upstream_port: u16) -> String {
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
    format!("up_{sandbox_id}_{safe}_{upstream_port}")
}

/// Unified egress policy for one sandbox. This is the Envoy-facing abstraction:
/// allowlist hosts for ordinary egress plus credential-injection routes for any
/// credential family. The routes hold plaintext secrets and must never be
/// persisted or logged.
#[derive(Debug, Clone, Default)]
pub struct SandboxEgressPolicy {
    pub allowlist_hosts: Vec<String>,
    pub credential_routes: Vec<EgressCredentialRoute>,
}

impl SandboxEgressPolicy {
    pub fn clusters(&self, sandbox_id: &Uuid) -> Vec<ClusterSpec> {
        let mut seen = std::collections::HashSet::new();
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

/// Legacy orchestrator-facing description of the real secrets for one sandbox,
/// built from decrypted DB rows. Converted to [`SandboxEgressPolicy`] before it
/// reaches Envoy rendering. This type holds plaintext secrets and must never be
/// persisted or logged.
///
/// All credential families (LLM, MCP, Git, External) are unified as a flat list
/// of [`EgressCredentialRoute`]. Builders emit routes directly; the `kind` field
/// on each route is diagnostic. To add a new credential type, write a builder
/// that returns `Vec<EgressCredentialRoute>` and `extend` this list — no
/// intermediate struct or `to_routes` change needed.
#[derive(Debug, Clone, Default)]
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

    /// Flatten into credential routes, filling each route's `cluster_name` from
    /// its upstream host/port when the builder left it empty. All families
    /// (LLM/MCP/Git/External) already carry fully-formed routes; this is the
    /// single point where the per-sandbox cluster name is resolved.
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

    /// The per-upstream STRICT_DNS clusters this sandbox needs, de-duplicated by
    /// cluster name (multiple MCP servers may share a host).
    pub fn to_clusters(&self, sandbox_id: &Uuid) -> Vec<ClusterSpec> {
        self.to_policy(sandbox_id, vec![]).clusters(sandbox_id)
    }
}

/// Ensure a path prefix is non-empty and starts with `/`.
pub(crate) fn normalize_prefix(p: &str) -> String {
    if p.is_empty() {
        "/".to_string()
    } else if p.starts_with('/') {
        p.to_string()
    } else {
        format!("/{p}")
    }
}

pub(crate) fn normalize_rewrite_base_prefix(p: &str) -> String {
    let mut prefix = normalize_prefix(p);
    if prefix != "/" && !prefix.ends_with('/') {
        prefix.push('/');
    }
    prefix
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

fn route_prefix_rewrite(r: &CredentialRoute) -> String {
    if r.match_host == LLM_EGRESS_HOST {
        normalize_rewrite_base_prefix(&r.upstream_prefix)
    } else {
        r.upstream_prefix.clone()
    }
}

fn auth_headers_to_remove(inject_headers: &[(String, String)]) -> Vec<String> {
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
fn escape_envoy_header_value(raw: &str) -> String {
    raw.replace('%', "%%")
}

impl ListenerSpec {
    /// Resource name Envoy sees, e.g. `"<uuid>_grpc"` / `"<uuid>_http"`.
    /// Kept identical to the historical filesystem naming so a mode switch is
    /// transparent.
    pub fn resource_name(&self) -> String {
        match self.kind {
            ListenerKind::Grpc => format!("{}_grpc", self.sandbox_id),
            ListenerKind::Http => format!("{}_http", self.sandbox_id),
        }
    }
}

// ---------------------------------------------------------------------------
// Trait
// ---------------------------------------------------------------------------

/// Transport-agnostic sink for per-sandbox Envoy Listener config.
#[async_trait]
pub trait LdsBackend: Send + Sync {
    /// Add or replace the given listeners.
    async fn upsert(&self, specs: Vec<ListenerSpec>) -> anyhow::Result<()>;
    /// Remove listeners by resource name (e.g. `"<uuid>_grpc"`).
    async fn remove(&self, names: Vec<String>) -> anyhow::Result<()>;
    /// Replace the entire set (used for init and gRPC re-sync on reconnect).
    async fn replace_all(&self, specs: Vec<ListenerSpec>) -> anyhow::Result<()>;
}

// ===========================================================================
// Filesystem backend
// ===========================================================================

/// LDS backend that writes `/envoy-config/lds.json` into the Envoy container.
/// This is the historical behaviour, relocated behind the trait unchanged.
pub struct FilesystemLds {
    docker: Arc<Docker>,
    container_name: String,
    /// name → rendered listener JSON. Rewritten in full on every change.
    listeners: Mutex<HashMap<String, Value>>,
}

impl FilesystemLds {
    pub fn new(docker: Arc<Docker>, container_name: String) -> Self {
        Self {
            docker,
            container_name,
            listeners: Mutex::new(HashMap::new()),
        }
    }

    /// Serialise the current listener set to `lds.json` and write it atomically.
    async fn write_lds(&self, listeners: &HashMap<String, Value>) -> anyhow::Result<()> {
        let resources: Vec<&Value> = listeners.values().collect();
        let lds = json!({
            "version_info": listeners.len().to_string(),
            "resources": resources,
        });
        let lds_json = serde_json::to_string(&lds)?;
        write_file_in_envoy(
            &self.docker,
            &self.container_name,
            "/envoy-config/lds.json",
            &lds_json,
        )
        .await?;
        debug!(
            listener_count = listeners.len(),
            "FilesystemLds wrote lds.json"
        );
        Ok(())
    }
}

#[async_trait]
impl LdsBackend for FilesystemLds {
    async fn upsert(&self, specs: Vec<ListenerSpec>) -> anyhow::Result<()> {
        let mut listeners = self.listeners.lock().await;
        for spec in specs {
            listeners.insert(spec.resource_name(), render_listener_json(&spec));
        }
        self.write_lds(&listeners).await
    }

    async fn remove(&self, names: Vec<String>) -> anyhow::Result<()> {
        let mut listeners = self.listeners.lock().await;
        for name in names {
            listeners.remove(&name);
        }
        self.write_lds(&listeners).await
    }

    async fn replace_all(&self, specs: Vec<ListenerSpec>) -> anyhow::Result<()> {
        let mut listeners = self.listeners.lock().await;
        listeners.clear();
        for spec in specs {
            listeners.insert(spec.resource_name(), render_listener_json(&spec));
        }
        self.write_lds(&listeners).await
    }
}

// ===========================================================================
// CDS (Cluster Discovery Service) — per-upstream STRICT_DNS clusters
// ===========================================================================

/// Transport-agnostic sink for per-sandbox Envoy Cluster config. Mirrors
/// [`LdsBackend`]; credential-injection routes reference these clusters by name.
#[async_trait]
pub trait CdsBackend: Send + Sync {
    async fn upsert(&self, specs: Vec<ClusterSpec>) -> anyhow::Result<()>;
    /// Remove every cluster whose name starts with `prefix` (used to drop all of
    /// a sandbox's per-upstream clusters without enumerating their hosts).
    async fn remove_by_prefix(&self, prefix: &str) -> anyhow::Result<()>;
    async fn replace_all(&self, specs: Vec<ClusterSpec>) -> anyhow::Result<()>;
}

/// The Envoy type URL for a Cluster resource (Delta CDS).
const CLUSTER_TYPE_URL: &str = "type.googleapis.com/envoy.config.cluster.v3.Cluster";

/// CDS backend that writes `/envoy-config/cds.json` into the Envoy container.
pub struct FilesystemCds {
    docker: Arc<Docker>,
    container_name: String,
    clusters: Mutex<HashMap<String, Value>>,
}

impl FilesystemCds {
    pub fn new(docker: Arc<Docker>, container_name: String) -> Self {
        Self {
            docker,
            container_name,
            clusters: Mutex::new(HashMap::new()),
        }
    }

    async fn write_cds(&self, clusters: &HashMap<String, Value>) -> anyhow::Result<()> {
        let resources: Vec<&Value> = clusters.values().collect();
        let cds = json!({
            "version_info": clusters.len().to_string(),
            "resources": resources,
        });
        let cds_json = serde_json::to_string(&cds)?;
        write_file_in_envoy(
            &self.docker,
            &self.container_name,
            "/envoy-config/cds.json",
            &cds_json,
        )
        .await?;
        debug!(
            cluster_count = clusters.len(),
            "FilesystemCds wrote cds.json"
        );
        Ok(())
    }
}

#[async_trait]
impl CdsBackend for FilesystemCds {
    async fn upsert(&self, specs: Vec<ClusterSpec>) -> anyhow::Result<()> {
        let mut clusters = self.clusters.lock().await;
        for spec in specs {
            clusters.insert(spec.name.clone(), render_cluster_json(&spec));
        }
        self.write_cds(&clusters).await
    }

    async fn remove_by_prefix(&self, prefix: &str) -> anyhow::Result<()> {
        let mut clusters = self.clusters.lock().await;
        clusters.retain(|name, _| !name.starts_with(prefix));
        self.write_cds(&clusters).await
    }

    async fn replace_all(&self, specs: Vec<ClusterSpec>) -> anyhow::Result<()> {
        let mut clusters = self.clusters.lock().await;
        clusters.clear();
        for spec in specs {
            clusters.insert(spec.name.clone(), render_cluster_json(&spec));
        }
        self.write_cds(&clusters).await
    }
}

/// Render a [`ClusterSpec`] to canonical Envoy Cluster JSON: a STRICT_DNS cluster
/// with one endpoint at the real upstream host:port, plus a TLS transport socket
/// (auto-SNI + system CA trust) when the upstream is HTTPS.
fn render_cluster_json(spec: &ClusterSpec) -> Value {
    let mut cluster = json!({
        "@type": CLUSTER_TYPE_URL,
        "name": spec.name,
        "connect_timeout": "10s",
        "type": "STRICT_DNS",
        "lb_policy": "ROUND_ROBIN",
        "dns_lookup_family": "V4_ONLY",
        "load_assignment": {
            "cluster_name": spec.name,
            "endpoints": [{
                "lb_endpoints": [{
                    "endpoint": {
                        "address": {
                            "socket_address": {
                                "address": spec.upstream_host,
                                "port_value": spec.upstream_port
                            }
                        }
                    }
                }]
            }]
        }
    });
    if spec.upstream_tls {
        cluster["transport_socket"] = json!({
            "name": "envoy.transport_sockets.tls",
            "typed_config": {
                "@type": "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.UpstreamTlsContext",
                "sni": spec.upstream_host,
                "common_tls_context": {
                    "validation_context": {
                        "trusted_ca": { "filename": "/etc/ssl/certs/ca-certificates.crt" }
                    }
                }
            }
        });
    }
    cluster
}

// ---------------------------------------------------------------------------
// JSON listener rendering (filesystem backend)
// ---------------------------------------------------------------------------

/// Render a [`ListenerSpec`] to canonical Envoy Listener JSON.
fn render_listener_json(spec: &ListenerSpec) -> Value {
    match spec.kind {
        ListenerKind::Grpc => build_grpc_listener_json(&spec.sandbox_id),
        ListenerKind::Http => {
            build_http_listener_json(&spec.sandbox_id, &spec.allowed_hosts, &spec.credentials)
        }
    }
}

/// TCP proxy listener that forwards gRPC traffic to the orchestrator.
fn build_grpc_listener_json(sandbox_id: &Uuid) -> Value {
    json!({
        "@type": LISTENER_TYPE_URL,
        "name": format!("{sandbox_id}_grpc"),
        "address": {
            "pipe": {
                "path": format!("/sockets/{sandbox_id}/grpc.sock"),
                "mode": 438
            }
        },
        "filter_chains": [{
            "filters": [{
                "name": "envoy.filters.network.tcp_proxy",
                "typed_config": {
                    "@type": "type.googleapis.com/envoy.extensions.filters.network.tcp_proxy.v3.TcpProxy",
                    "stat_prefix": format!("{sandbox_id}_grpc"),
                    "cluster": "orchestrator_grpc"
                }
            }]
        }]
    })
}

/// HTTP connection manager listener with domain-based allowlist.
fn build_http_listener_json(
    sandbox_id: &Uuid,
    allowed_hosts: &[String],
    credentials: &[CredentialRoute],
) -> Value {
    let virtual_hosts = build_virtual_hosts_json(allowed_hosts, credentials);

    json!({
        "@type": LISTENER_TYPE_URL,
        "name": format!("{sandbox_id}_http"),
        "address": {
            "pipe": {
                "path": format!("/sockets/{sandbox_id}/http.sock"),
                "mode": 438
            }
        },
        "filter_chains": [{
            "filters": [{
                "name": "envoy.filters.network.http_connection_manager",
                "typed_config": {
                    "@type": "type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager",
                    "stat_prefix": format!("{sandbox_id}_http"),
                    "http_protocol_options": {
                        "allow_absolute_url": true
                    },
                    "stream_idle_timeout": "0s",
                    "upgrade_configs": [{
                        "upgrade_type": "CONNECT"
                    }],
                    "route_config": {
                        "virtual_hosts": virtual_hosts
                    },
                    "http_filters": [
                        {
                            "name": "envoy.filters.http.dynamic_forward_proxy",
                            "typed_config": {
                                "@type": "type.googleapis.com/envoy.extensions.filters.http.dynamic_forward_proxy.v3.FilterConfig",
                                "dns_cache_config": {
                                    "name": "dynamic_forward_proxy_cache",
                                    "dns_lookup_family": "V4_ONLY"
                                }
                            }
                        },
                        {
                            "name": "envoy.filters.http.router",
                            "typed_config": {
                                "@type": "type.googleapis.com/envoy.extensions.filters.http.router.v3.Router"
                            }
                        }
                    ]
                }
            }]
        }]
    })
}

/// Build the virtual_hosts array for the HTTP listener.
///
/// Order matters — Envoy evaluates virtual hosts by most-specific domain match,
/// and routes within a vhost are first-match. Credential-injection vhosts match
/// the **real** upstream host, so a host with an injected credential gets its own
/// vhost (superseding the plain allowlist entry for that host); unmatched paths
/// on that host still egress plainly.
fn build_virtual_hosts_json(
    allowed_hosts: &[String],
    credentials: &[CredentialRoute],
) -> Vec<Value> {
    let mut vhosts = Vec::new();

    // Credential-injection vhosts, one per real upstream host. Routes that share
    // a host (e.g. several MCP servers on the same host) are grouped and ordered
    // longest-prefix-first so `/sse` wins over `/`.
    for (match_host, routes) in group_credentials_by_host(credentials) {
        let json_routes: Vec<Value> = routes
            .iter()
            .map(|r| {
                let headers: Vec<Value> = r
                    .inject_headers
                    .iter()
                    .map(|(k, v)| {
                        json!({
                            "header": { "key": k, "value": escape_envoy_header_value(v) },
                            "append_action": "OVERWRITE_IF_EXISTS_OR_ADD"
                        })
                    })
                    .collect();
                let headers_to_remove = if r.remove_headers.is_empty() {
                    auth_headers_to_remove(&r.inject_headers)
                } else {
                    r.remove_headers.clone()
                };
                // host_rewrite → real upstream (fixes Host header + TLS SNI);
                // prefix_rewrite → real upstream path; cluster → per-upstream
                // STRICT_DNS cluster whose endpoint is the real host (resolved
                // independently of the placeholder authority).
                let prefix_rewrite = route_prefix_rewrite(r);
                let route_json = if r.exact_path {
                    // Exact path match: no prefix_rewrite (it only applies to
                    // prefix matches). Transparent allowlist routes keep the path
                    // as-is, so this is correct.
                    json!({
                        "cluster": r.cluster_name,
                        "host_rewrite_literal": r.upstream_host,
                        "timeout": "0s"
                    })
                } else {
                    json!({
                        "cluster": r.cluster_name,
                        "host_rewrite_literal": r.upstream_host,
                        "prefix_rewrite": prefix_rewrite,
                        "timeout": "0s"
                    })
                };
                let match_json = if r.exact_path {
                    json!({ "path": r.match_prefix })
                } else {
                    json!({ "prefix": r.match_prefix })
                };
                json!({
                    "match": match_json,
                    "route": route_json,
                    "request_headers_to_add": headers,
                    "request_headers_to_remove": headers_to_remove
                })
            })
            .collect();

        // Domains include the bare host + standard port variants (:80/:443).
        // For transparent egress routes targeting non-standard ports, also add
        // :<port> so Envoy matches the Host header that includes the port.
        let mut domains = vec![
            json!(&match_host),
            json!(format!("{match_host}:80")),
            json!(format!("{match_host}:443")),
        ];
        for r in &routes {
            if r.upstream_port != 80 && r.upstream_port != 443 {
                let with_port = format!("{match_host}:{}", r.upstream_port);
                if !domains.iter().any(|d| d.as_str() == Some(&with_port)) {
                    domains.push(json!(with_port));
                }
            }
        }

        vhosts.push(json!({
            "name": format!("egress_{}", match_host.replace(['.', ':'], "_")),
            "domains": domains,
            "routes": json_routes
        }));
    }

    if !allowed_hosts.is_empty() {
        let mut domains = Vec::new();
        for host in allowed_hosts {
            domains.push(json!(host));
            if !host.contains(':') {
                domains.push(json!(format!("{host}:443")));
                domains.push(json!(format!("{host}:80")));
            }
        }

        vhosts.push(json!({
            "name": "allowed",
            "domains": domains,
            "routes": [
                {
                    "match": { "connect_matcher": {} },
                    "route": {
                        "cluster": "dynamic_forward_proxy",
                        "upgrade_configs": [{
                            "upgrade_type": "CONNECT",
                            "connect_config": {}
                        }]
                    }
                },
                {
                    "match": { "prefix": "/" },
                    "route": { "cluster": "dynamic_forward_proxy" }
                }
            ]
        }));
    }

    // Catch-all: deny everything not explicitly allowed.
    vhosts.push(json!({
        "name": "deny_all",
        "domains": ["*"],
        "routes": [{
            "match": { "prefix": "/" },
            "direct_response": {
                "status": 403,
                "body": { "inline_string": "Host not in allowlist" }
            }
        }]
    }));

    vhosts
}

/// Group credential routes by their placeholder `match_host`, returning a stable
/// (host-sorted) list with routes ordered longest-`match_prefix`-first so more
/// specific prefixes are matched before `/`.
fn group_credentials_by_host(
    credentials: &[CredentialRoute],
) -> Vec<(String, Vec<CredentialRoute>)> {
    let mut by_host: HashMap<String, Vec<CredentialRoute>> = HashMap::new();
    for r in credentials {
        by_host
            .entry(r.match_host.clone())
            .or_default()
            .push(r.clone());
    }
    let mut grouped: Vec<(String, Vec<CredentialRoute>)> = by_host.into_iter().collect();
    grouped.sort_by(|a, b| a.0.cmp(&b.0));
    for (_, routes) in &mut grouped {
        routes.sort_by(|a, b| b.match_prefix.len().cmp(&a.match_prefix.len()));
    }
    grouped
}

// ===========================================================================
// gRPC (Delta ADS) backend
// ===========================================================================

/// A pending change to a specific resource type.
#[derive(Debug, Clone)]
enum Change {
    Upsert(String, Any),
    Remove(String),
}

/// Shared xDS state: the authoritative resource sets (per type URL) + version.
struct XdsState {
    /// type_url → (resource name → encoded resource). Holds both Clusters and
    /// Listeners so the single ADS stream can serve CDS + LDS.
    resources: HashMap<String, HashMap<String, Any>>,
    /// Monotonic version stamped into each Delta response.
    version: u64,
}

impl XdsState {
    fn new() -> Self {
        Self {
            resources: HashMap::new(),
            version: 0,
        }
    }

    fn entry(&mut self, type_url: &str) -> &mut HashMap<String, Any> {
        self.resources.entry(type_url.to_string()).or_default()
    }

    fn snapshot_type(&self, type_url: &str) -> HashMap<String, Any> {
        self.resources.get(type_url).cloned().unwrap_or_default()
    }
}

/// Delta ADS gRPC server. Registered on the orchestrator's existing gRPC server
/// (shares the runner port); Envoy connects and receives incremental CDS + LDS
/// updates on one aggregated stream.
pub struct DeltaXdsServer {
    /// Held as its own `Arc` so the Delta stream task can snapshot it without
    /// borrowing `self` across await points.
    state: Arc<Mutex<XdsState>>,
    /// Bumped on every state change to wake the active Delta stream.
    notify: watch::Sender<u64>,
}

impl DeltaXdsServer {
    pub fn new() -> Arc<Self> {
        let (notify, _rx) = watch::channel(0u64);
        Arc::new(Self {
            state: Arc::new(Mutex::new(XdsState::new())),
            notify,
        })
    }

    /// Apply a batch of changes to one resource type and wake the stream.
    async fn apply(&self, type_url: &str, changes: Vec<Change>) {
        if changes.is_empty() {
            return;
        }
        let mut st = self.state.lock().await;
        st.version += 1;
        {
            let map = st.entry(type_url);
            for change in &changes {
                match change {
                    Change::Upsert(name, any) => {
                        map.insert(name.clone(), any.clone());
                    }
                    Change::Remove(name) => {
                        map.remove(name);
                    }
                }
            }
        }
        let version = st.version;
        drop(st);
        // Ignore send error: no receiver means no Envoy connected yet; the
        // change is already recorded and delivered as initial state on connect.
        let _ = self.notify.send(version);
    }
}

#[async_trait]
impl LdsBackend for GrpcLds {
    async fn upsert(&self, specs: Vec<ListenerSpec>) -> anyhow::Result<()> {
        let mut changes = Vec::with_capacity(specs.len());
        for spec in specs {
            let any = encode_listener_any(&spec)?;
            changes.push(Change::Upsert(spec.resource_name(), any));
        }
        self.server.apply(LISTENER_TYPE_URL, changes).await;
        Ok(())
    }

    async fn remove(&self, names: Vec<String>) -> anyhow::Result<()> {
        let changes = names.into_iter().map(Change::Remove).collect();
        self.server.apply(LISTENER_TYPE_URL, changes).await;
        Ok(())
    }

    async fn replace_all(&self, specs: Vec<ListenerSpec>) -> anyhow::Result<()> {
        // Compute the delta against the current world: upsert everything in
        // `specs`, remove anything no longer present.
        let mut new_names = std::collections::HashSet::new();
        let mut changes = Vec::new();
        for spec in &specs {
            let name = spec.resource_name();
            new_names.insert(name.clone());
            changes.push(Change::Upsert(name, encode_listener_any(spec)?));
        }
        {
            let st = self.server.state.lock().await;
            for existing in st.snapshot_type(LISTENER_TYPE_URL).keys() {
                if !new_names.contains(existing) {
                    changes.push(Change::Remove(existing.clone()));
                }
            }
        }
        self.server.apply(LISTENER_TYPE_URL, changes).await;
        Ok(())
    }
}

/// [`LdsBackend`] wrapper around a shared [`DeltaXdsServer`]. The same
/// `DeltaXdsServer` is also registered as a gRPC service on the orchestrator.
pub struct GrpcLds {
    server: Arc<DeltaXdsServer>,
}

impl GrpcLds {
    pub fn new(server: Arc<DeltaXdsServer>) -> Self {
        Self { server }
    }
}

/// [`CdsBackend`] wrapper around the same shared [`DeltaXdsServer`] — clusters
/// ride the same ADS stream as listeners, under the Cluster type URL.
pub struct GrpcCds {
    server: Arc<DeltaXdsServer>,
}

impl GrpcCds {
    pub fn new(server: Arc<DeltaXdsServer>) -> Self {
        Self { server }
    }
}

#[async_trait]
impl CdsBackend for GrpcCds {
    async fn upsert(&self, specs: Vec<ClusterSpec>) -> anyhow::Result<()> {
        let mut changes = Vec::with_capacity(specs.len());
        for spec in specs {
            changes.push(Change::Upsert(
                spec.name.clone(),
                encode_cluster_any(&spec)?,
            ));
        }
        self.server.apply(CLUSTER_TYPE_URL, changes).await;
        Ok(())
    }

    async fn remove_by_prefix(&self, prefix: &str) -> anyhow::Result<()> {
        let names: Vec<String> = {
            let st = self.server.state.lock().await;
            st.snapshot_type(CLUSTER_TYPE_URL)
                .keys()
                .filter(|n| n.starts_with(prefix))
                .cloned()
                .collect()
        };
        let changes = names.into_iter().map(Change::Remove).collect();
        self.server.apply(CLUSTER_TYPE_URL, changes).await;
        Ok(())
    }

    async fn replace_all(&self, specs: Vec<ClusterSpec>) -> anyhow::Result<()> {
        let mut new_names = std::collections::HashSet::new();
        let mut changes = Vec::new();
        for spec in &specs {
            new_names.insert(spec.name.clone());
            changes.push(Change::Upsert(spec.name.clone(), encode_cluster_any(spec)?));
        }
        {
            let st = self.server.state.lock().await;
            for existing in st.snapshot_type(CLUSTER_TYPE_URL).keys() {
                if !new_names.contains(existing) {
                    changes.push(Change::Remove(existing.clone()));
                }
            }
        }
        self.server.apply(CLUSTER_TYPE_URL, changes).await;
        Ok(())
    }
}

// ---------------------------------------------------------------------------
// Delta ADS service implementation
// ---------------------------------------------------------------------------

type DeltaStream = Pin<Box<dyn Stream<Item = Result<DeltaDiscoveryResponse, Status>> + Send>>;
type SotwStream = Pin<Box<dyn Stream<Item = Result<DiscoveryResponse, Status>> + Send>>;

#[tonic::async_trait]
impl AggregatedDiscoveryService for DeltaXdsServer {
    type StreamAggregatedResourcesStream = SotwStream;

    /// State-of-the-World ADS is not used; the bootstrap requests DELTA_GRPC.
    async fn stream_aggregated_resources(
        &self,
        _request: Request<Streaming<DiscoveryRequest>>,
    ) -> Result<Response<Self::StreamAggregatedResourcesStream>, Status> {
        Err(Status::unimplemented(
            "only DeltaAggregatedResources is supported",
        ))
    }

    type DeltaAggregatedResourcesStream = DeltaStream;

    async fn delta_aggregated_resources(
        &self,
        request: Request<Streaming<DeltaDiscoveryRequest>>,
    ) -> Result<Response<Self::DeltaAggregatedResourcesStream>, Status> {
        // NOTE: this is a `&self` method, but the response stream must outlive
        // the call. The service is registered via `from_arc`, and we snapshot the
        // shared state through a cloned `Arc<Mutex<..>>` handle so the spawned
        // task never borrows `self`.
        let mut inbound = request.into_inner();
        let (tx, rx) = tokio::sync::mpsc::channel::<Result<DeltaDiscoveryResponse, Status>>(16);

        let mut notify_rx = self.notify.subscribe();
        let state_handle = self.state_snapshot_handle();

        // Resource types this aggregated stream serves. Order matters: Clusters
        // (CDS) must be pushed before Listeners (LDS) so a listener's routes
        // never reference a not-yet-known cluster (make-before-break).
        const TYPES: [&str; 2] = [CLUSTER_TYPE_URL, LISTENER_TYPE_URL];

        // Snapshot the initial full state per type to send on connect.
        let (initial, mut last_seen_version) = {
            let st = self.state.lock().await;
            let version = st.version;
            let mut responses = Vec::new();
            for type_url in TYPES {
                let map = st.snapshot_type(type_url);
                let resources: Vec<Resource> = map
                    .iter()
                    .map(|(name, any)| Resource {
                        name: name.clone(),
                        version: version.to_string(),
                        resource: Some(any.clone()),
                        ..Default::default()
                    })
                    .collect();
                responses.push(DeltaDiscoveryResponse {
                    system_version_info: version.to_string(),
                    resources,
                    removed_resources: vec![],
                    type_url: type_url.to_string(),
                    nonce: format!("n-{type_url}-{version}"),
                    ..Default::default()
                });
            }
            (responses, version)
        };

        let task = async move {
            // Send initial state (CDS then LDS).
            for resp in initial {
                if tx.send(Ok(resp)).await.is_err() {
                    return;
                }
            }
            // Track what Envoy currently has per type, to compute removes.
            let mut sent: HashMap<String, std::collections::HashSet<String>> = HashMap::new();
            for type_url in TYPES {
                let snap = state_handle.snapshot_type(type_url).await;
                sent.insert(type_url.to_string(), snap.into_keys().collect());
            }

            loop {
                tokio::select! {
                    // Drain ACK/NACK and subscription messages. We don't act on
                    // subscriptions (we always push the full set) but we must
                    // consume the stream so flow control advances and NACKs are
                    // visible in logs.
                    msg = inbound.message() => {
                        match msg {
                            Ok(Some(req)) => {
                                if let Some(err) = &req.error_detail {
                                    warn!(code = err.code, message = %err.message, "Envoy NACK'd xDS update");
                                }
                            }
                            Err(e) => {
                                debug!(error = %e, "xDS inbound stream error, closing");
                                break;
                            }
                            Ok(None) => {
                                debug!("Envoy closed xDS stream");
                                break;
                            }
                        }
                    }
                    changed = notify_rx.changed() => {
                        if changed.is_err() {
                            break; // server dropped
                        }
                        let version = *notify_rx.borrow_and_update();
                        if version == last_seen_version {
                            continue;
                        }
                        last_seen_version = version;

                        // Emit a per-type delta, CDS before LDS.
                        let mut closed = false;
                        for type_url in TYPES {
                            let snap = state_handle.snapshot_type(type_url).await;
                            let current: std::collections::HashSet<String> =
                                snap.keys().cloned().collect();
                            let resources: Vec<Resource> = snap
                                .iter()
                                .map(|(name, any)| Resource {
                                    name: name.clone(),
                                    version: version.to_string(),
                                    resource: Some(any.clone()),
                                    ..Default::default()
                                })
                                .collect();
                            let prev = sent.entry(type_url.to_string()).or_default();
                            let removed: Vec<String> =
                                prev.difference(&current).cloned().collect();
                            *prev = current;

                            let resp = DeltaDiscoveryResponse {
                                system_version_info: version.to_string(),
                                resources,
                                removed_resources: removed,
                                type_url: type_url.to_string(),
                                nonce: format!("n-{type_url}-{version}"),
                                ..Default::default()
                            };
                            if tx.send(Ok(resp)).await.is_err() {
                                closed = true;
                                break;
                            }
                        }
                        if closed {
                            break;
                        }
                    }
                }
            }
        };
        tokio::spawn(task);

        Ok(Response::new(
            Box::pin(ReceiverStream::new(rx)) as DeltaStream
        ))
    }
}

/// Handle that can snapshot the shared resource maps without holding a lock
/// across await points in the stream task.
struct StateSnapshotHandle {
    state: Arc<Mutex<XdsState>>,
}

impl StateSnapshotHandle {
    async fn snapshot_type(&self, type_url: &str) -> HashMap<String, Any> {
        self.state.lock().await.snapshot_type(type_url)
    }
}

impl DeltaXdsServer {
    /// Build a snapshot handle sharing this server's state Arc.
    ///
    /// The tonic service is registered via `from_arc`, so `self` here is behind
    /// an `Arc`; we expose the inner state as its own `Arc<Mutex<..>>` by holding
    /// it that way from construction.
    fn state_snapshot_handle(&self) -> StateSnapshotHandle {
        StateSnapshotHandle {
            state: self.state.clone(),
        }
    }
}

// ---------------------------------------------------------------------------
// Typed-protobuf listener rendering (gRPC backend)
// ---------------------------------------------------------------------------

/// Encode a [`ListenerSpec`] into a `google.protobuf.Any` wrapping a typed
/// Envoy Listener, for Delta xDS delivery.
fn encode_listener_any(spec: &ListenerSpec) -> anyhow::Result<Any> {
    use envoy_types::pb::envoy::config::listener::v3::Listener;

    let listener: Listener = match spec.kind {
        ListenerKind::Grpc => build_grpc_listener_proto(&spec.sandbox_id),
        ListenerKind::Http => {
            build_http_listener_proto(&spec.sandbox_id, &spec.allowed_hosts, &spec.credentials)
        }
    };
    let mut buf = Vec::new();
    listener.encode(&mut buf)?;
    Ok(Any {
        type_url: LISTENER_TYPE_URL.to_string(),
        value: buf,
    })
}

/// Encode a [`ClusterSpec`] into a `google.protobuf.Any` wrapping a typed Envoy
/// STRICT_DNS Cluster (with optional upstream TLS), for Delta CDS delivery.
fn encode_cluster_any(spec: &ClusterSpec) -> anyhow::Result<Any> {
    use envoy_types::pb::envoy::config::cluster::v3::{cluster, Cluster};
    use envoy_types::pb::envoy::config::core::v3::{
        address, socket_address, Address, SocketAddress,
    };
    use envoy_types::pb::envoy::config::endpoint::v3::{
        lb_endpoint, ClusterLoadAssignment, Endpoint, LbEndpoint, LocalityLbEndpoints,
    };

    let endpoint = LbEndpoint {
        host_identifier: Some(lb_endpoint::HostIdentifier::Endpoint(Endpoint {
            address: Some(Address {
                address: Some(address::Address::SocketAddress(SocketAddress {
                    address: spec.upstream_host.clone(),
                    port_specifier: Some(socket_address::PortSpecifier::PortValue(
                        spec.upstream_port as u32,
                    )),
                    ..Default::default()
                })),
            }),
            ..Default::default()
        })),
        ..Default::default()
    };

    let mut cl = Cluster {
        name: spec.name.clone(),
        connect_timeout: Some(envoy_types::pb::google::protobuf::Duration {
            seconds: 10,
            nanos: 0,
        }),
        cluster_discovery_type: Some(cluster::ClusterDiscoveryType::Type(
            cluster::DiscoveryType::StrictDns as i32,
        )),
        load_assignment: Some(ClusterLoadAssignment {
            cluster_name: spec.name.clone(),
            endpoints: vec![LocalityLbEndpoints {
                lb_endpoints: vec![endpoint],
                ..Default::default()
            }],
            ..Default::default()
        }),
        ..Default::default()
    };

    if spec.upstream_tls {
        use envoy_types::pb::envoy::config::core::v3::{
            data_source, transport_socket, DataSource, TransportSocket,
        };
        use envoy_types::pb::envoy::extensions::transport_sockets::tls::v3::{
            common_tls_context::ValidationContextType, CertificateValidationContext,
            CommonTlsContext, UpstreamTlsContext,
        };

        let tls = UpstreamTlsContext {
            sni: spec.upstream_host.clone(),
            common_tls_context: Some(CommonTlsContext {
                validation_context_type: Some(ValidationContextType::ValidationContext(
                    CertificateValidationContext {
                        trusted_ca: Some(DataSource {
                            specifier: Some(data_source::Specifier::Filename(
                                "/etc/ssl/certs/ca-certificates.crt".to_string(),
                            )),
                            ..Default::default()
                        }),
                        ..Default::default()
                    },
                )),
                ..Default::default()
            }),
            ..Default::default()
        };
        cl.transport_socket = Some(TransportSocket {
            name: "envoy.transport_sockets.tls".to_string(),
            config_type: Some(transport_socket::ConfigType::TypedConfig(pack_any(
                "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.UpstreamTlsContext",
                &tls,
            ))),
        });
    }

    let mut buf = Vec::new();
    cl.encode(&mut buf)?;
    Ok(Any {
        type_url: CLUSTER_TYPE_URL.to_string(),
        value: buf,
    })
}

/// Helper: wrap a prost message in an `Any` with the given type URL.
fn pack_any<M: Message>(type_url: &str, msg: &M) -> Any {
    let mut buf = Vec::new();
    // encode into a Vec never fails for a valid message
    msg.encode(&mut buf).expect("prost encode into Vec");
    Any {
        type_url: type_url.to_string(),
        value: buf,
    }
}

fn build_grpc_listener_proto(
    sandbox_id: &Uuid,
) -> envoy_types::pb::envoy::config::listener::v3::Listener {
    use envoy_types::pb::envoy::config::core::v3::{address, Address, Pipe};
    use envoy_types::pb::envoy::config::listener::v3::{filter, Filter, FilterChain, Listener};
    use envoy_types::pb::envoy::extensions::filters::network::tcp_proxy::v3::{
        tcp_proxy, TcpProxy,
    };

    let tcp_proxy = TcpProxy {
        stat_prefix: format!("{sandbox_id}_grpc"),
        cluster_specifier: Some(tcp_proxy::ClusterSpecifier::Cluster(
            "orchestrator_grpc".to_string(),
        )),
        ..Default::default()
    };

    Listener {
        name: format!("{sandbox_id}_grpc"),
        address: Some(Address {
            address: Some(address::Address::Pipe(Pipe {
                path: format!("/sockets/{sandbox_id}/grpc.sock"),
                mode: 438,
            })),
        }),
        filter_chains: vec![FilterChain {
            filters: vec![Filter {
                name: "envoy.filters.network.tcp_proxy".to_string(),
                config_type: Some(filter::ConfigType::TypedConfig(pack_any(
                    "type.googleapis.com/envoy.extensions.filters.network.tcp_proxy.v3.TcpProxy",
                    &tcp_proxy,
                ))),
            }],
            ..Default::default()
        }],
        ..Default::default()
    }
}

fn build_http_listener_proto(
    sandbox_id: &Uuid,
    allowed_hosts: &[String],
    credentials: &[CredentialRoute],
) -> envoy_types::pb::envoy::config::listener::v3::Listener {
    use envoy_types::pb::envoy::config::core::v3::{address, Address, Http1ProtocolOptions, Pipe};
    use envoy_types::pb::envoy::config::listener::v3::{filter, Filter, FilterChain, Listener};
    use envoy_types::pb::envoy::config::route::v3::RouteConfiguration;
    use envoy_types::pb::envoy::extensions::common::dynamic_forward_proxy::v3::DnsCacheConfig;
    use envoy_types::pb::envoy::extensions::filters::http::dynamic_forward_proxy::v3::{
        filter_config, FilterConfig,
    };
    use envoy_types::pb::envoy::extensions::filters::http::router::v3::Router;
    use envoy_types::pb::envoy::extensions::filters::network::http_connection_manager::v3::{
        http_connection_manager, http_filter, HttpConnectionManager, HttpFilter,
    };

    let dfp_filter = FilterConfig {
        implementation_specifier: Some(filter_config::ImplementationSpecifier::DnsCacheConfig(
            DnsCacheConfig {
                name: "dynamic_forward_proxy_cache".to_string(),
                // dns_lookup_family: V4_ONLY == 0 (default enum value), so we
                // leave it at Default to match the JSON path.
                ..Default::default()
            },
        )),
        ..Default::default()
    };

    let hcm = HttpConnectionManager {
        stat_prefix: format!("{sandbox_id}_http"),
        http_protocol_options: Some(Http1ProtocolOptions {
            allow_absolute_url: Some(envoy_types::pb::google::protobuf::BoolValue { value: true }),
            ..Default::default()
        }),
        upgrade_configs: vec![http_connection_manager::UpgradeConfig {
            upgrade_type: "CONNECT".to_string(),
            ..Default::default()
        }],
        route_specifier: Some(http_connection_manager::RouteSpecifier::RouteConfig(
            RouteConfiguration {
                virtual_hosts: build_virtual_hosts_proto(allowed_hosts, credentials),
                ..Default::default()
            },
        )),
        http_filters: vec![
            HttpFilter {
                name: "envoy.filters.http.dynamic_forward_proxy".to_string(),
                config_type: Some(http_filter::ConfigType::TypedConfig(pack_any(
                    "type.googleapis.com/envoy.extensions.filters.http.dynamic_forward_proxy.v3.FilterConfig",
                    &dfp_filter,
                ))),
                ..Default::default()
            },
            HttpFilter {
                name: "envoy.filters.http.router".to_string(),
                config_type: Some(http_filter::ConfigType::TypedConfig(pack_any(
                    "type.googleapis.com/envoy.extensions.filters.http.router.v3.Router",
                    &Router::default(),
                ))),
                ..Default::default()
            },
        ],
        ..Default::default()
    };

    Listener {
        name: format!("{sandbox_id}_http"),
        address: Some(Address {
            address: Some(address::Address::Pipe(Pipe {
                path: format!("/sockets/{sandbox_id}/http.sock"),
                mode: 438,
            })),
        }),
        filter_chains: vec![FilterChain {
            filters: vec![Filter {
                name: "envoy.filters.network.http_connection_manager".to_string(),
                config_type: Some(filter::ConfigType::TypedConfig(pack_any(
                    "type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager",
                    &hcm,
                ))),
            }],
            ..Default::default()
        }],
        ..Default::default()
    }
}

fn build_virtual_hosts_proto(
    allowed_hosts: &[String],
    credentials: &[CredentialRoute],
) -> Vec<envoy_types::pb::envoy::config::route::v3::VirtualHost> {
    use envoy_types::pb::envoy::config::core::v3::{
        data_source, header_value_option, DataSource, HeaderValue, HeaderValueOption,
    };
    use envoy_types::pb::envoy::config::route::v3::{
        route, route_action, route_match, DirectResponseAction, Route, RouteAction, RouteMatch,
        VirtualHost,
    };

    let mut vhosts = Vec::new();

    // Credential-injection vhosts (mirror of build_virtual_hosts_json).
    for (match_host, routes) in group_credentials_by_host(credentials) {
        let proto_routes: Vec<Route> = routes
            .iter()
            .map(|r| {
                let headers: Vec<HeaderValueOption> = r
                    .inject_headers
                    .iter()
                    .map(|(k, v)| HeaderValueOption {
                        header: Some(HeaderValue {
                            key: k.clone(),
                            value: escape_envoy_header_value(v),
                            ..Default::default()
                        }),
                        append_action:
                            header_value_option::HeaderAppendAction::OverwriteIfExistsOrAdd as i32,
                        ..Default::default()
                    })
                    .collect();
                let headers_to_remove = if r.remove_headers.is_empty() {
                    auth_headers_to_remove(&r.inject_headers)
                } else {
                    r.remove_headers.clone()
                };
                let path_specifier = if r.exact_path {
                    route_match::PathSpecifier::Path(r.match_prefix.clone())
                } else {
                    route_match::PathSpecifier::Prefix(r.match_prefix.clone())
                };
                // Exact path match: no prefix_rewrite (only valid for prefix
                // matches). Transparent allowlist routes keep the path as-is.
                let prefix_rewrite = if r.exact_path {
                    String::new()
                } else {
                    route_prefix_rewrite(r)
                };
                Route {
                    r#match: Some(RouteMatch {
                        path_specifier: Some(path_specifier),
                        ..Default::default()
                    }),
                    action: Some(route::Action::Route(RouteAction {
                        cluster_specifier: Some(route_action::ClusterSpecifier::Cluster(
                            r.cluster_name.clone(),
                        )),
                        // host_rewrite → real upstream (Host header + TLS SNI);
                        // prefix_rewrite → real upstream path.
                        host_rewrite_specifier: Some(
                            route_action::HostRewriteSpecifier::HostRewriteLiteral(
                                r.upstream_host.clone(),
                            ),
                        ),
                        prefix_rewrite,
                        ..Default::default()
                    })),
                    request_headers_to_add: headers,
                    request_headers_to_remove: headers_to_remove,
                    ..Default::default()
                }
            })
            .collect();

        let mut domains = vec![
            match_host.clone(),
            format!("{match_host}:80"),
            format!("{match_host}:443"),
        ];
        for r in &routes {
            if r.upstream_port != 80 && r.upstream_port != 443 {
                let with_port = format!("{match_host}:{}", r.upstream_port);
                if !domains.contains(&with_port) {
                    domains.push(with_port);
                }
            }
        }

        vhosts.push(VirtualHost {
            name: format!("egress_{}", match_host.replace(['.', ':'], "_")),
            domains,
            routes: proto_routes,
            ..Default::default()
        });
    }

    if !allowed_hosts.is_empty() {
        let mut domains = Vec::new();
        for host in allowed_hosts {
            domains.push(host.clone());
            if !host.contains(':') {
                domains.push(format!("{host}:443"));
                domains.push(format!("{host}:80"));
            }
        }

        // CONNECT route → dynamic_forward_proxy with CONNECT upgrade.
        let connect_route = Route {
            r#match: Some(RouteMatch {
                path_specifier: Some(route_match::PathSpecifier::ConnectMatcher(
                    route_match::ConnectMatcher {},
                )),
                ..Default::default()
            }),
            action: Some(route::Action::Route(RouteAction {
                cluster_specifier: Some(route_action::ClusterSpecifier::Cluster(
                    "dynamic_forward_proxy".to_string(),
                )),
                upgrade_configs: vec![route_action::UpgradeConfig {
                    upgrade_type: "CONNECT".to_string(),
                    connect_config: Some(route_action::upgrade_config::ConnectConfig::default()),
                    ..Default::default()
                }],
                ..Default::default()
            })),
            ..Default::default()
        };

        // Plain prefix "/" route → dynamic_forward_proxy.
        let prefix_route = Route {
            r#match: Some(RouteMatch {
                path_specifier: Some(route_match::PathSpecifier::Prefix("/".to_string())),
                ..Default::default()
            }),
            action: Some(route::Action::Route(RouteAction {
                cluster_specifier: Some(route_action::ClusterSpecifier::Cluster(
                    "dynamic_forward_proxy".to_string(),
                )),
                ..Default::default()
            })),
            ..Default::default()
        };

        vhosts.push(VirtualHost {
            name: "allowed".to_string(),
            domains,
            routes: vec![connect_route, prefix_route],
            ..Default::default()
        });
    }

    // Catch-all: deny everything not explicitly allowed with a 403.
    vhosts.push(VirtualHost {
        name: "deny_all".to_string(),
        domains: vec!["*".to_string()],
        routes: vec![Route {
            r#match: Some(RouteMatch {
                path_specifier: Some(route_match::PathSpecifier::Prefix("/".to_string())),
                ..Default::default()
            }),
            action: Some(route::Action::DirectResponse(DirectResponseAction {
                status: 403,
                body: Some(DataSource {
                    specifier: Some(data_source::Specifier::InlineString(
                        "Host not in allowlist".to_string(),
                    )),
                    ..Default::default()
                }),
            })),
            ..Default::default()
        }],
        ..Default::default()
    });

    vhosts
}

// ---------------------------------------------------------------------------
// Shared Envoy container file write (used by FilesystemLds + EnvoyManager)
// ---------------------------------------------------------------------------

/// Execute a shell command inside the Envoy container, returning combined output.
pub async fn exec_in_envoy(
    docker: &Docker,
    container_name: &str,
    cmd: &str,
) -> anyhow::Result<String> {
    use bollard::exec::{CreateExecOptions, StartExecResults};
    use futures::StreamExt;

    let exec = docker
        .create_exec(
            container_name,
            CreateExecOptions {
                cmd: Some(vec!["sh".to_string(), "-c".to_string(), cmd.to_string()]),
                attach_stdout: Some(true),
                attach_stderr: Some(true),
                ..Default::default()
            },
        )
        .await?;

    let mut output = String::new();
    if let StartExecResults::Attached {
        output: mut stream, ..
    } = docker.start_exec(&exec.id, None).await?
    {
        while let Some(msg) = stream.next().await {
            let msg = msg?;
            output.push_str(&msg.to_string());
        }
    }

    let inspect = docker.inspect_exec(&exec.id).await?;
    match inspect.exit_code {
        Some(0) => {}
        Some(code) => {
            anyhow::bail!("Envoy container command failed with exit code {code}: {output}");
        }
        None => {
            anyhow::bail!("Envoy container command finished without an exit code: {output}");
        }
    }

    Ok(output)
}

/// Write a file inside the Envoy container atomically (tmp + mv) via base64.
///
/// After the atomic rename, we `touch` the parent directory to guarantee that
/// Envoy's `watched_directory` inotify picks up the change. On Docker bind
/// mounts the `mv` (rename) event is frequently invisible to the watcher
/// inside the container, but a `touch` on the directory itself always fires a
/// directory-level `IN_ATTRIB` that Envoy's `FilesystemSubscriptionImpl` uses
/// as a rescan trigger.
pub async fn write_file_in_envoy(
    docker: &Docker,
    container_name: &str,
    path: &str,
    content: &str,
) -> anyhow::Result<()> {
    let encoded = base64::engine::general_purpose::STANDARD.encode(content.as_bytes());
    let tmp_path = format!("{path}.tmp");
    // Derive the parent directory for the post-write touch.
    let parent = std::path::Path::new(path)
        .parent()
        .and_then(|p| p.to_str())
        .unwrap_or("/envoy-config");
    let cmd = format!(
        "printf %s '{}' | base64 -d > '{}' && mv '{}' '{}' && touch '{}'",
        encoded, tmp_path, tmp_path, path, parent
    );
    exec_in_envoy(docker, container_name, &cmd).await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use prost::Message;

    fn spec(kind: ListenerKind, hosts: &[&str]) -> ListenerSpec {
        ListenerSpec {
            sandbox_id: Uuid::nil(),
            kind,
            allowed_hosts: hosts.iter().map(|s| s.to_string()).collect(),
            credentials: vec![],
        }
    }

    fn spec_with_creds(
        kind: ListenerKind,
        hosts: &[&str],
        creds: Vec<CredentialRoute>,
    ) -> ListenerSpec {
        ListenerSpec {
            sandbox_id: Uuid::nil(),
            kind,
            allowed_hosts: hosts.iter().map(|s| s.to_string()).collect(),
            credentials: creds,
        }
    }

    fn llm_route() -> CredentialRoute {
        CredentialRoute {
            id: "llm".to_string(),
            kind: EgressKind::Llm,
            exposure: EgressExposure::Placeholder,
            match_host: LLM_EGRESS_HOST.to_string(),
            match_prefix: "/".to_string(),
            exact_path: false,
            upstream_host: "llm.internal.example.com".to_string(),
            upstream_port: 443,
            upstream_prefix: "/v1".to_string(),
            upstream_tls: true,
            cluster_name: "up_test_llm".to_string(),
            inject_headers: vec![("authorization".to_string(), "Bearer sk-secret".to_string())],
            remove_headers: vec![],
        }
    }

    fn mcp_route(name: &str) -> CredentialRoute {
        CredentialRoute {
            id: format!("mcp:{name}"),
            kind: EgressKind::Mcp,
            exposure: EgressExposure::Placeholder,
            match_host: MCP_EGRESS_HOST.to_string(),
            match_prefix: format!("/mcp/{name}/"),
            exact_path: false,
            upstream_host: "mcp.example.com".to_string(),
            upstream_port: 443,
            upstream_prefix: "/sse".to_string(),
            upstream_tls: true,
            cluster_name: "up_test_mcp".to_string(),
            inject_headers: vec![("authorization".to_string(), "Bearer tok".to_string())],
            remove_headers: vec![],
        }
    }

    #[test]
    fn resource_names_match_historical_scheme() {
        assert_eq!(
            spec(ListenerKind::Grpc, &[]).resource_name(),
            "00000000-0000-0000-0000-000000000000_grpc"
        );
        assert_eq!(
            spec(ListenerKind::Http, &[]).resource_name(),
            "00000000-0000-0000-0000-000000000000_http"
        );
    }

    #[test]
    fn grpc_listener_encodes_to_listener_any() {
        let any = encode_listener_any(&spec(ListenerKind::Grpc, &[])).unwrap();
        assert_eq!(any.type_url, LISTENER_TYPE_URL);
        // Round-trips as a Listener with the expected name + a pipe address.
        use envoy_types::pb::envoy::config::listener::v3::Listener;
        let l = Listener::decode(any.value.as_slice()).unwrap();
        assert_eq!(l.name, "00000000-0000-0000-0000-000000000000_grpc");
        assert_eq!(l.filter_chains.len(), 1);
        assert!(l.address.is_some());
    }

    #[test]
    fn http_listener_encodes_with_allowlist_and_deny_all() {
        let any = encode_listener_any(&spec(ListenerKind::Http, &["api.example.com"])).unwrap();
        assert_eq!(any.type_url, LISTENER_TYPE_URL);
        use envoy_types::pb::envoy::config::listener::v3::Listener;
        let l = Listener::decode(any.value.as_slice()).unwrap();
        assert_eq!(l.name, "00000000-0000-0000-0000-000000000000_http");
        assert_eq!(l.filter_chains.len(), 1);
    }

    #[test]
    fn json_and_proto_agree_on_listener_name() {
        // The filesystem (JSON) and gRPC (proto) backends must name resources
        // identically so a mode switch is transparent to Envoy.
        let http = spec(ListenerKind::Http, &["a.com"]);
        let json = render_listener_json(&http);
        assert_eq!(json["name"], "00000000-0000-0000-0000-000000000000_http");
        assert_eq!(json["@type"], LISTENER_TYPE_URL);
    }

    #[test]
    fn credentials_produce_matching_routes_and_clusters() {
        // Full-shape check: placeholder-host routes host_rewrite to the real
        // upstream and reference a per-upstream STRICT_DNS cluster that CDS
        // delivers. Validated live against Envoy; this locks the wire shape.
        let creds = SandboxCredentials {
            routes: vec![
                EgressCredentialRoute {
                    id: "llm".to_string(),
                    kind: EgressKind::Llm,
                    exposure: EgressExposure::Placeholder,
                    match_host: LLM_EGRESS_HOST.to_string(),
                    match_prefix: "/".to_string(),
                    exact_path: false,
                    upstream_host: "llm.internal.example.com".to_string(),
                    upstream_port: 443,
                    upstream_prefix: "/v1/".to_string(),
                    upstream_tls: true,
                    cluster_name: String::new(),
                    inject_headers: vec![(
                        "authorization".to_string(),
                        "Bearer sk".to_string(),
                    )],
                    remove_headers: vec![],
                },
                EgressCredentialRoute {
                    id: "mcp:gitlab".to_string(),
                    kind: EgressKind::Mcp,
                    exposure: EgressExposure::Placeholder,
                    match_host: MCP_EGRESS_HOST.to_string(),
                    match_prefix: "/mcp/gitlab/".to_string(),
                    exact_path: false,
                    upstream_host: "mcp.example.com".to_string(),
                    upstream_port: 8443,
                    upstream_prefix: "/sse".to_string(),
                    upstream_tls: true,
                    cluster_name: String::new(),
                    inject_headers: vec![("authorization".to_string(), "Bearer t".to_string())],
                    remove_headers: vec![],
                },
            ],
        };
        let sid = Uuid::nil();
        let routes = creds.to_routes(&sid);
        let clusters = creds.to_clusters(&sid);

        // Every route's cluster_name must exist in the cluster set.
        let cluster_names: std::collections::HashSet<&str> =
            clusters.iter().map(|c| c.name.as_str()).collect();
        for r in &routes {
            assert!(
                cluster_names.contains(r.cluster_name.as_str()),
                "route cluster {} missing from CDS",
                r.cluster_name
            );
        }

        // LLM route: placeholder match host, host_rewrite to real upstream.
        let llm = routes
            .iter()
            .find(|r| r.match_host == LLM_EGRESS_HOST)
            .unwrap();
        assert_eq!(llm.match_prefix, "/");
        assert_eq!(llm.upstream_host, "llm.internal.example.com");
        assert_eq!(llm.upstream_prefix, "/v1/");

        // MCP route scoped by name; cluster carries the non-443 port.
        let mcp = routes
            .iter()
            .find(|r| r.match_host == MCP_EGRESS_HOST)
            .unwrap();
        assert_eq!(mcp.match_prefix, "/mcp/gitlab/");
        assert_eq!(mcp.upstream_prefix, "/sse");
        let mcp_cluster = clusters
            .iter()
            .find(|c| c.name == mcp.cluster_name)
            .unwrap();
        assert_eq!(mcp_cluster.upstream_port, 8443);
        assert!(mcp_cluster.upstream_tls);

        // The TLS cluster JSON carries SNI + CA trust; the listener JSON renders.
        let cj = render_cluster_json(mcp_cluster);
        assert_eq!(cj["type"], "STRICT_DNS");
        assert_eq!(
            cj["transport_socket"]["typed_config"]["sni"],
            "mcp.example.com"
        );
    }

    #[test]
    fn external_placeholder_and_transparent_routes_share_one_cluster() {
        // An external service emits two routes: a placeholder-host route
        // (external-egress.internal/services/<name>/) and a transparent route on
        // the real host so a skill can call http://crm.example.com/api/ directly.
        // Both target the same upstream, so CDS must dedupe to a single cluster.
        let sid = Uuid::nil();
        let cluster = upstream_cluster_name(&sid, "crm.example.com", 443);
        let creds = SandboxCredentials {
            routes: vec![
                EgressCredentialRoute {
                    id: "external:crm".to_string(),
                    kind: EgressKind::External,
                    exposure: EgressExposure::Placeholder,
                    match_host: EXTERNAL_EGRESS_HOST.to_string(),
                    match_prefix: "/services/crm/".to_string(),
                    exact_path: false,
                    upstream_host: "crm.example.com".to_string(),
                    upstream_port: 443,
                    upstream_prefix: "/api/".to_string(),
                    upstream_tls: true,
                    cluster_name: String::new(),
                    inject_headers: vec![("cookie".to_string(), "SESSION=abc".to_string())],
                    remove_headers: vec!["cookie".to_string()],
                },
                EgressCredentialRoute {
                    id: "external-direct:crm".to_string(),
                    kind: EgressKind::External,
                    exposure: EgressExposure::Transparent,
                    match_host: "crm.example.com".to_string(),
                    match_prefix: "/api/".to_string(),
                    exact_path: false,
                    upstream_host: "crm.example.com".to_string(),
                    upstream_port: 443,
                    upstream_prefix: "/api/".to_string(),
                    upstream_tls: true,
                    cluster_name: String::new(),
                    inject_headers: vec![("cookie".to_string(), "SESSION=abc".to_string())],
                    remove_headers: vec!["cookie".to_string()],
                },
            ],
        };

        let routes = creds.to_routes(&sid);
        let clusters = creds.to_clusters(&sid);

        // Two routes, one deduped cluster.
        assert_eq!(routes.len(), 2);
        assert_eq!(clusters.len(), 1);
        assert_eq!(clusters[0].name, cluster);

        // Transparent route matches the real host and rewrites are no-ops.
        let direct = routes
            .iter()
            .find(|r| r.match_host == "crm.example.com")
            .unwrap();
        assert_eq!(direct.exposure, EgressExposure::Transparent);
        assert_eq!(direct.match_prefix, "/api/");
        assert_eq!(direct.upstream_host, "crm.example.com");
        assert_eq!(direct.upstream_prefix, "/api/");
        assert!(direct.upstream_tls);
        assert_eq!(direct.cluster_name, cluster);

        // The transparent host gets its own credential vhost keyed on the real
        // host. In production the real host is NOT added to allowed_hosts (see
        // merge_egress_hosts), so no vhost collides on that exact domain. Build
        // the listener the way it is actually assembled — transparent routes +
        // an allowlist that does NOT contain the transparent host — and assert
        // every exact domain is unique across vhosts (Envoy rejects duplicates).
        let vh = build_virtual_hosts_json(&["other.example.com".to_string()], &routes);
        assert!(vh.iter().any(|v| v["name"] == "egress_crm_example_com"));

        let mut seen = std::collections::HashSet::new();
        for v in &vh {
            for d in v["domains"].as_array().unwrap() {
                let domain = d.as_str().unwrap().to_string();
                if domain == "*" {
                    continue;
                }
                assert!(
                    seen.insert(domain.clone()),
                    "duplicate exact domain across vhosts: {domain}"
                );
            }
        }
    }

    #[test]
    fn same_host_multiple_base_paths_share_one_vhost() {
        // Two external services on the same host but different base paths
        // (e.g. crm.example.com/api/ and crm.example.com/auth/). Their
        // transparent routes must land in ONE vhost for that host, ordered
        // longest-prefix-first, with the host's exact domain declared once.
        let sid = Uuid::nil();
        let mk = |id: &str, prefix: &str| EgressCredentialRoute {
            id: id.to_string(),
            kind: EgressKind::External,
            exposure: EgressExposure::Transparent,
            match_host: "crm.example.com".to_string(),
            match_prefix: prefix.to_string(),
            exact_path: false,
            upstream_host: "crm.example.com".to_string(),
            upstream_port: 443,
            upstream_prefix: prefix.to_string(),
            upstream_tls: true,
            cluster_name: String::new(),
            inject_headers: vec![("cookie".to_string(), "SESSION=abc".to_string())],
            remove_headers: vec!["cookie".to_string()],
        };
        let creds = SandboxCredentials {
            routes: vec![
                mk("external-direct:crm-api", "/api/"),
                mk("external-direct:crm-auth", "/auth/api/"),
            ],
        };
        let routes = creds.to_routes(&sid);
        let vh = build_virtual_hosts_json(&[], &routes);

        // Exactly one credential vhost for the host, holding both routes.
        let host_vhosts: Vec<_> = vh
            .iter()
            .filter(|v| v["name"] == "egress_crm_example_com")
            .collect();
        assert_eq!(host_vhosts.len(), 1);
        let vhost_routes = host_vhosts[0]["routes"].as_array().unwrap();
        assert_eq!(vhost_routes.len(), 2);
        // Longest prefix first: /auth/api/ (10) before /api/ (5).
        assert_eq!(vhost_routes[0]["match"]["prefix"], "/auth/api/");
        assert_eq!(vhost_routes[1]["match"]["prefix"], "/api/");

        // Exact domain declared once across all vhosts.
        let mut seen = std::collections::HashSet::new();
        for v in &vh {
            for d in v["domains"].as_array().unwrap() {
                let domain = d.as_str().unwrap().to_string();
                if domain == "*" {
                    continue;
                }
                assert!(
                    seen.insert(domain.clone()),
                    "duplicate exact domain: {domain}"
                );
            }
        }
    }

    #[test]
    fn exact_path_route_renders_path_match_without_prefix_rewrite() {
        // A transparent allowlist route with exact_path=true must render an
        // Envoy `path` match (not `prefix`) and must NOT emit prefix_rewrite
        // (which is only valid for prefix matches). A prefix route (trailing /)
        // renders `prefix` + prefix_rewrite.
        let exact = EgressCredentialRoute {
            id: "external-direct:crm:0".to_string(),
            kind: EgressKind::External,
            exposure: EgressExposure::Transparent,
            match_host: "crm.example.com".to_string(),
            match_prefix: "/api/warning/getWarningDetailById".to_string(),
            exact_path: true,
            upstream_host: "crm.example.com".to_string(),
            upstream_port: 443,
            upstream_prefix: "/api/warning/getWarningDetailById".to_string(),
            upstream_tls: true,
            cluster_name: "up_test_crm".to_string(),
            inject_headers: vec![("cookie".to_string(), "SESSION=abc".to_string())],
            remove_headers: vec!["cookie".to_string()],
        };
        let prefix = EgressCredentialRoute {
            id: "external-direct:crm:1".to_string(),
            match_prefix: "/api/work/".to_string(),
            upstream_prefix: "/api/work/".to_string(),
            exact_path: false,
            ..exact.clone()
        };

        let vh = build_virtual_hosts_json(&[], &[exact, prefix]);
        let routes = vh
            .iter()
            .find(|v| v["name"] == "egress_crm_example_com")
            .unwrap()["routes"]
            .as_array()
            .unwrap();

        let exact_route = routes
            .iter()
            .find(|r| r["match"].get("path").is_some())
            .unwrap();
        assert_eq!(
            exact_route["match"]["path"],
            "/api/warning/getWarningDetailById"
        );
        // Exact routes must not carry a prefix_rewrite.
        assert!(exact_route["route"].get("prefix_rewrite").is_none());

        let prefix_route = routes
            .iter()
            .find(|r| r["match"].get("prefix").is_some())
            .unwrap();
        assert_eq!(prefix_route["match"]["prefix"], "/api/work/");
        assert_eq!(prefix_route["route"]["prefix_rewrite"], "/api/work/");
    }

    #[test]
    fn http_vhosts_have_deny_all_last() {
        // With no allowlist, only the catch-all deny_all vhost exists.
        let vh = build_virtual_hosts_json(&[], &[]);
        assert_eq!(vh.len(), 1);
        assert_eq!(vh[0]["name"], "deny_all");
        // With an allowlist, `allowed` precedes `deny_all`.
        let vh = build_virtual_hosts_json(&["a.com".to_string()], &[]);
        assert_eq!(vh.len(), 2);
        assert_eq!(vh[0]["name"], "allowed");
        assert_eq!(vh[1]["name"], "deny_all");
    }

    #[test]
    fn credential_vhosts_precede_allowlist_and_inject_headers() {
        let creds = vec![llm_route(), mcp_route("gitlab"), mcp_route("jira")];
        let vh = build_virtual_hosts_json(&["a.com".to_string()], &creds);
        // Placeholder-host vhosts, then allowlist, then deny_all.
        assert_eq!(vh[0]["name"], "egress_llm-egress_internal");
        assert_eq!(vh[1]["name"], "egress_mcp-egress_internal");
        assert_eq!(vh[2]["name"], "allowed");
        assert_eq!(vh[3]["name"], "deny_all");

        // LLM route injects Bearer + rewrites host/prefix to the real upstream,
        // routing to its dedicated cluster.
        let llm_routes = vh[0]["routes"].as_array().unwrap();
        let inj = &llm_routes[0]["request_headers_to_add"][0];
        assert_eq!(inj["header"]["key"], "authorization");
        assert_eq!(inj["header"]["value"], "Bearer sk-secret");
        assert_eq!(inj["append_action"], "OVERWRITE_IF_EXISTS_OR_ADD");
        assert_eq!(
            llm_routes[0]["request_headers_to_remove"]
                .as_array()
                .unwrap(),
            &vec![
                json!("x-api-key"),
                json!("api-key"),
                json!("x-goog-api-key")
            ]
        );
        assert_eq!(
            llm_routes[0]["route"]["host_rewrite_literal"],
            "llm.internal.example.com"
        );
        assert_eq!(llm_routes[0]["route"]["prefix_rewrite"], "/v1/");
        assert_eq!(llm_routes[0]["route"]["cluster"], "up_test_llm");

        // MCP vhost: two servers on the placeholder host, each its own prefix.
        let mcp_routes = vh[1]["routes"].as_array().unwrap();
        assert_eq!(mcp_routes.len(), 2);
        assert!(mcp_routes[0]["match"]["prefix"]
            .as_str()
            .unwrap()
            .starts_with("/mcp/"));
        assert_eq!(mcp_routes[0]["route"]["prefix_rewrite"], "/sse");
    }

    #[test]
    fn json_and_proto_agree_on_credential_injection() {
        let creds = vec![llm_route(), mcp_route("gitlab")];
        let http = spec_with_creds(ListenerKind::Http, &["a.com"], creds);

        // JSON path: credential vhosts present.
        let json = render_listener_json(&http);
        let vhosts = json["filter_chains"][0]["filters"][0]["typed_config"]["route_config"]
            ["virtual_hosts"]
            .as_array()
            .unwrap();
        let json_names: Vec<&str> = vhosts.iter().map(|v| v["name"].as_str().unwrap()).collect();

        // Proto path: decode and compare vhost names.
        let any = encode_listener_any(&http).unwrap();
        use envoy_types::pb::envoy::config::listener::v3::Listener;
        use envoy_types::pb::envoy::extensions::filters::network::http_connection_manager::v3::{
            http_connection_manager, HttpConnectionManager,
        };
        let l = Listener::decode(any.value.as_slice()).unwrap();
        let hcm_any = match &l.filter_chains[0].filters[0].config_type {
            Some(
                envoy_types::pb::envoy::config::listener::v3::filter::ConfigType::TypedConfig(a),
            ) => a,
            _ => panic!("expected typed config"),
        };
        let hcm = HttpConnectionManager::decode(hcm_any.value.as_slice()).unwrap();
        let rc = match hcm.route_specifier {
            Some(http_connection_manager::RouteSpecifier::RouteConfig(rc)) => rc,
            _ => panic!("expected route config"),
        };
        let proto_names: Vec<String> = rc.virtual_hosts.iter().map(|v| v.name.clone()).collect();

        assert_eq!(
            json_names,
            proto_names.iter().map(|s| s.as_str()).collect::<Vec<_>>()
        );
        assert_eq!(json_names[0], "egress_llm-egress_internal");
    }

    #[test]
    fn escape_envoy_header_value_escapes_percent() {
        assert_eq!(escape_envoy_header_value("plain"), "plain");
        assert_eq!(escape_envoy_header_value("a%7Cb"), "a%%7Cb");
        assert_eq!(
            escape_envoy_header_value("sid=x%3Dy%7Cz"),
            "sid=x%%3Dy%%7Cz"
        );
        assert_eq!(escape_envoy_header_value("100%"), "100%%");
        assert_eq!(escape_envoy_header_value("%%already"), "%%%%already");
    }

    #[test]
    fn credential_header_values_with_percent_are_escaped_in_json() {
        let cred = CredentialRoute {
            id: "test".to_string(),
            kind: EgressKind::External,
            exposure: EgressExposure::Transparent,
            match_host: "llm-egress.internal".to_string(),
            match_prefix: "/v1/".to_string(),
            upstream_host: "api.example.com".to_string(),
            upstream_port: 443,
            upstream_prefix: "/v1/".to_string(),
            upstream_tls: true,
            cluster_name: "up_test".to_string(),
            exact_path: false,
            inject_headers: vec![(
                "cookie".to_string(),
                "session=abc%7Cdef%3Dxyz".to_string(),
            )],
            remove_headers: vec![],
        };
        let vh = build_virtual_hosts_json(&[], &[cred]);
        let header_val = vh[0]["routes"][0]["request_headers_to_add"][0]["header"]["value"]
            .as_str()
            .unwrap();
        // % must be doubled so Envoy treats them as literal
        assert_eq!(header_val, "session=abc%%7Cdef%%3Dxyz");
    }
}
