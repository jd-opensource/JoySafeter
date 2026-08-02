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
use std::fmt;
use std::net::IpAddr;
use std::pin::Pin;
use std::str::FromStr;
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

use crate::egress::policy::normalize_rewrite_base_prefix;
#[cfg(test)]
use crate::egress::policy::{
    upstream_cluster_name, EgressExposure, EgressKind, SandboxCredentials, EXTERNAL_EGRESS_HOST,
    MCP_EGRESS_HOST,
};
use crate::egress::policy::{ClusterSpec, CredentialRoute, EgressCredentialRoute, LLM_EGRESS_HOST};

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
    /// Resolved addresses matching these ranges are removed from dynamic
    /// forward proxy DNS results before a connection is attempted.
    pub denied_cidrs: Vec<DeniedCidr>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeniedCidr {
    pub address_prefix: String,
    pub prefix_len: u32,
}

impl fmt::Display for DeniedCidr {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}/{}", self.address_prefix, self.prefix_len)
    }
}

impl FromStr for DeniedCidr {
    type Err = anyhow::Error;

    fn from_str(raw: &str) -> Result<Self, Self::Err> {
        let (address, prefix) = raw
            .trim()
            .split_once('/')
            .ok_or_else(|| anyhow::anyhow!("egress denied CIDR must include a prefix: {raw}"))?;
        let address: IpAddr = address
            .parse()
            .map_err(|error| anyhow::anyhow!("invalid egress denied CIDR {raw}: {error}"))?;
        let prefix_len: u32 = prefix
            .parse()
            .map_err(|error| anyhow::anyhow!("invalid egress denied CIDR {raw}: {error}"))?;
        let max_prefix = if address.is_ipv4() { 32 } else { 128 };
        if prefix_len > max_prefix {
            anyhow::bail!("invalid egress denied CIDR {raw}: prefix exceeds {max_prefix}");
        }
        Ok(Self {
            address_prefix: address.to_string(),
            prefix_len,
        })
    }
}

pub(crate) fn dynamic_forward_proxy_dns_cache_json(denied_cidrs: &[DeniedCidr]) -> Value {
    json!({
        "name": "dynamic_forward_proxy_cache",
        "dns_lookup_family": "V4_ONLY",
        "resolved_address_filter": {
            "ranges": denied_cidrs.iter().map(|cidr| json!({
                "address_prefix": cidr.address_prefix,
                "prefix_len": cidr.prefix_len
            })).collect::<Vec<_>>()
        }
    })
}

const CREDENTIAL_AUTH_HEADERS: &[&str] =
    &["authorization", "x-api-key", "api-key", "x-goog-api-key"];

fn route_prefix_rewrite(r: &CredentialRoute) -> String {
    if r.match_host == LLM_EGRESS_HOST {
        normalize_rewrite_base_prefix(&r.upstream_prefix)
    } else {
        r.upstream_prefix.clone()
    }
}

fn auth_headers_to_remove(inject_header: &str) -> Vec<String> {
    CREDENTIAL_AUTH_HEADERS
        .iter()
        .filter(|candidate| !inject_header.eq_ignore_ascii_case(candidate))
        .map(|header| header.to_string())
        .collect()
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
/// (explicit SNI + system CA trust + exact DNS SAN validation) when the upstream
/// is HTTPS.
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
                        "trusted_ca": { "filename": "/etc/ssl/certs/ca-certificates.crt" },
                        "match_typed_subject_alt_names": [{
                            "san_type": "DNS",
                            "matcher": { "exact": spec.upstream_host }
                        }]
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
        ListenerKind::Http => build_http_listener_json(
            &spec.sandbox_id,
            &spec.allowed_hosts,
            &spec.credentials,
            &spec.denied_cidrs,
        ),
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
    denied_cidrs: &[DeniedCidr],
) -> Value {
    let virtual_hosts = build_virtual_hosts_json(sandbox_id, allowed_hosts, credentials);

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
                                "dns_cache_config": dynamic_forward_proxy_dns_cache_json(denied_cidrs)
                            }
                        },
                        {
                            // Per-request credential resolution. The filter is a
                            // no-op unless a route enables it (per-route
                            // context_extensions); the orchestrator's ext_authz
                            // service resolves the credential and returns the
                            // header to inject. No secret is ever in this config.
                            "name": "envoy.filters.http.ext_authz",
                            "typed_config": {
                                "@type": "type.googleapis.com/envoy.extensions.filters.http.ext_authz.v3.ExtAuthz",
                                "transport_api_version": "V3",
                                "grpc_service": {
                                    "envoy_grpc": { "cluster_name": "orchestrator_grpc" }
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

/// Per-route ext_authz config (JSON) that ENABLES the credential callout for a
/// credential-injection route, passing its non-secret `(sandbox_id, route_id)`
/// to the ext_authz service as `context_extensions`.
fn ext_authz_enable_json(sandbox_id: &Uuid, route_id: &str) -> Value {
    let mut context = serde_json::Map::new();
    context.insert(
        crate::kernel::credential_resolution::EXT_AUTHZ_SANDBOX_ID_KEY.to_string(),
        json!(sandbox_id.to_string()),
    );
    context.insert(
        crate::kernel::credential_resolution::EXT_AUTHZ_ROUTE_ID_KEY.to_string(),
        json!(route_id),
    );
    json!({
        "envoy.filters.http.ext_authz": {
            "@type": "type.googleapis.com/envoy.extensions.filters.http.ext_authz.v3.ExtAuthzPerRoute",
            "check_settings": { "context_extensions": context }
        }
    })
}

/// Per-route ext_authz config (JSON) that DISABLES the callout — used on
/// allowlist/deny traffic, which needs no platform credential.
fn ext_authz_disabled_json() -> Value {
    json!({
        "envoy.filters.http.ext_authz": {
            "@type": "type.googleapis.com/envoy.extensions.filters.http.ext_authz.v3.ExtAuthzPerRoute",
            "disabled": true
        }
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
    sandbox_id: &Uuid,
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
                // SP-3 Task 1: no secret is baked into the listener. Credential
                // injection is performed per request via an ext_authz callout to
                // the orchestrator (wired in Task 5); the listener carries only
                // the non-secret ref + the auth-header strip set.
                let headers: Vec<Value> = Vec::new();
                let headers_to_remove = if r.remove_headers.is_empty() {
                    auth_headers_to_remove(&r.inject_header)
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
                    "request_headers_to_remove": headers_to_remove,
                    // Enable per-request credential resolution for this route,
                    // passing its (sandbox_id, route_id) to the ext_authz service
                    // via non-secret context_extensions.
                    "typed_per_filter_config": ext_authz_enable_json(sandbox_id, &r.id)
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
            // Allowlist traffic needs no credential; skip the ext_authz callout.
            "typed_per_filter_config": ext_authz_disabled_json(),
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
        "typed_per_filter_config": ext_authz_disabled_json(),
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
        ListenerKind::Http => build_http_listener_proto(
            &spec.sandbox_id,
            &spec.allowed_hosts,
            &spec.credentials,
            &spec.denied_cidrs,
        ),
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
            common_tls_context::ValidationContextType, subject_alt_name_matcher,
            CertificateValidationContext, CommonTlsContext, SubjectAltNameMatcher,
            UpstreamTlsContext,
        };
        use envoy_types::pb::envoy::r#type::matcher::v3::{string_matcher, StringMatcher};

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
                        match_typed_subject_alt_names: vec![SubjectAltNameMatcher {
                            san_type: subject_alt_name_matcher::SanType::Dns as i32,
                            matcher: Some(StringMatcher {
                                ignore_case: false,
                                match_pattern: Some(string_matcher::MatchPattern::Exact(
                                    spec.upstream_host.clone(),
                                )),
                            }),
                            oid: String::new(),
                        }],
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

// `envoy-types` 0.5.1 predates Envoy 1.39's DnsCacheConfig field 16. These
// minimal wire-compatible messages let both filesystem and Delta xDS modes emit
// the same resolved-address SSRF filter without upgrading the crate's entire
// tonic/prost graph. Remove them when the production control plane replaces the
// in-process xDS prototype.
#[derive(Clone, PartialEq, prost::Message)]
struct DynamicForwardProxyFilterConfigV139 {
    #[prost(message, optional, tag = "1")]
    dns_cache_config: Option<DnsCacheConfigV139>,
    #[prost(bool, tag = "2")]
    save_upstream_address: bool,
}

#[derive(Clone, PartialEq, prost::Message)]
struct DnsCacheConfigV139 {
    #[prost(string, tag = "1")]
    name: String,
    #[prost(int32, tag = "2")]
    dns_lookup_family: i32,
    #[prost(message, optional, tag = "16")]
    resolved_address_filter: Option<AddressMatcherV139>,
}

#[derive(Clone, PartialEq, prost::Message)]
struct AddressMatcherV139 {
    #[prost(message, repeated, tag = "1")]
    ranges: Vec<CidrRangeV139>,
    #[prost(bool, tag = "2")]
    invert_match: bool,
}

#[derive(Clone, PartialEq, prost::Message)]
struct CidrRangeV139 {
    #[prost(string, tag = "1")]
    address_prefix: String,
    #[prost(message, optional, tag = "2")]
    prefix_len: Option<envoy_types::pb::google::protobuf::UInt32Value>,
}

/// Type URL for the per-route ext_authz override, used in the proto renderer's
/// `typed_per_filter_config` maps (mirror of the JSON `@type`).
const EXT_AUTHZ_PER_ROUTE_TYPE_URL: &str =
    "type.googleapis.com/envoy.extensions.filters.http.ext_authz.v3.ExtAuthzPerRoute";

/// Per-route ext_authz config (proto) that ENABLES the credential callout for a
/// credential-injection route, passing its non-secret `(sandbox_id, route_id)`
/// to the ext_authz service as `context_extensions`. Proto mirror of
/// [`ext_authz_enable_json`]; returned as a `typed_per_filter_config` map keyed
/// by the filter name.
fn ext_authz_enable_proto(sandbox_id: &Uuid, route_id: &str) -> HashMap<String, Any> {
    use envoy_types::pb::envoy::extensions::filters::http::ext_authz::v3::{
        ext_authz_per_route, CheckSettings, ExtAuthzPerRoute,
    };
    let mut context = HashMap::new();
    context.insert(
        crate::kernel::credential_resolution::EXT_AUTHZ_SANDBOX_ID_KEY.to_string(),
        sandbox_id.to_string(),
    );
    context.insert(
        crate::kernel::credential_resolution::EXT_AUTHZ_ROUTE_ID_KEY.to_string(),
        route_id.to_string(),
    );
    let per_route = ExtAuthzPerRoute {
        r#override: Some(ext_authz_per_route::Override::CheckSettings(
            CheckSettings {
                context_extensions: context,
                ..Default::default()
            },
        )),
    };
    let mut map = HashMap::new();
    map.insert(
        "envoy.filters.http.ext_authz".to_string(),
        pack_any(EXT_AUTHZ_PER_ROUTE_TYPE_URL, &per_route),
    );
    map
}

/// Per-route ext_authz config (proto) that DISABLES the callout — used on
/// allowlist/deny traffic, which needs no platform credential. Proto mirror of
/// [`ext_authz_disabled_json`].
fn ext_authz_disabled_proto() -> HashMap<String, Any> {
    use envoy_types::pb::envoy::extensions::filters::http::ext_authz::v3::{
        ext_authz_per_route, ExtAuthzPerRoute,
    };
    let per_route = ExtAuthzPerRoute {
        r#override: Some(ext_authz_per_route::Override::Disabled(true)),
    };
    let mut map = HashMap::new();
    map.insert(
        "envoy.filters.http.ext_authz".to_string(),
        pack_any(EXT_AUTHZ_PER_ROUTE_TYPE_URL, &per_route),
    );
    map
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
    denied_cidrs: &[DeniedCidr],
) -> envoy_types::pb::envoy::config::listener::v3::Listener {
    use envoy_types::pb::envoy::config::core::v3::{address, Address, Http1ProtocolOptions, Pipe};
    use envoy_types::pb::envoy::config::listener::v3::{filter, Filter, FilterChain, Listener};
    use envoy_types::pb::envoy::config::route::v3::RouteConfiguration;
    use envoy_types::pb::envoy::extensions::filters::http::router::v3::Router;
    use envoy_types::pb::envoy::extensions::filters::network::http_connection_manager::v3::{
        http_connection_manager, http_filter, HttpConnectionManager, HttpFilter,
    };

    let dfp_filter = DynamicForwardProxyFilterConfigV139 {
        dns_cache_config: Some(DnsCacheConfigV139 {
            name: "dynamic_forward_proxy_cache".to_string(),
            dns_lookup_family: 1,
            resolved_address_filter: Some(AddressMatcherV139 {
                ranges: denied_cidrs
                    .iter()
                    .map(|cidr| CidrRangeV139 {
                        address_prefix: cidr.address_prefix.clone(),
                        prefix_len: Some(envoy_types::pb::google::protobuf::UInt32Value {
                            value: cidr.prefix_len,
                        }),
                    })
                    .collect(),
                invert_match: false,
            }),
        }),
        save_upstream_address: false,
    };

    // ext_authz HTTP filter: points at the always-present orchestrator_grpc
    // bootstrap cluster over gRPC v3. Per-route context_extensions (set below)
    // decide which routes actually invoke the callout; no secret lives here.
    let ext_authz = {
        use envoy_types::pb::envoy::config::core::v3::ApiVersion;
        use envoy_types::pb::envoy::config::core::v3::{grpc_service, GrpcService};
        use envoy_types::pb::envoy::extensions::filters::http::ext_authz::v3::{
            ext_authz, ExtAuthz,
        };
        ExtAuthz {
            services: Some(ext_authz::Services::GrpcService(GrpcService {
                target_specifier: Some(grpc_service::TargetSpecifier::EnvoyGrpc(
                    grpc_service::EnvoyGrpc {
                        cluster_name: "orchestrator_grpc".to_string(),
                        ..Default::default()
                    },
                )),
                ..Default::default()
            })),
            transport_api_version: ApiVersion::V3 as i32,
            ..Default::default()
        }
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
                virtual_hosts: build_virtual_hosts_proto(sandbox_id, allowed_hosts, credentials),
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
                // Per-request credential resolution. A no-op unless a route
                // enables it (per-route context_extensions); the orchestrator's
                // ext_authz service resolves the credential and returns the
                // header to inject. No secret is ever in this config.
                name: "envoy.filters.http.ext_authz".to_string(),
                config_type: Some(http_filter::ConfigType::TypedConfig(pack_any(
                    "type.googleapis.com/envoy.extensions.filters.http.ext_authz.v3.ExtAuthz",
                    &ext_authz,
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
    sandbox_id: &Uuid,
    allowed_hosts: &[String],
    credentials: &[CredentialRoute],
) -> Vec<envoy_types::pb::envoy::config::route::v3::VirtualHost> {
    use envoy_types::pb::envoy::config::core::v3::{data_source, DataSource, HeaderValueOption};
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
                // SP-3 Task 1: no secret baked; ext_authz injects per request
                // (Task 5). Listener carries only the ref + auth-header strip set.
                let headers: Vec<HeaderValueOption> = Vec::new();
                let headers_to_remove = if r.remove_headers.is_empty() {
                    auth_headers_to_remove(&r.inject_header)
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
                    // Enable per-request credential resolution for this route,
                    // passing its (sandbox_id, route_id) to the ext_authz service
                    // via non-secret context_extensions.
                    typed_per_filter_config: ext_authz_enable_proto(sandbox_id, &r.id),
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
            // Allowlist traffic needs no credential; skip the ext_authz callout.
            typed_per_filter_config: ext_authz_disabled_proto(),
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
        typed_per_filter_config: ext_authz_disabled_proto(),
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
    use crate::egress::policy::{CredentialRef, InjectScheme};
    use prost::Message;

    fn denied_cidrs() -> Vec<DeniedCidr> {
        vec![
            "10.0.0.0/8".parse().unwrap(),
            "169.254.0.0/16".parse().unwrap(),
        ]
    }

    #[test]
    fn denied_cidr_parser_validates_address_family_prefixes() {
        assert_eq!(
            "10.0.0.0/8".parse::<DeniedCidr>().unwrap(),
            DeniedCidr {
                address_prefix: "10.0.0.0".to_string(),
                prefix_len: 8,
            }
        );
        assert!("10.0.0.0/33".parse::<DeniedCidr>().is_err());
        assert!("not-an-ip/8".parse::<DeniedCidr>().is_err());
        assert!("10.0.0.0".parse::<DeniedCidr>().is_err());
    }

    fn spec(kind: ListenerKind, hosts: &[&str]) -> ListenerSpec {
        ListenerSpec {
            sandbox_id: Uuid::nil(),
            kind,
            allowed_hosts: hosts.iter().map(|s| s.to_string()).collect(),
            credentials: vec![],
            denied_cidrs: denied_cidrs(),
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
            denied_cidrs: denied_cidrs(),
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
            credential_ref: CredentialRef::Llm {
                secret_name: "test-secret".to_string(),
                secret_key: "ANTHROPIC_API_KEY".to_string(),
                project_id: None,
            },
            inject_header: "authorization".to_string(),
            inject_scheme: InjectScheme::Bearer,
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
            credential_ref: CredentialRef::Mcp {
                vault_id: Uuid::nil(),
                mcp_server_url: "https://mcp.example.com/sse".to_string(),
            },
            inject_header: "authorization".to_string(),
            inject_scheme: InjectScheme::Bearer,
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
                    credential_ref: CredentialRef::Llm {
                        secret_name: "test-secret".to_string(),
                        secret_key: "ANTHROPIC_API_KEY".to_string(),
                        project_id: None,
                    },
                    inject_header: "authorization".to_string(),
                    inject_scheme: InjectScheme::Bearer,
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
                    credential_ref: CredentialRef::Mcp {
                        vault_id: Uuid::nil(),
                        mcp_server_url: "https://mcp.example.com/sse".to_string(),
                    },
                    inject_header: "authorization".to_string(),
                    inject_scheme: InjectScheme::Bearer,
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
        assert_eq!(
            cj["transport_socket"]["typed_config"]["common_tls_context"]["validation_context"]
                ["match_typed_subject_alt_names"][0]["matcher"]["exact"],
            "mcp.example.com"
        );

        let any = encode_cluster_any(mcp_cluster).unwrap();
        use envoy_types::pb::envoy::config::cluster::v3::Cluster;
        use envoy_types::pb::envoy::config::core::v3::transport_socket;
        use envoy_types::pb::envoy::extensions::transport_sockets::tls::v3::{
            common_tls_context, UpstreamTlsContext,
        };
        use envoy_types::pb::envoy::r#type::matcher::v3::string_matcher;
        let cluster = Cluster::decode(any.value.as_slice()).unwrap();
        let tls_any = match cluster.transport_socket.unwrap().config_type.unwrap() {
            transport_socket::ConfigType::TypedConfig(any) => any,
        };
        let tls = UpstreamTlsContext::decode(tls_any.value.as_slice()).unwrap();
        let validation = match tls
            .common_tls_context
            .unwrap()
            .validation_context_type
            .unwrap()
        {
            common_tls_context::ValidationContextType::ValidationContext(context) => context,
            _ => panic!("expected inline validation context"),
        };
        let san = &validation.match_typed_subject_alt_names[0];
        assert!(matches!(
            san.matcher.as_ref().unwrap().match_pattern.as_ref().unwrap(),
            string_matcher::MatchPattern::Exact(host) if host == "mcp.example.com"
        ));
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
                    credential_ref: CredentialRef::External {
                        secret_name: "svc".to_string(),
                        secret_key: "COOKIE_HEADER".to_string(),
                        project_id: None,
                    },
                    inject_header: "cookie".to_string(),
                    inject_scheme: InjectScheme::Raw,
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
                    credential_ref: CredentialRef::External {
                        secret_name: "svc".to_string(),
                        secret_key: "COOKIE_HEADER".to_string(),
                        project_id: None,
                    },
                    inject_header: "cookie".to_string(),
                    inject_scheme: InjectScheme::Raw,
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
        let vh =
            build_virtual_hosts_json(&Uuid::nil(), &["other.example.com".to_string()], &routes);
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
            credential_ref: CredentialRef::External {
                secret_name: "svc".to_string(),
                secret_key: "COOKIE_HEADER".to_string(),
                project_id: None,
            },
            inject_header: "cookie".to_string(),
            inject_scheme: InjectScheme::Raw,
            remove_headers: vec!["cookie".to_string()],
        };
        let creds = SandboxCredentials {
            routes: vec![
                mk("external-direct:crm-api", "/api/"),
                mk("external-direct:crm-auth", "/auth/api/"),
            ],
        };
        let routes = creds.to_routes(&sid);
        let vh = build_virtual_hosts_json(&Uuid::nil(), &[], &routes);

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
            credential_ref: CredentialRef::External {
                secret_name: "svc".to_string(),
                secret_key: "COOKIE_HEADER".to_string(),
                project_id: None,
            },
            inject_header: "cookie".to_string(),
            inject_scheme: InjectScheme::Raw,
            remove_headers: vec!["cookie".to_string()],
        };
        let prefix = EgressCredentialRoute {
            id: "external-direct:crm:1".to_string(),
            match_prefix: "/api/work/".to_string(),
            upstream_prefix: "/api/work/".to_string(),
            exact_path: false,
            ..exact.clone()
        };

        let vh = build_virtual_hosts_json(&Uuid::nil(), &[], &[exact, prefix]);
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
        let vh = build_virtual_hosts_json(&Uuid::nil(), &[], &[]);
        assert_eq!(vh.len(), 1);
        assert_eq!(vh[0]["name"], "deny_all");
        // With an allowlist, `allowed` precedes `deny_all`.
        let vh = build_virtual_hosts_json(&Uuid::nil(), &["a.com".to_string()], &[]);
        assert_eq!(vh.len(), 2);
        assert_eq!(vh[0]["name"], "allowed");
        assert_eq!(vh[1]["name"], "deny_all");
    }

    #[test]
    fn credential_vhosts_precede_allowlist_and_inject_headers() {
        let creds = vec![llm_route(), mcp_route("gitlab"), mcp_route("jira")];
        let vh = build_virtual_hosts_json(&Uuid::nil(), &["a.com".to_string()], &creds);
        // Placeholder-host vhosts, then allowlist, then deny_all.
        assert_eq!(vh[0]["name"], "egress_llm-egress_internal");
        assert_eq!(vh[1]["name"], "egress_mcp-egress_internal");
        assert_eq!(vh[2]["name"], "allowed");
        assert_eq!(vh[3]["name"], "deny_all");

        // SP-3 Task 1: the listener bakes NO secret; credential injection is
        // performed per request via an ext_authz callout (wired in Task 5). The
        // route still rewrites host/prefix to the real upstream and strips
        // sandbox-supplied auth headers.
        let llm_routes = vh[0]["routes"].as_array().unwrap();
        assert!(llm_routes[0]["request_headers_to_add"]
            .as_array()
            .unwrap()
            .is_empty());
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

    /// A spec with a non-nil sandbox id so tests can assert the id is threaded
    /// into per-route context_extensions (nil would hide a threading bug).
    fn http_spec_with_sandbox(sandbox_id: Uuid, creds: Vec<CredentialRoute>) -> ListenerSpec {
        ListenerSpec {
            sandbox_id,
            kind: ListenerKind::Http,
            allowed_hosts: vec!["a.com".to_string()],
            credentials: creds,
            denied_cidrs: denied_cidrs(),
        }
    }

    #[test]
    fn http_listener_json_wires_ext_authz_per_route() {
        let sid = Uuid::parse_str("11111111-1111-1111-1111-111111111111").unwrap();
        let http = http_spec_with_sandbox(sid, vec![llm_route()]);
        let json = render_listener_json(&http);

        // The ext_authz HTTP filter sits between dynamic_forward_proxy and router
        // and points at the orchestrator_grpc bootstrap cluster over gRPC v3.
        let http_filters = json["filter_chains"][0]["filters"][0]["typed_config"]["http_filters"]
            .as_array()
            .unwrap();
        let filter_names: Vec<&str> = http_filters
            .iter()
            .map(|f| f["name"].as_str().unwrap())
            .collect();
        assert_eq!(
            filter_names,
            vec![
                "envoy.filters.http.dynamic_forward_proxy",
                "envoy.filters.http.ext_authz",
                "envoy.filters.http.router",
            ]
        );
        let denied_ranges = http_filters[0]["typed_config"]["dns_cache_config"]
            ["resolved_address_filter"]["ranges"]
            .as_array()
            .unwrap();
        assert!(denied_ranges
            .iter()
            .any(|range| { range["address_prefix"] == "10.0.0.0" && range["prefix_len"] == 8 }));
        assert!(denied_ranges.iter().any(|range| {
            range["address_prefix"] == "169.254.0.0" && range["prefix_len"] == 16
        }));
        let ext_authz = &http_filters[1]["typed_config"];
        assert_eq!(ext_authz["transport_api_version"], "V3");
        assert_eq!(
            ext_authz["grpc_service"]["envoy_grpc"]["cluster_name"],
            "orchestrator_grpc"
        );

        // The credential vhost's route ENABLES the callout, carrying the
        // non-secret (sandbox_id, route_id) as context_extensions.
        let vhosts = json["filter_chains"][0]["filters"][0]["typed_config"]["route_config"]
            ["virtual_hosts"]
            .as_array()
            .unwrap();
        let cred_vhost = vhosts
            .iter()
            .find(|v| v["name"] == "egress_llm-egress_internal")
            .unwrap();
        let ctx = &cred_vhost["routes"][0]["typed_per_filter_config"]
            ["envoy.filters.http.ext_authz"]["check_settings"]["context_extensions"];
        assert_eq!(ctx["joysafeter_sandbox_id"], sid.to_string());
        assert_eq!(ctx["joysafeter_route_id"], "llm");

        // Allowlist and deny_all vhosts DISABLE the callout (no credential).
        for name in ["allowed", "deny_all"] {
            let v = vhosts.iter().find(|v| v["name"] == name).unwrap();
            assert_eq!(
                v["typed_per_filter_config"]["envoy.filters.http.ext_authz"]["disabled"],
                serde_json::Value::Bool(true),
                "{name} vhost should disable ext_authz"
            );
        }

        // No secret name/key/value ever appears in the rendered listener; only
        // the non-secret coordinates travel to the ext_authz service.
        let serialized = serde_json::to_string(&json).unwrap();
        assert!(!serialized.contains("test-secret"));
        assert!(!serialized.contains("ANTHROPIC_API_KEY"));
    }

    #[test]
    fn http_listener_proto_wires_ext_authz_per_route() {
        use envoy_types::pb::envoy::config::core::v3::grpc_service;
        use envoy_types::pb::envoy::config::listener::v3::{filter, Listener};
        use envoy_types::pb::envoy::extensions::filters::http::ext_authz::v3::{
            ext_authz, ext_authz_per_route, ExtAuthz, ExtAuthzPerRoute,
        };
        use envoy_types::pb::envoy::extensions::filters::network::http_connection_manager::v3::{
            http_connection_manager, http_filter, HttpConnectionManager,
        };

        let sid = Uuid::parse_str("22222222-2222-2222-2222-222222222222").unwrap();
        let http = http_spec_with_sandbox(sid, vec![llm_route()]);
        let any = encode_listener_any(&http).unwrap();

        let l = Listener::decode(any.value.as_slice()).unwrap();
        let hcm_any = match &l.filter_chains[0].filters[0].config_type {
            Some(filter::ConfigType::TypedConfig(a)) => a,
            _ => panic!("expected typed config"),
        };
        let hcm = HttpConnectionManager::decode(hcm_any.value.as_slice()).unwrap();

        let dfp_any = match &hcm.http_filters[0].config_type {
            Some(http_filter::ConfigType::TypedConfig(any)) => any,
            _ => panic!("expected dynamic forward proxy typed config"),
        };
        let dfp = DynamicForwardProxyFilterConfigV139::decode(dfp_any.value.as_slice()).unwrap();
        let dns = dfp.dns_cache_config.unwrap();
        assert_eq!(dns.dns_lookup_family, 1);
        let ranges = dns.resolved_address_filter.unwrap().ranges;
        assert!(ranges.iter().any(|range| {
            range.address_prefix == "10.0.0.0"
                && range.prefix_len.as_ref().map(|prefix| prefix.value) == Some(8)
        }));
        assert!(ranges.iter().any(|range| {
            range.address_prefix == "169.254.0.0"
                && range.prefix_len.as_ref().map(|prefix| prefix.value) == Some(16)
        }));

        // Filter order: dynamic_forward_proxy, ext_authz, router.
        let filter_names: Vec<&str> = hcm.http_filters.iter().map(|f| f.name.as_str()).collect();
        assert_eq!(
            filter_names,
            vec![
                "envoy.filters.http.dynamic_forward_proxy",
                "envoy.filters.http.ext_authz",
                "envoy.filters.http.router",
            ]
        );

        // The ext_authz filter targets orchestrator_grpc over gRPC v3.
        let ext_authz_any = match &hcm.http_filters[1].config_type {
            Some(http_filter::ConfigType::TypedConfig(a)) => a,
            _ => panic!("expected ext_authz typed config"),
        };
        let ext_authz = ExtAuthz::decode(ext_authz_any.value.as_slice()).unwrap();
        assert_eq!(ext_authz.transport_api_version, 2); // ApiVersion::V3
        let cluster_name = match ext_authz.services {
            Some(ext_authz::Services::GrpcService(gs)) => match gs.target_specifier {
                Some(grpc_service::TargetSpecifier::EnvoyGrpc(e)) => e.cluster_name,
                _ => panic!("expected envoy_grpc"),
            },
            _ => panic!("expected grpc_service"),
        };
        assert_eq!(cluster_name, "orchestrator_grpc");

        // Credential route ENABLES the callout with the (sandbox_id, route_id)
        // context_extensions; allowlist/deny vhosts DISABLE it.
        let rc = match hcm.route_specifier {
            Some(http_connection_manager::RouteSpecifier::RouteConfig(rc)) => rc,
            _ => panic!("expected route config"),
        };
        let decode_per_route = |cfg: &HashMap<String, Any>| -> ExtAuthzPerRoute {
            let a = cfg
                .get("envoy.filters.http.ext_authz")
                .expect("ext_authz cfg");
            ExtAuthzPerRoute::decode(a.value.as_slice()).unwrap()
        };

        let cred_vhost = rc
            .virtual_hosts
            .iter()
            .find(|v| v.name == "egress_llm-egress_internal")
            .unwrap();
        let route_cfg = decode_per_route(&cred_vhost.routes[0].typed_per_filter_config);
        match route_cfg.r#override {
            Some(ext_authz_per_route::Override::CheckSettings(cs)) => {
                assert_eq!(
                    cs.context_extensions.get("joysafeter_sandbox_id"),
                    Some(&sid.to_string())
                );
                assert_eq!(
                    cs.context_extensions.get("joysafeter_route_id"),
                    Some(&"llm".to_string())
                );
            }
            other => panic!("expected CheckSettings, got {other:?}"),
        }

        for name in ["allowed", "deny_all"] {
            let v = rc.virtual_hosts.iter().find(|v| v.name == name).unwrap();
            let cfg = decode_per_route(&v.typed_per_filter_config);
            assert!(
                matches!(
                    cfg.r#override,
                    Some(ext_authz_per_route::Override::Disabled(true))
                ),
                "{name} vhost should disable ext_authz"
            );
        }
    }
}
