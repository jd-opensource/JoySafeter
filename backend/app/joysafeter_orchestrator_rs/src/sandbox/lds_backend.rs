//! Pluggable LDS (Listener Discovery Service) backends for the per-sandbox
//! Envoy proxy.
//!
//! `EnvoyManager` describes each sandbox's HTTP egress listener as a neutral
//! [`ListenerSpec`] and hands it to an
//! [`LdsBackend`]. Two backends exist, selected at startup by
//! `JOYSAFETER_ENVOY_XDS_MODE`:
//!
//! * [`FilesystemLds`] — renders listeners to canonical Envoy JSON and writes
//!   `/envoy-config/lds.json` into the Envoy container, which watches the file
//!   via `path_config_source`. O(N) per update.
//!
//! * [`GrpcLds`] — a Delta ADS gRPC server. Renders listeners to typed protobuf,
//!   keeps them in memory, and pushes only the changed resources to Envoy over a
//!   long-lived stream (`api_type: DELTA_GRPC`). O(1) per update, no file I/O.
//!
//! The sandbox egress data plane (network=none + shared `/sockets` volume + the
//! runner's socat bridge) is identical regardless of backend — only the transport
//! of the Listener config differs. Runner gRPC control-plane traffic bypasses
//! Envoy and connects directly to the orchestrator's Unix socket.

use std::collections::HashMap;
use std::pin::Pin;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use base64::Engine as _;
use futures::Stream;
use prost::Message;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use sqlx::PgPool;
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

fn protobuf_string_value(value: impl Into<String>) -> envoy_types::pb::google::protobuf::Value {
    envoy_types::pb::google::protobuf::Value {
        kind: Some(envoy_types::pb::google::protobuf::value::Kind::StringValue(
            value.into(),
        )),
    }
}

fn access_log_json_format(listener: String) -> envoy_types::pb::google::protobuf::Struct {
    envoy_types::pb::google::protobuf::Struct {
        fields: HashMap::from([
            ("ts".to_string(), protobuf_string_value("%START_TIME%")),
            (
                "method".to_string(),
                protobuf_string_value("%REQ(:METHOD)%"),
            ),
            (
                "authority".to_string(),
                protobuf_string_value("%REQ(:AUTHORITY)%"),
            ),
            (
                "path".to_string(),
                protobuf_string_value("%REQ(X-ENVOY-ORIGINAL-PATH?:PATH)%"),
            ),
            (
                "status".to_string(),
                protobuf_string_value("%RESPONSE_CODE%"),
            ),
            (
                "flags".to_string(),
                protobuf_string_value("%RESPONSE_FLAGS%"),
            ),
            (
                "response_code_details".to_string(),
                protobuf_string_value("%RESPONSE_CODE_DETAILS%"),
            ),
            (
                "upstream_transport_failure_reason".to_string(),
                protobuf_string_value("%UPSTREAM_TRANSPORT_FAILURE_REASON%"),
            ),
            (
                "upstream".to_string(),
                protobuf_string_value("%UPSTREAM_HOST%"),
            ),
            (
                "upstream_host".to_string(),
                protobuf_string_value("%UPSTREAM_HOST%"),
            ),
            (
                "cluster".to_string(),
                protobuf_string_value("%UPSTREAM_CLUSTER%"),
            ),
            (
                "upstream_cluster".to_string(),
                protobuf_string_value("%UPSTREAM_CLUSTER%"),
            ),
            (
                "attempt_count".to_string(),
                protobuf_string_value("%UPSTREAM_REQUEST_ATTEMPT_COUNT%"),
            ),
            (
                "duration_ms".to_string(),
                protobuf_string_value("%DURATION%"),
            ),
            (
                "bytes_in".to_string(),
                protobuf_string_value("%BYTES_RECEIVED%"),
            ),
            (
                "bytes_out".to_string(),
                protobuf_string_value("%BYTES_SENT%"),
            ),
            ("listener".to_string(), protobuf_string_value(listener)),
        ]),
    }
}

/// The Envoy type URL for a Listener resource. Delta responses tag each resource
/// with this so Envoy routes it to LDS.
const LISTENER_TYPE_URL: &str = "type.googleapis.com/envoy.config.listener.v3.Listener";

/// Hard client-side bound on any single Docker exec/upload against the Envoy
/// container. The Docker daemon calls are not self-bounding; without this a
/// stalled daemon wedges sandbox provisioning indefinitely. Generous enough to
/// cover a busy daemon, short enough that the provisioning path degrades and
/// retries rather than hanging.
// ---------------------------------------------------------------------------
// Neutral listener description
// ---------------------------------------------------------------------------

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
            .field("match_prefix", &self.match_prefix)
            .field("exact_path", &self.exact_path)
            .field("upstream_host", &self.upstream_host)
            .field("upstream_port", &self.upstream_port)
            .field("upstream_prefix", &self.upstream_prefix)
            .field("upstream_tls", &self.upstream_tls)
            .field("cluster_name", &self.cluster_name)
            .field("inject_header_names", &inject_header_names)
            .field("inject_header_values", &"<redacted>")
            .field("remove_headers", &self.remove_headers)
            .finish()
    }
}

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

    pub fn clusters(&self, _sandbox_id: &Uuid) -> Vec<ClusterSpec> {
        // No per-sandbox clusters needed — all credential-injection routes point
        // to the shared dynamic_forward_proxy / dynamic_forward_proxy_tls clusters.
        Vec::new()
    }
}

pub fn validate_egress_policy(
    _sandbox_id: &Uuid,
    policy: &SandboxEgressPolicy,
) -> anyhow::Result<()> {
    let mut route_ids = std::collections::HashSet::new();
    // All credential-injection routes use the shared dynamic_forward_proxy
    // clusters (TLS or plain); no per-sandbox clusters to validate against.
    const SHARED_CLUSTERS: &[&str] = &["dynamic_forward_proxy", "dynamic_forward_proxy_tls"];

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
        validate_route_path(&route.match_prefix).map_err(|e| {
            anyhow::anyhow!("invalid egress match_prefix {}: {e}", route.match_prefix)
        })?;
        validate_route_path(&route.upstream_prefix).map_err(|e| {
            anyhow::anyhow!(
                "invalid egress upstream_prefix {}: {e}",
                route.upstream_prefix
            )
        })?;
        if route.cluster_name.is_empty() || !SHARED_CLUSTERS.contains(&route.cluster_name.as_str())
        {
            anyhow::bail!(
                "egress route {} references unknown cluster {}",
                route.id,
                route.cluster_name
            );
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

pub fn egress_policy_summary(sandbox_id: &Uuid, policy: &SandboxEgressPolicy) -> Value {
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
                "match_prefix": route.match_prefix,
                "exact_path": route.exact_path,
                "upstream_host": route.upstream_host,
                "upstream_port": route.upstream_port,
                "upstream_prefix": route.upstream_prefix,
                "upstream_tls": route.upstream_tls,
                "cluster_name": route.cluster_name,
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
        sandbox_id: &Uuid,
        allowlist_hosts: Vec<String>,
    ) -> SandboxEgressPolicy {
        SandboxEgressPolicy {
            allowlist_hosts,
            credential_routes: self.to_routes(sandbox_id),
            proxy_auth_token: self.proxy_auth_token.clone(),
        }
    }

    /// Flatten into credential routes, filling each route's `cluster_name` to
    /// point at the shared dynamic_forward_proxy cluster (TLS or plain) based on
    /// the route's `upstream_tls`. No per-sandbox clusters are created; the DFP
    /// cluster resolves DNS on-demand from the `host_rewrite_literal` target.
    pub fn to_routes(&self, _sandbox_id: &Uuid) -> Vec<EgressCredentialRoute> {
        self.routes
            .iter()
            .map(|r| {
                let mut route = r.clone();
                if route.cluster_name.is_empty() {
                    route.cluster_name = if route.upstream_tls {
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

fn route_prefix_rewrite(r: &EgressCredentialRoute) -> String {
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
    /// Resource name Envoy sees, e.g. `"<uuid>_http"`.
    pub fn resource_name(&self) -> String {
        match self.kind {
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
    /// Remove listeners by resource name (e.g. `"<uuid>_http"`).
    async fn remove(&self, names: Vec<String>) -> anyhow::Result<()>;
    /// Replace the entire set (used for init and gRPC re-sync on reconnect).
    async fn replace_all(&self, specs: Vec<ListenerSpec>) -> anyhow::Result<()>;
    /// Wait until Envoy accepts the sandbox's listener resources.
    /// Filesystem LDS has no ACK channel, so its default is successful after write.
    async fn wait_for_sandbox_ack(
        &self,
        _sandbox_id: Uuid,
        _timeout: Duration,
    ) -> anyhow::Result<()> {
        Ok(())
    }
    /// Release any retained per-sandbox apply/ACK bookkeeping on teardown.
    /// Filesystem LDS keeps no such state, so the default is a no-op.
    async fn forget_sandbox(&self, _sandbox_id: Uuid) {}

    /// Atomically apply one sandbox's clusters and listeners in a single update
    /// (CDS ordered before LDS for make-before-break). Existing clusters under
    /// `cluster_prefix` that are absent from `clusters` are removed.
    ///
    /// Returns `Ok(true)` if the backend applied the combined batch, or
    /// `Ok(false)` if it does not support batching and the caller should fall
    /// back to separate CDS then LDS writes. The default is `Ok(false)` so the
    /// filesystem backend keeps its two-file behaviour unchanged.
    async fn apply_sandbox_batch(
        &self,
        _clusters: Vec<ClusterSpec>,
        _listeners: Vec<ListenerSpec>,
        _cluster_prefix: String,
    ) -> anyhow::Result<bool> {
        Ok(false)
    }
}

// ===========================================================================
// Filesystem backend
// ===========================================================================

/// LDS backend that writes `/envoy-config/lds.json` into the Envoy container.
pub struct FilesystemLds {
    config_dir: String,
    /// name → rendered listener JSON. Rewritten in full on every change.
    listeners: Mutex<HashMap<String, Value>>,
}

impl FilesystemLds {
    pub fn new(config_dir: String) -> Self {
        Self {
            config_dir,
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
        write_config_file(&self.config_dir, "lds.json", &lds_json).await?;
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
    /// Replace every cluster whose name starts with `prefix` in a single backend
    /// update. Used when refreshing one sandbox's egress policy so removed routes
    /// do not leave stale upstream clusters behind.
    async fn replace_by_prefix(&self, prefix: &str, specs: Vec<ClusterSpec>) -> anyhow::Result<()>;
    async fn replace_all(&self, specs: Vec<ClusterSpec>) -> anyhow::Result<()>;
}

/// The Envoy type URL for a Cluster resource (Delta CDS).
const CLUSTER_TYPE_URL: &str = "type.googleapis.com/envoy.config.cluster.v3.Cluster";

/// CDS backend that writes `/envoy-config/cds.json` into the Envoy container.
pub struct FilesystemCds {
    config_dir: String,
    clusters: Mutex<HashMap<String, Value>>,
}

impl FilesystemCds {
    pub fn new(config_dir: String) -> Self {
        Self {
            config_dir,
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
        write_config_file(&self.config_dir, "cds.json", &cds_json).await?;
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

    async fn replace_by_prefix(&self, prefix: &str, specs: Vec<ClusterSpec>) -> anyhow::Result<()> {
        let mut clusters = self.clusters.lock().await;
        clusters.retain(|name, _| !name.starts_with(prefix));
        for spec in specs {
            clusters.insert(spec.name.clone(), render_cluster_json(&spec));
        }
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

/// Render a [`ClusterSpec`] to canonical Envoy Cluster JSON: a LOGICAL_DNS
/// cluster with one endpoint at the real upstream host:port, plus a TLS
/// transport socket (auto-SNI + system CA trust) when the upstream is HTTPS.
///
/// LOGICAL_DNS (vs STRICT_DNS) is chosen because each credential-injection
/// upstream has exactly one endpoint. LOGICAL_DNS only resolves on new
/// connections and retains the last-good IP on transient DNS failures, which
/// eliminates the "no healthy upstream" 503 window that STRICT_DNS produces
/// when DNS briefly fails (it clears the endpoint list entirely).
fn render_cluster_json(spec: &ClusterSpec) -> Value {
    let mut cluster = json!({
        "@type": CLUSTER_TYPE_URL,
        "name": spec.name,
        "connect_timeout": "10s",
        "type": "LOGICAL_DNS",
        "lb_policy": "ROUND_ROBIN",
        "dns_lookup_family": "V4_ONLY",
        "dns_refresh_rate": "2s",
        "dns_failure_refresh_rate": {
            "base_interval": "0.5s",
            "max_interval": "2s"
        },
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
        ListenerKind::Http => build_http_listener_json(
            &spec.sandbox_id,
            &spec.allowed_hosts,
            &spec.credentials,
            spec.proxy_auth_token.as_deref(),
        ),
    }
}

/// HTTP connection manager listener with domain-based allowlist.
fn build_http_listener_json(
    sandbox_id: &Uuid,
    allowed_hosts: &[String],
    credentials: &[EgressCredentialRoute],
    proxy_auth_token: Option<&str>,
) -> Value {
    let virtual_hosts = build_virtual_hosts_json(allowed_hosts, credentials, proxy_auth_token);

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
                    "access_log": [{
                        "name": "envoy.access_loggers.stdout",
                        "typed_config": {
                            "@type": "type.googleapis.com/envoy.extensions.access_loggers.stream.v3.StdoutAccessLog",
                            "log_format": {
                                "json_format": {
                                    "ts": "%START_TIME%",
                                    "method": "%REQ(:METHOD)%",
                                    "authority": "%REQ(:AUTHORITY)%",
                                    "path": "%REQ(X-ENVOY-ORIGINAL-PATH?:PATH)%",
                                    "status": "%RESPONSE_CODE%",
                                    "flags": "%RESPONSE_FLAGS%",
                                    "response_code_details": "%RESPONSE_CODE_DETAILS%",
                                    "upstream_transport_failure_reason": "%UPSTREAM_TRANSPORT_FAILURE_REASON%",
                                    "upstream": "%UPSTREAM_HOST%",
                                    "upstream_host": "%UPSTREAM_HOST%",
                                    "cluster": "%UPSTREAM_CLUSTER%",
                                    "upstream_cluster": "%UPSTREAM_CLUSTER%",
                                    "attempt_count": "%UPSTREAM_REQUEST_ATTEMPT_COUNT%",
                                    "duration_ms": "%DURATION%",
                                    "listener": format!("{sandbox_id}_http")
                                }
                            }
                        }
                    }],
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
    credentials: &[EgressCredentialRoute],
    proxy_auth_token: Option<&str>,
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
                let mut headers_to_remove = if r.remove_headers.is_empty() {
                    auth_headers_to_remove(&r.inject_headers)
                } else {
                    r.remove_headers.clone()
                };
                if !headers_to_remove
                    .iter()
                    .any(|h| h.eq_ignore_ascii_case("proxy-authorization"))
                {
                    headers_to_remove.push("proxy-authorization".to_string());
                }
                // For transparent routes (host is already real), no host_rewrite
                // or prefix_rewrite is needed. Placeholder routes rewrite to
                // the real upstream.
                let is_transparent = r.exposure == EgressExposure::Transparent;
                let prefix_rewrite = route_prefix_rewrite(r);
                let route_json = if is_transparent {
                    // Transparent: Host is real, path is real, just forward.
                    json!({
                        "cluster": r.cluster_name,
                        "timeout": "0s",
                        "retry_policy": {
                            "retry_on": "5xx,reset,connect-failure",
                            "num_retries": 2
                        }
                    })
                } else if r.exact_path {
                    json!({
                        "cluster": r.cluster_name,
                        "host_rewrite_literal": r.upstream_host,
                        "timeout": "0s",
                        "retry_policy": {
                            "retry_on": "5xx,reset,connect-failure",
                            "num_retries": 2
                        }
                    })
                } else {
                    json!({
                        "cluster": r.cluster_name,
                        "host_rewrite_literal": r.upstream_host,
                        "prefix_rewrite": prefix_rewrite,
                        "timeout": "0s",
                        "retry_policy": {
                            "retry_on": "5xx,reset,connect-failure",
                            "num_retries": 2
                        }
                    })
                };
                let mut match_json = if r.exact_path {
                    json!({ "path": r.match_prefix })
                } else {
                    json!({ "prefix": r.match_prefix })
                };
                add_proxy_auth_match(&mut match_json, proxy_auth_token);
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
                    "match": route_match_with_proxy_auth(json!({ "connect_matcher": {} }), proxy_auth_token),
                    "route": {
                        "cluster": "dynamic_forward_proxy",
                        "upgrade_configs": [{
                            "upgrade_type": "CONNECT",
                            "connect_config": {}
                        }]
                    },
                    "request_headers_to_remove": ["proxy-authorization"]
                },
                {
                    "match": route_match_with_proxy_auth(json!({ "prefix": "/" }), proxy_auth_token),
                    "route": {
                        "cluster": "dynamic_forward_proxy",
                        "retry_policy": {
                            "retry_on": "5xx,reset,connect-failure",
                            "num_retries": 2
                        }
                    },
                    "request_headers_to_remove": ["proxy-authorization"]
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

fn proxy_authorization_value(token: &str) -> String {
    format!(
        "Basic {}",
        base64::engine::general_purpose::STANDARD.encode(format!("sandbox:{token}"))
    )
}

fn add_proxy_auth_match(match_json: &mut Value, proxy_auth_token: Option<&str>) {
    let Some(token) = proxy_auth_token.filter(|token| !token.is_empty()) else {
        return;
    };
    if let Some(obj) = match_json.as_object_mut() {
        obj.insert(
            "headers".to_string(),
            json!([{
                "name": "proxy-authorization",
                "string_match": { "exact": proxy_authorization_value(token) }
            }]),
        );
    }
}

fn route_match_with_proxy_auth(mut match_json: Value, proxy_auth_token: Option<&str>) -> Value {
    add_proxy_auth_match(&mut match_json, proxy_auth_token);
    match_json
}

fn domains_for_credential_host(match_host: &str, routes: &[EgressCredentialRoute]) -> Vec<String> {
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

/// Group credential routes by their placeholder `match_host`, returning a stable
/// (host-sorted) list with routes ordered longest-`match_prefix`-first so more
/// specific prefixes are matched before `/`.
fn group_credentials_by_host(
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

#[derive(Debug, Clone)]
struct VersionedChange {
    version: u64,
    type_url: String,
    changes: Vec<Change>,
}

const XDS_CHANGE_LOG_LIMIT: usize = 4096;

/// Upper bound on outstanding response nonces tracked per ADS stream. Envoy
/// acknowledges nonces in order, so a stream normally has only a couple in
/// flight; this cap is a safety net against unbounded growth if some pushes are
/// never ACK'd (e.g. Envoy disconnects mid-flight). Eviction is FIFO.
const XDS_NONCE_TRACK_LIMIT: usize = 512;

/// Bounded, insertion-ordered map from response nonce to the
/// `(type_url, version, resource_names)` it carried. Used per ADS stream to map
/// an Envoy ACK/NACK back to the sandboxes it applied to. Entries are removed
/// when consumed by an ACK/NACK and FIFO-evicted once the cap is exceeded, so a
/// long-lived stream cannot leak nonce state.
#[derive(Default)]
struct NonceTracker {
    map: HashMap<String, (String, u64, Vec<String>)>,
    order: std::collections::VecDeque<String>,
}

impl NonceTracker {
    fn insert(&mut self, nonce: String, entry: (String, u64, Vec<String>)) {
        if self.map.insert(nonce.clone(), entry).is_none() {
            self.order.push_back(nonce);
        }
        while self.order.len() > XDS_NONCE_TRACK_LIMIT {
            if let Some(old) = self.order.pop_front() {
                self.map.remove(&old);
            }
        }
    }

    /// Remove and return the entry for `nonce`. Consuming on ACK/NACK is what
    /// keeps the tracker bounded in the common (fully-acknowledged) case.
    fn take(&mut self, nonce: &str) -> Option<(String, u64, Vec<String>)> {
        let entry = self.map.remove(nonce);
        if entry.is_some() {
            self.order.retain(|n| n != nonce);
        }
        entry
    }
}

/// Shared xDS state: the authoritative resource sets (per type URL) + version.
struct XdsState {
    /// type_url → (resource name → encoded resource). Holds both Clusters and
    /// Listeners so the single ADS stream can serve CDS + LDS.
    resources: HashMap<String, HashMap<String, Any>>,
    /// Monotonic version stamped into each Delta response.
    version: u64,
    /// Recent per-version changes used by active Delta ADS streams. This keeps
    /// ordinary updates incremental instead of cloning and sending the full LDS
    /// and CDS world every time one sandbox changes.
    change_log: Vec<VersionedChange>,
}

#[derive(Debug, Clone)]
enum XdsApplyStatus {
    Pending { min_version: u64 },
    Acked,
    Nacked(String),
}

impl XdsState {
    fn new() -> Self {
        Self {
            resources: HashMap::new(),
            version: 0,
            change_log: Vec::new(),
        }
    }

    fn entry(&mut self, type_url: &str) -> &mut HashMap<String, Any> {
        self.resources.entry(type_url.to_string()).or_default()
    }

    fn snapshot_type(&self, type_url: &str) -> HashMap<String, Any> {
        self.resources.get(type_url).cloned().unwrap_or_default()
    }

    fn changes_since(&self, version: u64) -> Option<Vec<VersionedChange>> {
        let Some(first) = self.change_log.first() else {
            return Some(Vec::new());
        };
        if version < first.version.saturating_sub(1) {
            return None;
        }
        Some(
            self.change_log
                .iter()
                .filter(|change| change.version > version)
                .cloned()
                .collect(),
        )
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
    /// Optional DB handle attached on orchestrator startup for ACK/NACK status
    /// persistence. Kept optional so unit tests and filesystem mode do not need a DB.
    db_pool: Arc<Mutex<Option<PgPool>>>,
    apply_status: Arc<Mutex<HashMap<Uuid, XdsApplyStatus>>>,
    status_notify: watch::Sender<u64>,
}

impl DeltaXdsServer {
    pub fn new() -> Arc<Self> {
        let (notify, _rx) = watch::channel(0u64);
        let (status_notify, _status_rx) = watch::channel(0u64);
        Arc::new(Self {
            state: Arc::new(Mutex::new(XdsState::new())),
            notify,
            db_pool: Arc::new(Mutex::new(None)),
            apply_status: Arc::new(Mutex::new(HashMap::new())),
            status_notify,
        })
    }

    pub async fn attach_db_pool(&self, pool: PgPool) {
        *self.db_pool.lock().await = Some(pool);
    }

    pub async fn wait_for_sandbox_ack(
        &self,
        sandbox_id: Uuid,
        timeout: Duration,
    ) -> anyhow::Result<()> {
        let mut rx = self.status_notify.subscribe();
        let deadline = tokio::time::Instant::now() + timeout;
        loop {
            match self.apply_status.lock().await.get(&sandbox_id).cloned() {
                Some(XdsApplyStatus::Acked) => return Ok(()),
                Some(XdsApplyStatus::Nacked(reason)) => {
                    anyhow::bail!("Envoy NACK'd xDS update for sandbox {sandbox_id}: {reason}")
                }
                Some(XdsApplyStatus::Pending { .. }) | None => {}
            }
            let now = tokio::time::Instant::now();
            if now >= deadline {
                anyhow::bail!("timed out waiting for Envoy xDS ACK for sandbox {sandbox_id}");
            }
            if tokio::time::timeout_at(deadline, rx.changed())
                .await
                .is_err()
            {
                anyhow::bail!("timed out waiting for Envoy xDS ACK for sandbox {sandbox_id}");
            }
        }
    }

    /// Drop any retained ACK/NACK status for a torn-down sandbox. Called when a
    /// sandbox's listeners/clusters are removed so `apply_status` cannot grow
    /// unboundedly over the orchestrator's lifetime (one entry per sandbox ever
    /// created otherwise).
    async fn forget_sandbox(&self, sandbox_id: Uuid) {
        self.apply_status.lock().await.remove(&sandbox_id);
    }

    /// Apply a batch of changes to one resource type and wake the stream.
    async fn apply(
        &self,
        type_url: &str,
        changes: Vec<Change>,
        pending_sandboxes: Vec<Uuid>,
    ) -> u64 {
        self.apply_batch(vec![(type_url.to_string(), changes)], pending_sandboxes)
            .await
    }

    /// Apply changes across several resource types as one atomic update: a single
    /// version tick, one change-log group per non-empty type (in the given order,
    /// so callers pass Clusters before Listeners for make-before-break), and one
    /// `notify` wake. This lets a sandbox's CDS + LDS update ride a single version
    /// instead of two, halving stream wakeups and re-pushes under load.
    async fn apply_batch(
        &self,
        groups: Vec<(String, Vec<Change>)>,
        pending_sandboxes: Vec<Uuid>,
    ) -> u64 {
        let groups: Vec<(String, Vec<Change>)> = groups
            .into_iter()
            .filter(|(_, changes)| !changes.is_empty())
            .collect();
        if groups.is_empty() {
            return *self.notify.borrow();
        }
        let mut st = self.state.lock().await;
        st.version += 1;
        let version = st.version;
        for (type_url, changes) in &groups {
            {
                let map = st.entry(type_url);
                for change in changes {
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
            st.change_log.push(VersionedChange {
                version,
                type_url: type_url.clone(),
                changes: changes.clone(),
            });
        }
        if st.change_log.len() > XDS_CHANGE_LOG_LIMIT {
            let remove_count = st.change_log.len() - XDS_CHANGE_LOG_LIMIT;
            st.change_log.drain(..remove_count);
        }
        drop(st);
        if !pending_sandboxes.is_empty() {
            let mut statuses = self.apply_status.lock().await;
            for sandbox_id in pending_sandboxes {
                statuses.insert(
                    sandbox_id,
                    XdsApplyStatus::Pending {
                        min_version: version,
                    },
                );
            }
            // Hoist the current value into a local before send(): holding the
            // watch read guard from borrow() across send()'s write acquisition
            // on the same channel self-deadlocks (read-then-write on one thread).
            let next_status_version = *self.status_notify.borrow() + 1;
            let _ = self.status_notify.send(next_status_version);
        }
        // Ignore send error: no receiver means no Envoy connected yet; the
        // change is already recorded and delivered as initial state on connect.
        let _ = self.notify.send(version);
        version
    }
}

#[async_trait]
impl LdsBackend for GrpcLds {
    async fn upsert(&self, specs: Vec<ListenerSpec>) -> anyhow::Result<()> {
        let mut changes = Vec::with_capacity(specs.len());
        let mut pending_sandboxes = Vec::new();
        for spec in specs {
            if !pending_sandboxes.contains(&spec.sandbox_id) {
                pending_sandboxes.push(spec.sandbox_id);
            }
            let any = encode_listener_any(&spec)?;
            changes.push(Change::Upsert(spec.resource_name(), any));
        }
        self.server
            .apply(LISTENER_TYPE_URL, changes, pending_sandboxes)
            .await;
        Ok(())
    }

    async fn remove(&self, names: Vec<String>) -> anyhow::Result<()> {
        let changes = names.into_iter().map(Change::Remove).collect();
        self.server.apply(LISTENER_TYPE_URL, changes, vec![]).await;
        Ok(())
    }

    async fn replace_all(&self, specs: Vec<ListenerSpec>) -> anyhow::Result<()> {
        // Compute the delta against the current world: upsert everything in
        // `specs`, remove anything no longer present.
        let mut new_names = std::collections::HashSet::new();
        let mut changes = Vec::new();
        let mut pending_sandboxes = Vec::new();
        for spec in &specs {
            let name = spec.resource_name();
            new_names.insert(name.clone());
            if !pending_sandboxes.contains(&spec.sandbox_id) {
                pending_sandboxes.push(spec.sandbox_id);
            }
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
        self.server
            .apply(LISTENER_TYPE_URL, changes, pending_sandboxes)
            .await;
        Ok(())
    }

    async fn wait_for_sandbox_ack(
        &self,
        sandbox_id: Uuid,
        timeout: Duration,
    ) -> anyhow::Result<()> {
        self.server.wait_for_sandbox_ack(sandbox_id, timeout).await
    }

    async fn forget_sandbox(&self, sandbox_id: Uuid) {
        self.server.forget_sandbox(sandbox_id).await;
    }

    async fn apply_sandbox_batch(
        &self,
        clusters: Vec<ClusterSpec>,
        listeners: Vec<ListenerSpec>,
        cluster_prefix: String,
    ) -> anyhow::Result<bool> {
        // Cluster changes: upsert the new set, remove any prior clusters under
        // this sandbox's prefix that are no longer present (credentials removed
        // since the last refresh).
        let mut new_cluster_names = std::collections::HashSet::new();
        let mut cluster_changes = Vec::with_capacity(clusters.len());
        for spec in &clusters {
            new_cluster_names.insert(spec.name.clone());
            cluster_changes.push(Change::Upsert(spec.name.clone(), encode_cluster_any(spec)?));
        }
        // Listener changes: upsert this sandbox's listeners and collect the
        // sandboxes they belong to for pending/ACK tracking.
        let mut listener_changes = Vec::with_capacity(listeners.len());
        let mut pending_sandboxes = Vec::new();
        for spec in &listeners {
            if !pending_sandboxes.contains(&spec.sandbox_id) {
                pending_sandboxes.push(spec.sandbox_id);
            }
            listener_changes.push(Change::Upsert(
                spec.resource_name(),
                encode_listener_any(spec)?,
            ));
        }
        {
            let st = self.server.state.lock().await;
            for existing in st.snapshot_type(CLUSTER_TYPE_URL).keys() {
                if existing.starts_with(&cluster_prefix) && !new_cluster_names.contains(existing) {
                    cluster_changes.push(Change::Remove(existing.clone()));
                }
            }
        }
        // One atomic version tick, Clusters before Listeners (make-before-break).
        self.server
            .apply_batch(
                vec![
                    (CLUSTER_TYPE_URL.to_string(), cluster_changes),
                    (LISTENER_TYPE_URL.to_string(), listener_changes),
                ],
                pending_sandboxes,
            )
            .await;
        Ok(true)
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
        self.server.apply(CLUSTER_TYPE_URL, changes, vec![]).await;
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
        self.server.apply(CLUSTER_TYPE_URL, changes, vec![]).await;
        Ok(())
    }

    async fn replace_by_prefix(&self, prefix: &str, specs: Vec<ClusterSpec>) -> anyhow::Result<()> {
        let mut new_names = std::collections::HashSet::new();
        let mut changes = Vec::new();
        for spec in &specs {
            new_names.insert(spec.name.clone());
            changes.push(Change::Upsert(spec.name.clone(), encode_cluster_any(spec)?));
        }
        {
            let st = self.server.state.lock().await;
            for existing in st.snapshot_type(CLUSTER_TYPE_URL).keys() {
                if existing.starts_with(prefix) && !new_names.contains(existing) {
                    changes.push(Change::Remove(existing.clone()));
                }
            }
        }
        self.server.apply(CLUSTER_TYPE_URL, changes, vec![]).await;
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
        self.server.apply(CLUSTER_TYPE_URL, changes, vec![]).await;
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
        let xds_status_handle = self.status_handle();

        // Resource types this aggregated stream serves. Order matters: Clusters
        // (CDS) must be pushed before Listeners (LDS) so a listener's routes
        // never reference a not-yet-known cluster (make-before-break).
        const TYPES: [&str; 2] = [CLUSTER_TYPE_URL, LISTENER_TYPE_URL];

        let task = async move {
            // Track response nonce -> resource names so ACK/NACK can be mapped
            // back to sandbox policy rows. Bounded + consumed on ACK/NACK so a
            // long-lived stream never leaks nonce state.
            let mut nonce_resources = NonceTracker::default();
            // Track resource types Envoy has subscribed to and what we have sent
            // for each type. Delta ADS is subscription driven: sending resources
            // before Envoy asks for a type can be ignored by Envoy and leaves
            // later listener updates unapplied.
            let mut subscribed: std::collections::HashSet<String> =
                std::collections::HashSet::new();
            let mut sent: HashMap<String, std::collections::HashSet<String>> = HashMap::new();
            let mut last_seen_version = *notify_rx.borrow_and_update();

            loop {
                tokio::select! {
                    // Drain ACK/NACK and subscription messages. For Delta ADS we
                    // only send a resource type after Envoy subscribes to it.
                    msg = inbound.message() => {
                        match msg {
                            Ok(Some(req)) => {
                                if !req.response_nonce.is_empty() {
                                    let (acked_type_url, acked_version, resources) = nonce_resources
                                        .take(&req.response_nonce)
                                        .unwrap_or_default();
                                    if let Some(err) = &req.error_detail {
                                        warn!(code = err.code, message = %err.message, nonce = %req.response_nonce, "Envoy NACK'd xDS update");
                                        xds_status_handle.persist_nack(resources, acked_version, err.message.clone()).await;
                                    } else if acked_type_url == LISTENER_TYPE_URL {
                                        xds_status_handle.persist_ack(resources, acked_version).await;
                                    }
                                }
                                if TYPES.contains(&req.type_url.as_str()) && subscribed.insert(req.type_url.clone()) {
                                    let version = *notify_rx.borrow();
                                    let snap = state_handle.snapshot_type(&req.type_url).await;
                                    let (resp, current) = delta_response_from_snapshot(
                                        req.type_url.clone(),
                                        version,
                                        snap,
                                        &mut nonce_resources,
                                    );
                                    sent.insert(req.type_url, current);
                                    if tx.send(Ok(resp)).await.is_err() {
                                        break;
                                    }
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

                        let Some(changes) = state_handle.changes_since(last_seen_version).await else {
                            // The stream fell behind the bounded change log. Fall back to
                            // one full snapshot per subscribed type so Envoy catches up.
                            let mut closed = false;
                            for type_url in TYPES {
                                if !subscribed.contains(type_url) {
                                    continue;
                                }
                                let snap = state_handle.snapshot_type(type_url).await;
                                let (resp, current) = delta_response_from_snapshot(
                                    type_url.to_string(),
                                    version,
                                    snap,
                                    &mut nonce_resources,
                                );
                                sent.insert(type_url.to_string(), current);
                                if tx.send(Ok(resp)).await.is_err() {
                                    closed = true;
                                    break;
                                }
                            }
                            if closed {
                                break;
                            }
                            last_seen_version = version;
                            continue;
                        };

                        // Emit actual deltas only, CDS before LDS for each version.
                        let mut closed = false;
                        for change in changes {
                            if !subscribed.contains(change.type_url.as_str()) {
                                continue;
                            }
                            let (resp, removed) =
                                delta_response_from_change(change, &mut nonce_resources);
                            let prev = sent.entry(resp.type_url.clone()).or_default();
                            for resource in &resp.resources {
                                prev.insert(resource.name.clone());
                            }
                            for name in &removed {
                                prev.remove(name);
                            }
                            if tx.send(Ok(resp)).await.is_err() {
                                closed = true;
                                break;
                            }
                        }
                        if closed {
                            break;
                        }
                        last_seen_version = version;
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

struct XdsStatusHandle {
    db_pool: Arc<Mutex<Option<PgPool>>>,
    apply_status: Arc<Mutex<HashMap<Uuid, XdsApplyStatus>>>,
    status_notify: watch::Sender<u64>,
}

impl XdsStatusHandle {
    async fn persist_ack(&self, resources: Vec<String>, acked_version: u64) {
        let sandbox_ids = sandbox_ids_from_xds_resources(&resources);
        let mut acked_sandboxes = Vec::new();
        if !sandbox_ids.is_empty() {
            let mut statuses = self.apply_status.lock().await;
            for sandbox_id in &sandbox_ids {
                let should_ack = match statuses.get(sandbox_id) {
                    Some(XdsApplyStatus::Pending { min_version }) => acked_version >= *min_version,
                    Some(XdsApplyStatus::Acked) => false,
                    Some(XdsApplyStatus::Nacked(_)) | None => false,
                };
                if should_ack {
                    statuses.insert(*sandbox_id, XdsApplyStatus::Acked);
                    acked_sandboxes.push(*sandbox_id);
                }
            }
            if !acked_sandboxes.is_empty() {
                let next_status_version = *self.status_notify.borrow() + 1;
                let _ = self.status_notify.send(next_status_version);
            }
        }
        let Some(pool) = self.db_pool.lock().await.clone() else {
            return;
        };
        for sandbox_id in acked_sandboxes {
            if let Err(e) =
                crate::db::queries::mark_sandbox_network_policy_acked(&pool, sandbox_id).await
            {
                warn!(sandbox_id = %sandbox_id, error = %e, "Failed to persist xDS ACK status");
            }
        }
    }

    async fn persist_nack(&self, resources: Vec<String>, nacked_version: u64, reason: String) {
        let sandbox_ids = sandbox_ids_from_xds_resources(&resources);
        let mut nacked_sandboxes = Vec::new();
        if !sandbox_ids.is_empty() {
            let mut statuses = self.apply_status.lock().await;
            for sandbox_id in &sandbox_ids {
                let should_nack = match statuses.get(sandbox_id) {
                    Some(XdsApplyStatus::Pending { min_version }) => nacked_version >= *min_version,
                    Some(XdsApplyStatus::Acked) | Some(XdsApplyStatus::Nacked(_)) | None => false,
                };
                if should_nack {
                    statuses.insert(*sandbox_id, XdsApplyStatus::Nacked(reason.clone()));
                    nacked_sandboxes.push(*sandbox_id);
                }
            }
            if !nacked_sandboxes.is_empty() {
                let next_status_version = *self.status_notify.borrow() + 1;
                let _ = self.status_notify.send(next_status_version);
            }
        }
        let Some(pool) = self.db_pool.lock().await.clone() else {
            return;
        };
        for sandbox_id in nacked_sandboxes {
            if let Err(e) =
                crate::db::queries::record_network_policy_failure(&pool, sandbox_id, &reason).await
            {
                warn!(sandbox_id = %sandbox_id, error = %e, "Failed to persist xDS NACK status");
            }
        }
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

    async fn changes_since(&self, version: u64) -> Option<Vec<VersionedChange>> {
        self.state.lock().await.changes_since(version)
    }
}

fn delta_response_from_snapshot(
    type_url: String,
    version: u64,
    snap: HashMap<String, Any>,
    nonce_resources: &mut NonceTracker,
) -> (DeltaDiscoveryResponse, std::collections::HashSet<String>) {
    let current: std::collections::HashSet<String> = snap.keys().cloned().collect();
    let resources: Vec<Resource> = snap
        .into_iter()
        .map(|(name, any)| Resource {
            name,
            version: version.to_string(),
            resource: Some(any),
            ..Default::default()
        })
        .collect();
    let nonce = format!("n-{type_url}-{version}-snapshot");
    nonce_resources.insert(
        nonce.clone(),
        (
            type_url.clone(),
            version,
            resources
                .iter()
                .map(|resource| resource.name.clone())
                .collect(),
        ),
    );
    (
        DeltaDiscoveryResponse {
            system_version_info: version.to_string(),
            resources,
            removed_resources: vec![],
            type_url,
            nonce,
            ..Default::default()
        },
        current,
    )
}

fn delta_response_from_change(
    change: VersionedChange,
    nonce_resources: &mut NonceTracker,
) -> (DeltaDiscoveryResponse, Vec<String>) {
    let mut removed = Vec::new();
    let mut resources = Vec::new();
    for item in change.changes {
        match item {
            Change::Upsert(name, any) => {
                resources.push(Resource {
                    name,
                    version: change.version.to_string(),
                    resource: Some(any),
                    ..Default::default()
                });
            }
            Change::Remove(name) => {
                removed.push(name);
            }
        }
    }
    let nonce = format!("n-{}-{}", change.type_url, change.version);
    nonce_resources.insert(
        nonce.clone(),
        (
            change.type_url.clone(),
            change.version,
            resources
                .iter()
                .map(|resource| resource.name.clone())
                .chain(removed.iter().cloned())
                .collect(),
        ),
    );
    (
        DeltaDiscoveryResponse {
            system_version_info: change.version.to_string(),
            resources,
            removed_resources: removed.clone(),
            type_url: change.type_url,
            nonce,
            ..Default::default()
        },
        removed,
    )
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

    fn status_handle(&self) -> XdsStatusHandle {
        XdsStatusHandle {
            db_pool: self.db_pool.clone(),
            apply_status: self.apply_status.clone(),
            status_notify: self.status_notify.clone(),
        }
    }
}

fn sandbox_ids_from_xds_resources(resource_names: &[String]) -> Vec<Uuid> {
    let mut ids = Vec::new();
    for name in resource_names {
        if let Some(id) = sandbox_id_from_xds_resource(name) {
            if !ids.contains(&id) {
                ids.push(id);
            }
        }
    }
    ids
}

fn sandbox_id_from_xds_resource(name: &str) -> Option<Uuid> {
    let candidate = if let Some(listener_id) = name.strip_suffix("_http") {
        listener_id
    } else if let Some(cluster_name) = name.strip_prefix("up_") {
        cluster_name.split_once('_')?.0
    } else {
        return None;
    };
    Uuid::parse_str(candidate).ok()
}

// ---------------------------------------------------------------------------
// Typed-protobuf listener rendering (gRPC backend)
// ---------------------------------------------------------------------------

/// Encode a [`ListenerSpec`] into a `google.protobuf.Any` wrapping a typed
/// Envoy Listener, for Delta xDS delivery.
fn encode_listener_any(spec: &ListenerSpec) -> anyhow::Result<Any> {
    use envoy_types::pb::envoy::config::listener::v3::Listener;

    let listener: Listener = match spec.kind {
        ListenerKind::Http => build_http_listener_proto(
            &spec.sandbox_id,
            &spec.allowed_hosts,
            &spec.credentials,
            spec.proxy_auth_token.as_deref(),
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
            cluster::DiscoveryType::LogicalDns as i32,
        )),
        // Accelerate DNS refresh so a freshly-created cluster resolves within
        // ~0.5-2s (vs the default ~5.3s). dns_failure_refresh_rate specifically
        // handles the case where the first DNS lookup fails — without it,
        // LOGICAL_DNS would wait a full dns_refresh_rate cycle before retrying.
        dns_refresh_rate: Some(envoy_types::pb::google::protobuf::Duration {
            seconds: 2,
            nanos: 0,
        }),
        dns_failure_refresh_rate: Some(cluster::RefreshRate {
            base_interval: Some(envoy_types::pb::google::protobuf::Duration {
                seconds: 0,
                nanos: 500_000_000, // 0.5s
            }),
            max_interval: Some(envoy_types::pb::google::protobuf::Duration {
                seconds: 2,
                nanos: 0,
            }),
        }),
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

fn build_http_listener_proto(
    sandbox_id: &Uuid,
    allowed_hosts: &[String],
    credentials: &[EgressCredentialRoute],
    proxy_auth_token: Option<&str>,
) -> envoy_types::pb::envoy::config::listener::v3::Listener {
    use envoy_types::pb::envoy::config::accesslog::v3::{access_log, AccessLog};
    use envoy_types::pb::envoy::config::cluster::v3::cluster::DnsLookupFamily;
    use envoy_types::pb::envoy::config::core::v3::{
        address, substitution_format_string, Address, Http1ProtocolOptions, Pipe,
        SubstitutionFormatString,
    };
    use envoy_types::pb::envoy::config::listener::v3::{filter, Filter, FilterChain, Listener};
    use envoy_types::pb::envoy::config::route::v3::RouteConfiguration;
    use envoy_types::pb::envoy::extensions::access_loggers::stream::v3::{
        stdout_access_log, StdoutAccessLog,
    };
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
                dns_lookup_family: DnsLookupFamily::V4Only as i32,
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
        access_log: vec![AccessLog {
            name: "envoy.access_loggers.stdout".to_string(),
            config_type: Some(access_log::ConfigType::TypedConfig(pack_any(
                "type.googleapis.com/envoy.extensions.access_loggers.stream.v3.StdoutAccessLog",
                &StdoutAccessLog {
                    access_log_format: Some(stdout_access_log::AccessLogFormat::LogFormat(
                        SubstitutionFormatString {
                            format: Some(substitution_format_string::Format::JsonFormat(
                                access_log_json_format(format!("{sandbox_id}_http")),
                            )),
                            ..Default::default()
                        },
                    )),
                },
            ))),
            ..Default::default()
        }],
        // Disable stream idle timeout so long-lived connections (SSE / streaming
        // LLM responses / MCP) are not killed by the default 5-minute idle limit.
        stream_idle_timeout: Some(envoy_types::pb::google::protobuf::Duration { seconds: 0, nanos: 0 }),
        upgrade_configs: vec![http_connection_manager::UpgradeConfig {
            upgrade_type: "CONNECT".to_string(),
            ..Default::default()
        }],
        route_specifier: Some(http_connection_manager::RouteSpecifier::RouteConfig(
            RouteConfiguration {
                virtual_hosts: build_virtual_hosts_proto(
                    allowed_hosts,
                    credentials,
                    proxy_auth_token,
                ),
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
                // See the gRPC listener pipe above for why this is 0666 at
                // creation time. The HTTP proxy still requires the per-sandbox
                // proxy auth token before credential-bearing routes are usable.
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
    credentials: &[EgressCredentialRoute],
    proxy_auth_token: Option<&str>,
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
                let mut headers_to_remove = if r.remove_headers.is_empty() {
                    auth_headers_to_remove(&r.inject_headers)
                } else {
                    r.remove_headers.clone()
                };
                if !headers_to_remove
                    .iter()
                    .any(|h| h.eq_ignore_ascii_case("proxy-authorization"))
                {
                    headers_to_remove.push("proxy-authorization".to_string());
                }
                let path_specifier = if r.exact_path {
                    route_match::PathSpecifier::Path(r.match_prefix.clone())
                } else {
                    route_match::PathSpecifier::Prefix(r.match_prefix.clone())
                };
                let is_transparent = r.exposure == EgressExposure::Transparent;
                let prefix_rewrite = if is_transparent || r.exact_path {
                    String::new()
                } else {
                    route_prefix_rewrite(r)
                };
                let host_rewrite = if is_transparent {
                    None
                } else {
                    Some(route_action::HostRewriteSpecifier::HostRewriteLiteral(
                        r.upstream_host.clone(),
                    ))
                };
                Route {
                    r#match: Some(RouteMatch {
                        path_specifier: Some(path_specifier),
                        headers: proxy_auth_headers_proto(proxy_auth_token),
                        ..Default::default()
                    }),
                    action: Some(route::Action::Route(RouteAction {
                        cluster_specifier: Some(route_action::ClusterSpecifier::Cluster(
                            r.cluster_name.clone(),
                        )),
                        host_rewrite_specifier: host_rewrite,
                        prefix_rewrite,
                        // Disable the default 15s route timeout — streaming
                        // responses (LLM, SSE MCP) can run for minutes.
                        timeout: Some(envoy_types::pb::google::protobuf::Duration {
                            seconds: 0,
                            nanos: 0,
                        }),
                        retry_policy: Some(
                            envoy_types::pb::envoy::config::route::v3::RetryPolicy {
                                retry_on: "5xx,reset,connect-failure".to_string(),
                                num_retries: Some(envoy_types::pb::google::protobuf::UInt32Value {
                                    value: 2,
                                }),
                                ..Default::default()
                            },
                        ),
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
                headers: proxy_auth_headers_proto(proxy_auth_token),
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
            request_headers_to_remove: vec!["proxy-authorization".to_string()],
            ..Default::default()
        };

        // Plain prefix "/" route → dynamic_forward_proxy.
        let prefix_route = Route {
            r#match: Some(RouteMatch {
                path_specifier: Some(route_match::PathSpecifier::Prefix("/".to_string())),
                headers: proxy_auth_headers_proto(proxy_auth_token),
                ..Default::default()
            }),
            action: Some(route::Action::Route(RouteAction {
                cluster_specifier: Some(route_action::ClusterSpecifier::Cluster(
                    "dynamic_forward_proxy".to_string(),
                )),
                timeout: Some(envoy_types::pb::google::protobuf::Duration {
                    seconds: 0,
                    nanos: 0,
                }),
                retry_policy: Some(envoy_types::pb::envoy::config::route::v3::RetryPolicy {
                    retry_on: "5xx,reset,connect-failure".to_string(),
                    num_retries: Some(envoy_types::pb::google::protobuf::UInt32Value { value: 2 }),
                    ..Default::default()
                }),
                ..Default::default()
            })),
            request_headers_to_remove: vec!["proxy-authorization".to_string()],
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

fn proxy_auth_headers_proto(
    proxy_auth_token: Option<&str>,
) -> Vec<envoy_types::pb::envoy::config::route::v3::HeaderMatcher> {
    use envoy_types::pb::envoy::config::route::v3::{header_matcher, HeaderMatcher};
    use envoy_types::pb::envoy::r#type::matcher::v3::{string_matcher, StringMatcher};

    let Some(token) = proxy_auth_token.filter(|token| !token.is_empty()) else {
        return vec![];
    };
    vec![HeaderMatcher {
        name: "proxy-authorization".to_string(),
        header_match_specifier: Some(header_matcher::HeaderMatchSpecifier::StringMatch(
            StringMatcher {
                match_pattern: Some(string_matcher::MatchPattern::Exact(
                    proxy_authorization_value(token),
                )),
                ..Default::default()
            },
        )),
        ..Default::default()
    }]
}

// ---------------------------------------------------------------------------
// Shared Envoy bind-mount file write (used by filesystem LDS/CDS)
// ---------------------------------------------------------------------------

async fn write_config_file(
    config_dir: &str,
    relative_path: &str,
    content: &str,
) -> anyhow::Result<()> {
    let path = std::path::Path::new(config_dir).join(relative_path);
    if let Some(parent) = path.parent() {
        tokio::fs::create_dir_all(parent).await?;
    }
    let tmp = path.with_extension("tmp");
    tokio::fs::write(&tmp, content).await?;
    tokio::fs::rename(&tmp, &path).await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use prost::Message;

    /// Regression: `DeltaXdsServer::apply` must not self-deadlock when it records
    /// pending sandbox status. It previously called
    /// `status_notify.send(*status_notify.borrow() + 1)`, holding the watch read
    /// guard from `borrow()` across `send()`'s write acquisition on the same
    /// channel — a permanent single-thread read-then-write deadlock that only ran
    /// in gRPC xDS mode (the LDS listener push carries a non-empty
    /// `pending_sandboxes`). It wedged the global `config_apply_lock` and made
    /// every sandbox's networking reconcile time out, so Envoy never received the
    /// per-sandbox listener and `/sockets/<id>/http.sock` was never created.
    #[tokio::test]
    async fn grpc_lds_upsert_with_pending_status_does_not_deadlock() {
        let server = DeltaXdsServer::new();
        let lds = GrpcLds::new(server.clone());
        let mut listener = spec(ListenerKind::Http, &["example.com"]);
        listener.sandbox_id = Uuid::from_u128(1);

        // Before the fix this future never resolves; bound it so the test fails
        // as a timeout instead of hanging the whole test binary.
        let result = tokio::time::timeout(
            std::time::Duration::from_secs(5),
            lds.upsert(vec![listener]),
        )
        .await;

        assert!(
            result.is_ok(),
            "GrpcLds::upsert deadlocked while recording pending xDS status"
        );
        result.unwrap().expect("upsert should succeed");

        // The pending status was recorded for the sandbox.
        let statuses = server.apply_status.lock().await;
        assert!(matches!(
            statuses.get(&Uuid::from_u128(1)),
            Some(XdsApplyStatus::Pending { .. })
        ));
    }

    /// `forget_sandbox` must drop retained ACK/NACK bookkeeping so `apply_status`
    /// stays bounded across a sandbox's lifecycle (create → teardown).
    #[tokio::test]
    async fn forget_sandbox_clears_apply_status() {
        let server = DeltaXdsServer::new();
        let lds = GrpcLds::new(server.clone());
        let sandbox = Uuid::from_u128(7);
        let mut listener = spec(ListenerKind::Http, &["example.com"]);
        listener.sandbox_id = sandbox;

        lds.upsert(vec![listener]).await.unwrap();
        assert!(server.apply_status.lock().await.contains_key(&sandbox));

        lds.forget_sandbox(sandbox).await;
        assert!(
            !server.apply_status.lock().await.contains_key(&sandbox),
            "apply_status must be cleared on teardown"
        );
    }

    /// The nonce tracker is bounded and FIFO-evicts oldest entries, so a stream
    /// that pushes far more updates than Envoy ACKs cannot leak nonce state.
    #[test]
    fn nonce_tracker_is_bounded_and_fifo() {
        let mut tracker = NonceTracker::default();
        for i in 0..(XDS_NONCE_TRACK_LIMIT + 50) {
            tracker.insert(format!("n-{i}"), ("t".to_string(), i as u64, vec![]));
        }
        assert!(tracker.map.len() <= XDS_NONCE_TRACK_LIMIT);
        assert_eq!(tracker.map.len(), tracker.order.len());
        // Oldest were evicted; a recent one survives and is consumed on take().
        let recent = format!("n-{}", XDS_NONCE_TRACK_LIMIT + 49);
        assert!(tracker.take(&recent).is_some());
        assert!(tracker.take(&recent).is_none(), "take must consume");
        assert!(tracker.take("n-0").is_none(), "oldest was evicted");
    }

    /// `apply_sandbox_batch` applies clusters and listeners under ONE version
    /// tick (single stream wake) with clusters recorded before listeners, and
    /// removes stale clusters under the sandbox's prefix.
    #[tokio::test]
    async fn apply_sandbox_batch_is_atomic_and_ordered() {
        let server = DeltaXdsServer::new();
        let lds = GrpcLds::new(server.clone());
        let sandbox = Uuid::from_u128(9);
        let prefix = format!("up_{sandbox}_");

        // Seed a stale cluster under the prefix that should be pruned.
        server
            .apply(
                CLUSTER_TYPE_URL,
                vec![Change::Upsert(
                    format!("{prefix}stale_443"),
                    encode_cluster_any(&ClusterSpec {
                        name: format!("{prefix}stale_443"),
                        upstream_host: "old.example.com".to_string(),
                        upstream_port: 443,
                        upstream_tls: true,
                    })
                    .unwrap(),
                )],
                vec![],
            )
            .await;
        let version_before = server.state.lock().await.version;

        let clusters = vec![ClusterSpec {
            name: format!("{prefix}new_443"),
            upstream_host: "new.example.com".to_string(),
            upstream_port: 443,
            upstream_tls: true,
        }];
        let mut listener = spec(ListenerKind::Http, &["example.com"]);
        listener.sandbox_id = sandbox;

        let applied = lds
            .apply_sandbox_batch(clusters, vec![listener], prefix.clone())
            .await
            .unwrap();
        assert!(applied, "grpc backend must apply the batch");

        let st = server.state.lock().await;
        // Exactly one version tick for the combined CDS+LDS update.
        assert_eq!(st.version, version_before + 1);
        // Both change-log groups share that single version.
        let batch: Vec<&VersionedChange> = st
            .change_log
            .iter()
            .filter(|c| c.version == st.version)
            .collect();
        assert_eq!(batch.len(), 2, "one CDS group + one LDS group");
        assert_eq!(batch[0].type_url, CLUSTER_TYPE_URL, "CDS before LDS");
        assert_eq!(batch[1].type_url, LISTENER_TYPE_URL);
        // Stale cluster pruned, new cluster present, listener present.
        let clusters_now = st.snapshot_type(CLUSTER_TYPE_URL);
        assert!(clusters_now.contains_key(&format!("{prefix}new_443")));
        assert!(!clusters_now.contains_key(&format!("{prefix}stale_443")));
        assert!(st
            .snapshot_type(LISTENER_TYPE_URL)
            .contains_key(&format!("{sandbox}_http")));
    }

    fn spec(kind: ListenerKind, hosts: &[&str]) -> ListenerSpec {
        ListenerSpec {
            sandbox_id: Uuid::nil(),
            kind,
            allowed_hosts: hosts.iter().map(|s| s.to_string()).collect(),
            credentials: vec![],
            proxy_auth_token: None,
        }
    }

    fn spec_with_creds(
        kind: ListenerKind,
        hosts: &[&str],
        creds: Vec<EgressCredentialRoute>,
    ) -> ListenerSpec {
        ListenerSpec {
            sandbox_id: Uuid::nil(),
            kind,
            allowed_hosts: hosts.iter().map(|s| s.to_string()).collect(),
            credentials: creds,
            proxy_auth_token: None,
        }
    }

    fn llm_route() -> EgressCredentialRoute {
        EgressCredentialRoute {
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
            cluster_name: "dynamic_forward_proxy_tls".to_string(),
            inject_headers: vec![("authorization".to_string(), "Bearer sk-secret".to_string())],
            remove_headers: vec![],
        }
    }

    fn mcp_route(name: &str) -> EgressCredentialRoute {
        EgressCredentialRoute {
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
            cluster_name: "dynamic_forward_proxy_tls".to_string(),
            inject_headers: vec![("authorization".to_string(), "Bearer tok".to_string())],
            remove_headers: vec![],
        }
    }

    #[test]
    fn listener_resource_names_use_http_suffix() {
        assert_eq!(
            spec(ListenerKind::Http, &[]).resource_name(),
            "00000000-0000-0000-0000-000000000000_http"
        );
    }

    #[test]
    fn xds_resource_names_map_back_to_sandbox_ids() {
        let id = Uuid::parse_str("018f5f50-0000-7000-8000-000000000001").unwrap();
        assert_eq!(
            sandbox_id_from_xds_resource(&format!("{id}_http")),
            Some(id)
        );
        assert_eq!(
            sandbox_id_from_xds_resource(&format!("up_{id}_external_api")),
            Some(id)
        );
        assert_eq!(sandbox_id_from_xds_resource(&format!("{id}_grpc")), None);
        assert_eq!(sandbox_id_from_xds_resource("dynamic_forward_proxy"), None);
    }

    #[test]
    fn validates_duplicate_credential_and_allowlist_domains() {
        let sid = Uuid::nil();
        let policy = SandboxEgressPolicy {
            allowlist_hosts: vec![LLM_EGRESS_HOST.to_string()],
            credential_routes: vec![llm_route()],
            proxy_auth_token: None,
        };
        let err = validate_egress_policy(&sid, &policy)
            .unwrap_err()
            .to_string();
        assert!(err.contains("overlaps credential-injection host"), "{err}");
    }

    #[test]
    fn policy_summary_hashes_injected_header_values() {
        let sid = Uuid::nil();
        let policy = SandboxCredentials {
            routes: vec![llm_route()],
            proxy_auth_token: None,
        }
        .to_policy(&sid, vec![]);
        let summary = egress_policy_summary(&sid, &policy);
        let text = summary.to_string();
        assert!(text.contains("value_sha256"));
        assert!(!text.contains("Bearer sk-secret"));
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
                    inject_headers: vec![("authorization".to_string(), "Bearer sk".to_string())],
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
            proxy_auth_token: None,
        };
        let sid = Uuid::nil();
        let routes = creds.to_routes(&sid);
        let clusters = creds.to_clusters(&sid);

        // No per-sandbox clusters — routes point to shared DFP clusters.
        assert!(
            clusters.is_empty(),
            "per-sandbox clusters should not be created; routes use shared DFP"
        );

        // Every route's cluster_name must be one of the shared DFP clusters.
        for r in &routes {
            assert!(
                r.cluster_name == "dynamic_forward_proxy_tls"
                    || r.cluster_name == "dynamic_forward_proxy",
                "route cluster {} must be a shared DFP cluster",
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
        assert_eq!(llm.cluster_name, "dynamic_forward_proxy_tls");

        // MCP route scoped by name.
        let mcp = routes
            .iter()
            .find(|r| r.match_host == MCP_EGRESS_HOST)
            .unwrap();
        assert_eq!(mcp.match_prefix, "/mcp/gitlab/");
        assert_eq!(mcp.upstream_prefix, "/sse");
        assert_eq!(mcp.cluster_name, "dynamic_forward_proxy_tls");
    }

    #[test]
    fn external_placeholder_and_transparent_routes_share_one_cluster() {
        // An external service emits two routes: a placeholder-host route
        // (external-egress.internal/services/<name>/) and a transparent route on
        // the real host so a skill can call http://crm.example.com/api/ directly.
        // Both now point to the shared dynamic_forward_proxy_tls cluster.
        let sid = Uuid::nil();
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
            proxy_auth_token: None,
        };

        let routes = creds.to_routes(&sid);
        let clusters = creds.to_clusters(&sid);

        // No per-sandbox clusters; both routes use shared DFP.
        assert_eq!(routes.len(), 2);
        assert!(clusters.is_empty());
        assert_eq!(routes[0].cluster_name, "dynamic_forward_proxy_tls");
        assert_eq!(routes[1].cluster_name, "dynamic_forward_proxy_tls");

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
        assert_eq!(direct.cluster_name, "dynamic_forward_proxy_tls");

        // The transparent host gets its own credential vhost keyed on the real
        // host. In production the real host is NOT added to allowed_hosts (see
        // merge_egress_hosts), so no vhost collides on that exact domain. Build
        // the listener the way it is actually assembled — transparent routes +
        // an allowlist that does NOT contain the transparent host — and assert
        // every exact domain is unique across vhosts (Envoy rejects duplicates).
        let vh = build_virtual_hosts_json(&["other.example.com".to_string()], &routes, None);
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
            proxy_auth_token: None,
        };
        let routes = creds.to_routes(&sid);
        let vh = build_virtual_hosts_json(&[], &routes, None);

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
            cluster_name: "dynamic_forward_proxy_tls".to_string(),
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

        let vh = build_virtual_hosts_json(&[], &[exact, prefix], None);
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
        // Transparent routes don't need prefix_rewrite (path is already correct).
        assert!(prefix_route["route"].get("prefix_rewrite").is_none());
    }

    #[test]
    fn http_vhosts_have_deny_all_last() {
        // With no allowlist, only the catch-all deny_all vhost exists.
        let vh = build_virtual_hosts_json(&[], &[], None);
        assert_eq!(vh.len(), 1);
        assert_eq!(vh[0]["name"], "deny_all");
        // With an allowlist, `allowed` precedes `deny_all`.
        let vh = build_virtual_hosts_json(&["a.com".to_string()], &[], None);
        assert_eq!(vh.len(), 2);
        assert_eq!(vh[0]["name"], "allowed");
        assert_eq!(vh[1]["name"], "deny_all");
    }

    #[test]
    fn credential_vhosts_precede_allowlist_and_inject_headers() {
        let creds = vec![llm_route(), mcp_route("gitlab"), mcp_route("jira")];
        let vh = build_virtual_hosts_json(&["a.com".to_string()], &creds, None);
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
                json!("x-goog-api-key"),
                json!("proxy-authorization")
            ]
        );
        assert_eq!(
            llm_routes[0]["route"]["host_rewrite_literal"],
            "llm.internal.example.com"
        );
        assert_eq!(llm_routes[0]["route"]["prefix_rewrite"], "/v1/");
        assert_eq!(
            llm_routes[0]["route"]["cluster"],
            "dynamic_forward_proxy_tls"
        );

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
    fn proxy_auth_token_is_required_on_egress_routes() {
        let expected = proxy_authorization_value("runner-secret");
        let vh = build_virtual_hosts_json(
            &["a.com".to_string()],
            &[llm_route()],
            Some("runner-secret"),
        );

        let credential_headers = vh[0]["routes"][0]["match"]["headers"].as_array().unwrap();
        assert_eq!(credential_headers[0]["name"], "proxy-authorization");
        assert_eq!(credential_headers[0]["string_match"]["exact"], expected);

        let allowlist_headers = vh[1]["routes"][0]["match"]["headers"].as_array().unwrap();
        assert_eq!(allowlist_headers[0]["name"], "proxy-authorization");
        assert_eq!(allowlist_headers[0]["string_match"]["exact"], expected);
    }

    #[test]
    fn proxy_auth_token_is_required_in_proto_routes() {
        let expected = proxy_authorization_value("runner-secret");
        let mut http = spec_with_creds(ListenerKind::Http, &["a.com"], vec![llm_route()]);
        http.proxy_auth_token = Some("runner-secret".to_string());

        let any = encode_listener_any(&http).unwrap();
        use envoy_types::pb::envoy::config::listener::v3::Listener;
        use envoy_types::pb::envoy::config::route::v3::header_matcher;
        use envoy_types::pb::envoy::extensions::filters::network::http_connection_manager::v3::{
            http_connection_manager, HttpConnectionManager,
        };
        use envoy_types::pb::envoy::r#type::matcher::v3::string_matcher;
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
        let credential_header = &rc.virtual_hosts[0].routes[0]
            .r#match
            .as_ref()
            .unwrap()
            .headers[0];
        assert_eq!(credential_header.name, "proxy-authorization");
        assert!(matches!(
            credential_header.header_match_specifier.as_ref(),
            Some(header_matcher::HeaderMatchSpecifier::StringMatch(sm))
                if sm.match_pattern == Some(string_matcher::MatchPattern::Exact(expected.clone()))
        ));

        let allowed_header = &rc.virtual_hosts[1].routes[0]
            .r#match
            .as_ref()
            .unwrap()
            .headers[0];
        assert_eq!(allowed_header.name, "proxy-authorization");
        assert!(matches!(
            allowed_header.header_match_specifier.as_ref(),
            Some(header_matcher::HeaderMatchSpecifier::StringMatch(sm))
                if sm.match_pattern == Some(string_matcher::MatchPattern::Exact(expected.clone()))
        ));
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
        let cred = EgressCredentialRoute {
            id: "test".to_string(),
            kind: EgressKind::External,
            exposure: EgressExposure::Transparent,
            match_host: "llm-egress.internal".to_string(),
            match_prefix: "/v1/".to_string(),
            upstream_host: "api.example.com".to_string(),
            upstream_port: 443,
            upstream_prefix: "/v1/".to_string(),
            upstream_tls: true,
            cluster_name: "dynamic_forward_proxy_tls".to_string(),
            exact_path: false,
            inject_headers: vec![("cookie".to_string(), "session=abc%7Cdef%3Dxyz".to_string())],
            remove_headers: vec![],
        };
        let vh = build_virtual_hosts_json(&[], &[cred], None);
        let header_val = vh[0]["routes"][0]["request_headers_to_add"][0]["header"]["value"]
            .as_str()
            .unwrap();
        // % must be doubled so Envoy treats them as literal
        assert_eq!(header_val, "session=abc%%7Cdef%%3Dxyz");
    }
}
