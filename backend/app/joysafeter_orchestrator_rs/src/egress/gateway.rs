use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::{Arc, RwLock};

use axum::{
    body::{Body, Bytes},
    extract::{OriginalUri, Path, State},
    http::{HeaderMap, HeaderName, HeaderValue, Method, StatusCode},
    response::{IntoResponse, Response},
    routing::{any, get, put},
    Json, Router,
};
use reqwest::Client;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use subtle::ConstantTimeEq;
use thiserror::Error;
use tracing::{debug, warn};
use url::Url;
use uuid::Uuid;

use crate::egress::policy::{EgressCredentialRoute, SandboxEgressPolicy};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GatewayConfig {
    pub host: String,
    pub port: u16,
    pub require_sandbox_token: bool,
    pub control_token_sha256: Option<[u8; 32]>,
}

impl GatewayConfig {
    pub fn from_env() -> Self {
        Self {
            host: env_str("JOYSAFETER_EGRESS_GATEWAY_HOST", "0.0.0.0"),
            port: env_u16("JOYSAFETER_EGRESS_GATEWAY_PORT", 8088),
            require_sandbox_token: env_bool(
                "JOYSAFETER_EGRESS_GATEWAY_REQUIRE_SANDBOX_TOKEN",
                true,
            ),
            control_token_sha256: std::env::var("JOYSAFETER_EGRESS_GATEWAY_CONTROL_TOKEN")
                .ok()
                .filter(|token| !token.trim().is_empty())
                .map(|token| hash_token(&token)),
        }
    }

    pub fn bind_addr(&self) -> anyhow::Result<SocketAddr> {
        format!("{}:{}", self.host, self.port)
            .parse()
            .map_err(|e| anyhow::anyhow!("invalid egress gateway bind address: {e}"))
    }
}

#[derive(Debug, Clone)]
struct AppState {
    config: GatewayConfig,
    policy_store: Option<Arc<dyn GatewayPolicyStore>>,
    client: Client,
}

#[derive(Debug, Serialize)]
struct HealthResponse {
    status: &'static str,
    service: &'static str,
    version: &'static str,
    require_sandbox_token: bool,
    policy_store_configured: bool,
    control_api_configured: bool,
}

#[derive(Debug, Serialize, Deserialize)]
struct ErrorResponse {
    code: String,
    message: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct InstallPolicyRequest {
    sandbox_token: String,
    policy: SandboxEgressPolicy,
}

#[derive(Debug, Clone)]
pub struct EgressGatewayControlClient {
    base_url: Url,
    control_token: String,
    client: Client,
}

impl EgressGatewayControlClient {
    pub fn new(base_url: &str, control_token: &str) -> anyhow::Result<Self> {
        let base_url = Url::parse(base_url.trim())
            .map_err(|e| anyhow::anyhow!("invalid egress gateway URL: {e}"))?;
        let control_token = control_token.trim();
        if control_token.is_empty() {
            anyhow::bail!("egress gateway control token must be configured");
        }
        Ok(Self {
            base_url,
            control_token: control_token.to_string(),
            client: Client::new(),
        })
    }

    pub async fn install_policy(
        &self,
        sandbox_id: Uuid,
        sandbox_token: &str,
        policy: SandboxEgressPolicy,
    ) -> anyhow::Result<()> {
        if sandbox_token.trim().is_empty() {
            anyhow::bail!("sandbox token must be non-empty before installing egress policy");
        }
        let response = self
            .client
            .put(self.policy_url(sandbox_id)?)
            .header("x-joysafeter-control-token", &self.control_token)
            .json(&InstallPolicyRequest {
                sandbox_token: sandbox_token.to_string(),
                policy,
            })
            .send()
            .await?;
        ensure_control_success(response, "install gateway sandbox policy").await
    }

    pub async fn revoke_policy(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        let response = self
            .client
            .delete(self.policy_url(sandbox_id)?)
            .header("x-joysafeter-control-token", &self.control_token)
            .send()
            .await?;
        ensure_control_success(response, "revoke gateway sandbox policy").await
    }

    fn policy_url(&self, sandbox_id: Uuid) -> anyhow::Result<Url> {
        self.base_url
            .join(&format!("/control/sandboxes/{sandbox_id}/policy"))
            .map_err(|e| anyhow::anyhow!("invalid egress gateway policy URL: {e}"))
    }
}

async fn ensure_control_success(response: reqwest::Response, action: &str) -> anyhow::Result<()> {
    let status = response.status();
    if status.is_success() {
        return Ok(());
    }
    let error = response.json::<ErrorResponse>().await.ok();
    if let Some(error) = error {
        anyhow::bail!(
            "{action} failed with HTTP {status}: {} ({})",
            error.message,
            error.code
        );
    }
    anyhow::bail!("{action} failed with HTTP {status}");
}

#[derive(Debug, Clone)]
pub struct GatewaySandboxPolicy {
    pub sandbox_id: Uuid,
    sandbox_token_sha256: Option<[u8; 32]>,
    pub policy: SandboxEgressPolicy,
}

impl GatewaySandboxPolicy {
    pub fn new(sandbox_id: Uuid, sandbox_token: Option<&str>, policy: SandboxEgressPolicy) -> Self {
        Self {
            sandbox_id,
            sandbox_token_sha256: sandbox_token.map(hash_token),
            policy,
        }
    }

    fn verify_token(&self, presented: &str) -> bool {
        let Some(expected) = self.sandbox_token_sha256 else {
            return false;
        };
        let actual = hash_token(presented);
        expected.ct_eq(&actual).into()
    }
}

pub trait GatewayPolicyStore: std::fmt::Debug + Send + Sync {
    fn get(&self, sandbox_id: Uuid) -> Option<GatewaySandboxPolicy>;
    fn upsert(&self, policy: GatewaySandboxPolicy);
    fn delete(&self, sandbox_id: Uuid) -> bool;
}

#[derive(Debug, Default)]
pub struct InMemoryGatewayPolicyStore {
    policies: RwLock<HashMap<Uuid, GatewaySandboxPolicy>>,
}

impl InMemoryGatewayPolicyStore {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn insert(&self, policy: GatewaySandboxPolicy) {
        self.upsert(policy);
    }
}

impl GatewayPolicyStore for InMemoryGatewayPolicyStore {
    fn get(&self, sandbox_id: Uuid) -> Option<GatewaySandboxPolicy> {
        self.policies
            .read()
            .expect("gateway policy store poisoned")
            .get(&sandbox_id)
            .cloned()
    }

    fn upsert(&self, policy: GatewaySandboxPolicy) {
        self.policies
            .write()
            .expect("gateway policy store poisoned")
            .insert(policy.sandbox_id, policy);
    }

    fn delete(&self, sandbox_id: Uuid) -> bool {
        self.policies
            .write()
            .expect("gateway policy store poisoned")
            .remove(&sandbox_id)
            .is_some()
    }
}

pub fn app(config: GatewayConfig) -> Router {
    app_with_policy_store(config, Some(Arc::new(InMemoryGatewayPolicyStore::new())))
}

pub fn app_with_policy_store(
    config: GatewayConfig,
    policy_store: Option<Arc<dyn GatewayPolicyStore>>,
) -> Router {
    let state = AppState {
        config,
        policy_store,
        client: Client::new(),
    };
    Router::new()
        .route("/healthz", get(healthz))
        .route("/readyz", get(readyz))
        .route(
            "/control/sandboxes/:sandbox_id/policy",
            put(install_policy).delete(revoke_policy),
        )
        .fallback(any(proxy_entrypoint))
        .with_state(state)
}

async fn healthz(State(state): State<AppState>) -> impl IntoResponse {
    Json(HealthResponse {
        status: "ok",
        service: "joysafeter-egress-gateway",
        version: env!("CARGO_PKG_VERSION"),
        require_sandbox_token: state.config.require_sandbox_token,
        policy_store_configured: state.policy_store.is_some(),
        control_api_configured: state.config.control_token_sha256.is_some(),
    })
}

async fn readyz(State(state): State<AppState>) -> Response {
    if state.policy_store.is_none() {
        return (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(ErrorResponse {
                code: "GATEWAY_POLICY_STORE_NOT_CONFIGURED".to_string(),
                message: "egress gateway is running but no policy store is configured".to_string(),
            }),
        )
            .into_response();
    } else if !state.config.require_sandbox_token {
        return json_error(
            StatusCode::SERVICE_UNAVAILABLE,
            "GATEWAY_SANDBOX_AUTH_DISABLED",
            "egress gateway refuses readiness while sandbox token authentication is disabled",
        );
    } else if state.config.control_token_sha256.is_none() {
        return json_error(
            StatusCode::SERVICE_UNAVAILABLE,
            "GATEWAY_CONTROL_AUTH_NOT_CONFIGURED",
            "egress gateway refuses readiness without control-plane token authentication",
        );
    }

    json_error(
        StatusCode::OK,
        "GATEWAY_READY",
        "egress gateway policy store is configured and sandbox token authentication is enabled",
    )
}

async fn install_policy(
    State(state): State<AppState>,
    Path(sandbox_id): Path<Uuid>,
    headers: HeaderMap,
    Json(payload): Json<InstallPolicyRequest>,
) -> Response {
    if let Err(response) = authorize_control_request(&state, &headers) {
        return response;
    }
    let Some(store) = state.policy_store.as_ref() else {
        return json_error(
            StatusCode::SERVICE_UNAVAILABLE,
            "GATEWAY_POLICY_STORE_NOT_CONFIGURED",
            "egress gateway cannot install sandbox policy without a policy store",
        );
    };
    if payload.sandbox_token.trim().is_empty() {
        return json_error(
            StatusCode::BAD_REQUEST,
            "GATEWAY_SANDBOX_TOKEN_EMPTY",
            "sandbox policy installation requires a non-empty sandbox token",
        );
    }

    store.upsert(GatewaySandboxPolicy::new(
        sandbox_id,
        Some(&payload.sandbox_token),
        payload.policy,
    ));
    StatusCode::NO_CONTENT.into_response()
}

async fn revoke_policy(
    State(state): State<AppState>,
    Path(sandbox_id): Path<Uuid>,
    headers: HeaderMap,
) -> Response {
    if let Err(response) = authorize_control_request(&state, &headers) {
        return response;
    }
    let Some(store) = state.policy_store.as_ref() else {
        return json_error(
            StatusCode::SERVICE_UNAVAILABLE,
            "GATEWAY_POLICY_STORE_NOT_CONFIGURED",
            "egress gateway cannot revoke sandbox policy without a policy store",
        );
    };

    store.delete(sandbox_id);
    StatusCode::NO_CONTENT.into_response()
}

async fn proxy_entrypoint(
    State(state): State<AppState>,
    method: Method,
    OriginalUri(uri): OriginalUri,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    let Some((sandbox_id, route_id, rest_path)) = parse_gateway_path(uri.path()) else {
        return json_error(
            StatusCode::NOT_IMPLEMENTED,
            "GATEWAY_FORWARDING_NOT_IMPLEMENTED",
            format!(
                "egress gateway refused request to {}; path is not a sandbox egress route",
                uri.path()
            ),
        );
    };

    let Some(store) = state.policy_store.as_ref() else {
        return json_error(
            StatusCode::SERVICE_UNAVAILABLE,
            "GATEWAY_POLICY_STORE_NOT_CONFIGURED",
            "egress gateway cannot authorize sandbox traffic without a policy store",
        );
    };

    let Some(policy) = store.get(sandbox_id) else {
        return json_error(
            StatusCode::NOT_FOUND,
            "GATEWAY_SANDBOX_POLICY_NOT_FOUND",
            format!("no egress policy is installed for sandbox {sandbox_id}"),
        );
    };

    if state.config.require_sandbox_token {
        let Some(token) = extract_sandbox_token(&headers) else {
            return json_error(
                StatusCode::UNAUTHORIZED,
                "GATEWAY_SANDBOX_TOKEN_REQUIRED",
                "sandbox egress request did not include a bearer token",
            );
        };
        if !policy.verify_token(&token) {
            return json_error(
                StatusCode::UNAUTHORIZED,
                "GATEWAY_SANDBOX_TOKEN_INVALID",
                "sandbox egress request token is invalid",
            );
        }
    }

    let Some(route) = policy_route(&policy.policy, &route_id) else {
        return json_error(
            StatusCode::FORBIDDEN,
            "GATEWAY_EGRESS_ROUTE_DENIED",
            format!("sandbox {sandbox_id} is not allowed to use route '{route_id}'"),
        );
    };

    match build_upstream_request(
        sandbox_id,
        &state.client,
        route,
        method,
        &headers,
        body,
        &rest_path,
        uri.query(),
    ) {
        Ok(request) => match forward_upstream_request(&state.client, request).await {
            Ok(response) => response,
            Err(error) => gateway_forward_error(error),
        },
        Err(error) => gateway_forward_error(error),
    }
}

fn json_error(status: StatusCode, code: &'static str, message: impl Into<String>) -> Response {
    (
        status,
        Json(ErrorResponse {
            code: code.to_string(),
            message: message.into(),
        }),
    )
        .into_response()
}

fn parse_gateway_path(path: &str) -> Option<(Uuid, String, String)> {
    let mut parts = path.trim_start_matches('/').split('/');
    if parts.next()? != "sandbox" {
        return None;
    }
    let sandbox_id = parts.next()?.parse().ok()?;
    if parts.next()? != "egress" {
        return None;
    }
    let route_id = parts.next()?.to_string();
    if route_id.is_empty() {
        return None;
    }
    let rest = parts.collect::<Vec<_>>().join("/");
    Some((sandbox_id, route_id, format!("/{rest}")))
}

fn extract_sandbox_token(headers: &HeaderMap) -> Option<String> {
    if let Some(value) = headers.get("x-joysafeter-sandbox-token") {
        return value.to_str().ok().map(ToOwned::to_owned);
    }

    if let Some(authorization) = headers.get(axum::http::header::AUTHORIZATION) {
        let value = authorization.to_str().ok()?;
        if let Some(token) = value
            .strip_prefix("Bearer ")
            .filter(|token| !token.trim().is_empty())
        {
            return Some(token.to_string());
        }
    }

    for header in ["x-api-key", "api-key", "x-goog-api-key"] {
        if let Some(value) = headers.get(header) {
            if let Ok(token) = value.to_str() {
                if !token.trim().is_empty() {
                    return Some(token.to_string());
                }
            }
        }
    }

    None
}

fn authorize_control_request(state: &AppState, headers: &HeaderMap) -> Result<(), Response> {
    let Some(expected) = state.config.control_token_sha256 else {
        return Err(json_error(
            StatusCode::SERVICE_UNAVAILABLE,
            "GATEWAY_CONTROL_AUTH_NOT_CONFIGURED",
            "egress gateway control API is disabled because no control token is configured",
        ));
    };
    let Some(presented) = extract_control_token(headers) else {
        return Err(json_error(
            StatusCode::UNAUTHORIZED,
            "GATEWAY_CONTROL_TOKEN_REQUIRED",
            "egress gateway control request did not include a bearer token",
        ));
    };
    let actual = hash_token(&presented);
    if bool::from(expected.ct_eq(&actual)) {
        Ok(())
    } else {
        Err(json_error(
            StatusCode::UNAUTHORIZED,
            "GATEWAY_CONTROL_TOKEN_INVALID",
            "egress gateway control request token is invalid",
        ))
    }
}

fn extract_control_token(headers: &HeaderMap) -> Option<String> {
    if let Some(value) = headers.get("x-joysafeter-control-token") {
        return value.to_str().ok().map(ToOwned::to_owned);
    }

    let authorization = headers.get(axum::http::header::AUTHORIZATION)?;
    let value = authorization.to_str().ok()?;
    value
        .strip_prefix("Bearer ")
        .filter(|token| !token.trim().is_empty())
        .map(ToOwned::to_owned)
}

fn policy_route<'a>(
    policy: &'a SandboxEgressPolicy,
    route_id: &str,
) -> Option<&'a EgressCredentialRoute> {
    policy
        .credential_routes
        .iter()
        .find(|route| route.id == route_id)
}

#[derive(Debug, Error)]
enum GatewayForwardError {
    #[error("gateway route path is not allowed by policy")]
    RoutePathDenied,
    #[error("gateway route configuration is invalid")]
    InvalidRouteConfig,
    #[error("gateway request header is invalid")]
    InvalidRequestHeader,
    #[error("upstream request failed")]
    UpstreamRequest(#[from] reqwest::Error),
}

#[derive(Debug)]
struct BuiltUpstreamRequest {
    request: reqwest::Request,
    audit: GatewayForwardAudit,
}

#[derive(Debug, Clone)]
struct GatewayForwardAudit {
    sandbox_id: Uuid,
    route_id: String,
    method: String,
    upstream_host: String,
    upstream_port: u16,
    upstream_tls: bool,
    upstream_path: String,
    upstream_query: Option<String>,
    request_model: Option<String>,
    forwarded_header_names: Vec<String>,
    injected_header_names: Vec<String>,
    sandbox_auth_header_names: Vec<String>,
}

fn build_upstream_request(
    sandbox_id: Uuid,
    client: &Client,
    route: &EgressCredentialRoute,
    method: Method,
    headers: &HeaderMap,
    body: Bytes,
    rest_path: &str,
    query: Option<&str>,
) -> Result<BuiltUpstreamRequest, GatewayForwardError> {
    let upstream_url = upstream_url_for_route(route, rest_path, query)?;
    let reqwest_method = reqwest::Method::from_bytes(method.as_str().as_bytes())
        .map_err(|_| GatewayForwardError::InvalidRouteConfig)?;
    let forwarded_headers = sanitized_forward_headers(headers, route)?;
    let audit = GatewayForwardAudit {
        sandbox_id,
        route_id: route.id.clone(),
        method: method.as_str().to_string(),
        upstream_host: route.upstream_host.clone(),
        upstream_port: route.upstream_port,
        upstream_tls: route.upstream_tls,
        upstream_path: upstream_url.path().to_string(),
        upstream_query: upstream_url.query().map(ToOwned::to_owned),
        request_model: json_string_field(&body, "model"),
        forwarded_header_names: forwarded_headers
            .iter()
            .map(|(name, _)| name.as_str().to_string())
            .collect(),
        injected_header_names: route
            .inject_headers
            .iter()
            .map(|(name, _)| name.to_ascii_lowercase())
            .collect(),
        sandbox_auth_header_names: sandbox_auth_header_names(headers),
    };
    let mut builder = client.request(reqwest_method, upstream_url);
    for (name, value) in forwarded_headers {
        builder = builder.header(name, value);
    }
    for (name, value) in &route.inject_headers {
        let name = HeaderName::from_bytes(name.as_bytes())
            .map_err(|_| GatewayForwardError::InvalidRouteConfig)?;
        let value =
            HeaderValue::from_str(value).map_err(|_| GatewayForwardError::InvalidRouteConfig)?;
        builder = builder.header(name, value);
    }
    let request = builder
        .body(body)
        .build()
        .map_err(GatewayForwardError::UpstreamRequest)?;
    Ok(BuiltUpstreamRequest { request, audit })
}

async fn forward_upstream_request(
    client: &Client,
    built: BuiltUpstreamRequest,
) -> Result<Response, GatewayForwardError> {
    let audit = built.audit;
    debug!(
        sandbox_id = %audit.sandbox_id,
        route_id = %audit.route_id,
        method = %audit.method,
        upstream_host = %audit.upstream_host,
        upstream_port = audit.upstream_port,
        upstream_tls = audit.upstream_tls,
        upstream_path = %audit.upstream_path,
        upstream_query = audit.upstream_query.as_deref().unwrap_or(""),
        request_model = audit.request_model.as_deref().unwrap_or(""),
        forwarded_header_names = ?audit.forwarded_header_names,
        injected_header_names = ?audit.injected_header_names,
        sandbox_auth_header_names = ?audit.sandbox_auth_header_names,
        "LLM egress gateway forwarding request"
    );
    let upstream = client.execute(built.request).await?;
    let status = StatusCode::from_u16(upstream.status().as_u16())
        .map_err(|_| GatewayForwardError::InvalidRouteConfig)?;
    let headers = response_headers(upstream.headers())?;
    let body = upstream.bytes().await?;
    if status.is_success() {
        debug!(
            sandbox_id = %audit.sandbox_id,
            route_id = %audit.route_id,
            upstream_host = %audit.upstream_host,
            upstream_path = %audit.upstream_path,
            upstream_status = status.as_u16(),
            request_model = audit.request_model.as_deref().unwrap_or(""),
            "LLM egress gateway upstream response"
        );
    } else {
        let upstream_error_summary = upstream_error_summary(&body).unwrap_or_default();
        warn!(
            sandbox_id = %audit.sandbox_id,
            route_id = %audit.route_id,
            upstream_host = %audit.upstream_host,
            upstream_path = %audit.upstream_path,
            upstream_status = status.as_u16(),
            request_model = audit.request_model.as_deref().unwrap_or(""),
            upstream_error_summary = %upstream_error_summary,
            "LLM egress gateway upstream returned non-success"
        );
    }

    let mut builder = Response::builder().status(status);
    for (name, value) in headers {
        builder = builder.header(name, value);
    }
    builder
        .body(Body::from(body))
        .map_err(|_| GatewayForwardError::InvalidRouteConfig)
}

fn gateway_forward_error(error: GatewayForwardError) -> Response {
    match error {
        GatewayForwardError::RoutePathDenied => json_error(
            StatusCode::FORBIDDEN,
            "GATEWAY_EGRESS_PATH_DENIED",
            "egress route does not allow the requested upstream path",
        ),
        GatewayForwardError::InvalidRouteConfig | GatewayForwardError::InvalidRequestHeader => {
            json_error(
                StatusCode::BAD_GATEWAY,
                "GATEWAY_EGRESS_ROUTE_INVALID",
                "egress route could not be rendered into a safe upstream request",
            )
        }
        GatewayForwardError::UpstreamRequest(_) => json_error(
            StatusCode::BAD_GATEWAY,
            "GATEWAY_UPSTREAM_REQUEST_FAILED",
            "egress upstream request failed",
        ),
    }
}

fn upstream_url_for_route(
    route: &EgressCredentialRoute,
    rest_path: &str,
    query: Option<&str>,
) -> Result<Url, GatewayForwardError> {
    let path = upstream_path_for_route(route, rest_path)?;
    let scheme = if route.upstream_tls { "https" } else { "http" };
    let mut url = Url::parse(&format!("{scheme}://{}", route.upstream_host))
        .map_err(|_| GatewayForwardError::InvalidRouteConfig)?;
    url.set_port(Some(route.upstream_port))
        .map_err(|_| GatewayForwardError::InvalidRouteConfig)?;
    url.set_path(&path);
    url.set_query(query);
    Ok(url)
}

fn upstream_path_for_route(
    route: &EgressCredentialRoute,
    rest_path: &str,
) -> Result<String, GatewayForwardError> {
    let rest = normalize_gateway_path(rest_path);
    if has_forbidden_path_segment(&rest) {
        return Err(GatewayForwardError::RoutePathDenied);
    }
    let match_prefix = normalize_gateway_path(&route.match_prefix);
    if route.exact_path {
        if rest != match_prefix {
            return Err(GatewayForwardError::RoutePathDenied);
        }
        return Ok(normalize_gateway_path(&route.upstream_prefix));
    }

    if !path_has_prefix(&rest, &match_prefix) {
        return Err(GatewayForwardError::RoutePathDenied);
    }
    let suffix = rest.strip_prefix(&match_prefix).unwrap_or_default();
    Ok(join_gateway_paths(&route.upstream_prefix, suffix))
}

fn has_forbidden_path_segment(path: &str) -> bool {
    let lower = path.to_ascii_lowercase();
    if lower.contains("%2e") || lower.contains("%2f") || lower.contains("%5c") {
        return true;
    }
    path.split('/')
        .any(|segment| segment == "." || segment == "..")
}

fn normalize_gateway_path(path: &str) -> String {
    if path.is_empty() {
        "/".to_string()
    } else if path.starts_with('/') {
        path.to_string()
    } else {
        format!("/{path}")
    }
}

fn path_has_prefix(path: &str, prefix: &str) -> bool {
    if prefix == "/" {
        return true;
    }
    path == prefix || path.starts_with(prefix)
}

fn join_gateway_paths(prefix: &str, suffix: &str) -> String {
    let prefix = normalize_gateway_path(prefix);
    if suffix.is_empty() {
        return prefix;
    }
    let suffix = suffix.trim_start_matches('/');
    if prefix == "/" {
        format!("/{suffix}")
    } else if prefix.ends_with('/') {
        format!("{prefix}{suffix}")
    } else {
        format!("{prefix}/{suffix}")
    }
}

fn sanitized_forward_headers(
    headers: &HeaderMap,
    route: &EgressCredentialRoute,
) -> Result<Vec<(HeaderName, HeaderValue)>, GatewayForwardError> {
    let mut out = Vec::new();
    for (name, value) in headers {
        if should_strip_request_header(name, route) {
            continue;
        }
        out.push((name.clone(), value.clone()));
    }
    Ok(out)
}

fn sandbox_auth_header_names(headers: &HeaderMap) -> Vec<String> {
    ["authorization", "x-api-key", "api-key", "x-goog-api-key"]
        .iter()
        .filter(|name| headers.contains_key(**name))
        .map(|name| (*name).to_string())
        .collect()
}

fn json_string_field(body: &[u8], field: &str) -> Option<String> {
    serde_json::from_slice::<serde_json::Value>(body)
        .ok()?
        .get(field)?
        .as_str()
        .filter(|value| !value.trim().is_empty())
        .map(|value| value.chars().take(160).collect())
}

fn upstream_error_summary(body: &[u8]) -> Option<String> {
    let json = serde_json::from_slice::<serde_json::Value>(body).ok()?;
    let message = json
        .pointer("/error/message")
        .or_else(|| json.get("message"))
        .or_else(|| json.get("error"))?;
    let raw = message
        .as_str()
        .or_else(|| message.get("message").and_then(|value| value.as_str()))?;
    Some(sanitize_log_excerpt(raw, 240))
}

fn sanitize_log_excerpt(raw: &str, max_chars: usize) -> String {
    raw.chars()
        .map(|ch| if ch.is_control() { ' ' } else { ch })
        .collect::<String>()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .chars()
        .take(max_chars)
        .collect()
}

fn should_strip_request_header(name: &HeaderName, route: &EgressCredentialRoute) -> bool {
    const ALWAYS_STRIP: &[&str] = &[
        "host",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "content-length",
        "x-joysafeter-sandbox-token",
        "authorization",
        "cookie",
        "x-api-key",
        "api-key",
        "x-goog-api-key",
    ];
    ALWAYS_STRIP
        .iter()
        .any(|candidate| name.as_str().eq_ignore_ascii_case(candidate))
        || route
            .remove_headers
            .iter()
            .any(|candidate| name.as_str().eq_ignore_ascii_case(candidate))
}

fn response_headers(
    headers: &reqwest::header::HeaderMap,
) -> Result<Vec<(HeaderName, HeaderValue)>, GatewayForwardError> {
    let mut out = Vec::new();
    for (name, value) in headers {
        if should_strip_response_header(name.as_str()) {
            continue;
        }
        let name = HeaderName::from_bytes(name.as_str().as_bytes())
            .map_err(|_| GatewayForwardError::InvalidRequestHeader)?;
        let value = HeaderValue::from_bytes(value.as_bytes())
            .map_err(|_| GatewayForwardError::InvalidRequestHeader)?;
        out.push((name, value));
    }
    Ok(out)
}

fn should_strip_response_header(name: &str) -> bool {
    const STRIP: &[&str] = &[
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    ];
    STRIP
        .iter()
        .any(|candidate| name.eq_ignore_ascii_case(candidate))
}

pub(crate) fn hash_token(token: &str) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(token.as_bytes());
    hasher.finalize().into()
}

fn env_str(key: &str, default: &str) -> String {
    std::env::var(key).unwrap_or_else(|_| default.to_string())
}

fn env_bool(key: &str, default: bool) -> bool {
    std::env::var(key)
        .ok()
        .and_then(|value| match value.to_ascii_lowercase().as_str() {
            "1" | "true" | "yes" | "on" => Some(true),
            "0" | "false" | "no" | "off" => Some(false),
            _ => None,
        })
        .unwrap_or(default)
}

fn env_u16(key: &str, default: u16) -> u16 {
    std::env::var(key)
        .ok()
        .and_then(|value| value.parse().ok())
        .unwrap_or(default)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::egress::policy::{
        EgressCredentialRoute, EgressExposure, EgressKind, LLM_EGRESS_HOST,
    };
    use axum::http::Uri;
    use tokio::sync::{mpsc, oneshot};

    #[test]
    fn gateway_config_default_bind_addr_is_stable() {
        let config = GatewayConfig {
            host: "127.0.0.1".to_string(),
            port: 8088,
            require_sandbox_token: true,
            control_token_sha256: Some(hash_token("control-token")),
        };

        assert_eq!(
            config.bind_addr().expect("valid bind addr").to_string(),
            "127.0.0.1:8088"
        );
    }

    #[tokio::test]
    async fn gateway_readyz_fails_closed_without_policy_store() {
        let state = AppState {
            config: GatewayConfig {
                host: "127.0.0.1".to_string(),
                port: 8088,
                require_sandbox_token: true,
                control_token_sha256: Some(hash_token("control-token")),
            },
            policy_store: None,
            client: Client::new(),
        };

        let response = readyz(State(state)).await.into_response();

        assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
    }

    #[tokio::test]
    async fn gateway_proxy_entrypoint_refuses_unknown_paths_without_forwarding() {
        let state = AppState {
            config: test_config(),
            policy_store: None,
            client: Client::new(),
        };
        let uri = "/sandbox/018ff000-0000-7000-8000-000000000001/llm/v1/messages"
            .parse()
            .expect("valid uri");

        let response = proxy_entrypoint(
            State(state),
            Method::GET,
            OriginalUri(uri),
            HeaderMap::new(),
            Bytes::new(),
        )
        .await;

        assert_eq!(response.status(), StatusCode::NOT_IMPLEMENTED);
    }

    #[tokio::test]
    async fn gateway_readyz_requires_configured_policy_store_and_auth() {
        let state = AppState {
            config: test_config(),
            policy_store: Some(Arc::new(InMemoryGatewayPolicyStore::new())),
            client: Client::new(),
        };

        let response = readyz(State(state)).await.into_response();

        assert_eq!(response.status(), StatusCode::OK);
    }

    #[tokio::test]
    async fn gateway_readyz_fails_closed_without_control_token() {
        let state = AppState {
            config: GatewayConfig {
                host: "127.0.0.1".to_string(),
                port: 8088,
                require_sandbox_token: true,
                control_token_sha256: None,
            },
            policy_store: Some(Arc::new(InMemoryGatewayPolicyStore::new())),
            client: Client::new(),
        };

        let response = readyz(State(state)).await.into_response();

        assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
    }

    #[tokio::test]
    async fn gateway_proxy_requires_installed_policy() {
        let state = AppState {
            config: test_config(),
            policy_store: Some(Arc::new(InMemoryGatewayPolicyStore::new())),
            client: Client::new(),
        };
        let uri = format!(
            "/sandbox/{}/egress/llm/v1/messages",
            Uuid::parse_str("018ff000-0000-7000-8000-000000000001").unwrap()
        )
        .parse()
        .expect("valid uri");

        let response = proxy_entrypoint(
            State(state),
            Method::GET,
            OriginalUri(uri),
            bearer("runner-token"),
            Bytes::new(),
        )
        .await;

        assert_eq!(response.status(), StatusCode::NOT_FOUND);
    }

    #[tokio::test]
    async fn gateway_proxy_rejects_missing_or_invalid_sandbox_token() {
        let sandbox_id = Uuid::parse_str("018ff000-0000-7000-8000-000000000002").unwrap();
        let store = Arc::new(InMemoryGatewayPolicyStore::new());
        store.insert(test_policy(sandbox_id, "runner-token"));
        let state = AppState {
            config: test_config(),
            policy_store: Some(store),
            client: Client::new(),
        };
        let uri: Uri = format!("/sandbox/{sandbox_id}/egress/llm/v1/messages")
            .parse()
            .expect("valid uri");

        let missing = proxy_entrypoint(
            State(state.clone()),
            Method::GET,
            OriginalUri(uri.clone()),
            HeaderMap::new(),
            Bytes::new(),
        )
        .await;
        let invalid = proxy_entrypoint(
            State(state),
            Method::GET,
            OriginalUri(uri),
            bearer("wrong-token"),
            Bytes::new(),
        )
        .await;

        assert_eq!(missing.status(), StatusCode::UNAUTHORIZED);
        assert_eq!(invalid.status(), StatusCode::UNAUTHORIZED);
    }

    #[tokio::test]
    async fn gateway_proxy_rejects_unconfigured_route_after_auth() {
        let sandbox_id = Uuid::parse_str("018ff000-0000-7000-8000-000000000003").unwrap();
        let store = Arc::new(InMemoryGatewayPolicyStore::new());
        store.insert(test_policy(sandbox_id, "runner-token"));
        let state = AppState {
            config: test_config(),
            policy_store: Some(store),
            client: Client::new(),
        };
        let uri = format!("/sandbox/{sandbox_id}/egress/mcp-primary/sse")
            .parse()
            .expect("valid uri");

        let response = proxy_entrypoint(
            State(state),
            Method::GET,
            OriginalUri(uri),
            bearer("runner-token"),
            Bytes::new(),
        )
        .await;

        assert_eq!(response.status(), StatusCode::FORBIDDEN);
    }

    #[tokio::test]
    async fn gateway_proxy_authorizes_policy_route_and_attempts_forwarding() {
        let sandbox_id = Uuid::parse_str("018ff000-0000-7000-8000-000000000004").unwrap();
        let store = Arc::new(InMemoryGatewayPolicyStore::new());
        store.insert(test_policy(sandbox_id, "runner-token"));
        let state = AppState {
            config: test_config(),
            policy_store: Some(store),
            client: Client::new(),
        };
        let uri = format!("/sandbox/{sandbox_id}/egress/llm/v1/messages")
            .parse()
            .expect("valid uri");

        let response = proxy_entrypoint(
            State(state),
            Method::GET,
            OriginalUri(uri),
            bearer("runner-token"),
            Bytes::new(),
        )
        .await;

        assert_eq!(response.status(), StatusCode::BAD_GATEWAY);
    }

    #[tokio::test]
    async fn gateway_proxy_forwards_to_upstream_with_injected_headers() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .expect("bind upstream");
        let upstream_port = listener.local_addr().expect("local addr").port();
        let (seen_tx, mut seen_rx) = mpsc::unbounded_channel();
        let (shutdown_tx, shutdown_rx) = oneshot::channel::<()>();
        let upstream_app =
            Router::new().fallback(any(move |uri: Uri, headers: HeaderMap, body: Bytes| {
                let seen_tx = seen_tx.clone();
                async move {
                    let _ = seen_tx.send((
                        uri.path_and_query()
                            .map(|pq| pq.as_str().to_string())
                            .unwrap_or_else(|| uri.path().to_string()),
                        headers
                            .get("authorization")
                            .and_then(|v| v.to_str().ok())
                            .map(ToOwned::to_owned),
                        headers.get("x-joysafeter-sandbox-token").is_some(),
                        body.to_vec(),
                    ));
                    (StatusCode::CREATED, [("x-upstream", "ok")], "done")
                }
            }));
        let server = tokio::spawn(async move {
            let _ = axum::serve(listener, upstream_app)
                .with_graceful_shutdown(async {
                    let _ = shutdown_rx.await;
                })
                .await;
        });

        let sandbox_id = Uuid::parse_str("018ff000-0000-7000-8000-000000000006").unwrap();
        let store = Arc::new(InMemoryGatewayPolicyStore::new());
        store.insert(GatewaySandboxPolicy::new(
            sandbox_id,
            Some("runner-token"),
            SandboxEgressPolicy {
                allowlist_hosts: vec![],
                credential_routes: vec![EgressCredentialRoute {
                    id: "llm".to_string(),
                    kind: EgressKind::Llm,
                    exposure: EgressExposure::Placeholder,
                    match_host: LLM_EGRESS_HOST.to_string(),
                    match_prefix: "/".to_string(),
                    exact_path: false,
                    upstream_host: "127.0.0.1".to_string(),
                    upstream_port,
                    upstream_prefix: "/api/".to_string(),
                    upstream_tls: false,
                    cluster_name: "up-local".to_string(),
                    inject_headers: vec![(
                        "authorization".to_string(),
                        "Bearer platform-secret".to_string(),
                    )],
                    remove_headers: vec![],
                }],
            },
        ));
        let state = AppState {
            config: test_config(),
            policy_store: Some(store),
            client: Client::new(),
        };
        let uri = format!("/sandbox/{sandbox_id}/egress/llm/v1/messages?beta=true")
            .parse()
            .expect("valid uri");

        let mut sandbox_headers = bearer("attacker");
        sandbox_headers.insert(
            "x-joysafeter-sandbox-token",
            "runner-token".parse().unwrap(),
        );
        let response = proxy_entrypoint(
            State(state),
            Method::POST,
            OriginalUri(uri),
            sandbox_headers,
            Bytes::from_static(b"{\"ok\":true}"),
        )
        .await;

        let _ = shutdown_tx.send(());
        let _ = server.await;
        assert_eq!(response.status(), StatusCode::CREATED);
        assert_eq!(response.headers().get("x-upstream").unwrap(), "ok");
        let seen = seen_rx.recv().await.expect("upstream observed request");
        assert_eq!(seen.0, "/api/v1/messages?beta=true");
        assert_eq!(seen.1.as_deref(), Some("Bearer platform-secret"));
        assert!(!seen.2);
        assert_eq!(seen.3, br#"{"ok":true}"#);
    }

    #[tokio::test]
    async fn gateway_control_api_installs_and_revokes_policy() {
        let sandbox_id = Uuid::parse_str("018ff000-0000-7000-8000-000000000007").unwrap();
        let store = Arc::new(InMemoryGatewayPolicyStore::new());
        let state = AppState {
            config: test_config(),
            policy_store: Some(store.clone()),
            client: Client::new(),
        };

        let install = install_policy(
            State(state.clone()),
            Path(sandbox_id),
            control("control-token"),
            Json(InstallPolicyRequest {
                sandbox_token: "runner-token".to_string(),
                policy: test_egress_policy(),
            }),
        )
        .await;

        assert_eq!(install.status(), StatusCode::NO_CONTENT);
        let installed = store.get(sandbox_id).expect("policy installed");
        assert!(installed.verify_token("runner-token"));
        assert_eq!(installed.policy.credential_routes.len(), 1);

        let revoke = revoke_policy(State(state), Path(sandbox_id), control("control-token")).await;

        assert_eq!(revoke.status(), StatusCode::NO_CONTENT);
        assert!(store.get(sandbox_id).is_none());
    }

    #[tokio::test]
    async fn gateway_control_api_rejects_missing_invalid_and_empty_tokens() {
        let sandbox_id = Uuid::parse_str("018ff000-0000-7000-8000-000000000008").unwrap();
        let state = AppState {
            config: test_config(),
            policy_store: Some(Arc::new(InMemoryGatewayPolicyStore::new())),
            client: Client::new(),
        };

        let missing = install_policy(
            State(state.clone()),
            Path(sandbox_id),
            HeaderMap::new(),
            Json(InstallPolicyRequest {
                sandbox_token: "runner-token".to_string(),
                policy: test_egress_policy(),
            }),
        )
        .await;
        let invalid = install_policy(
            State(state.clone()),
            Path(sandbox_id),
            control("wrong-control-token"),
            Json(InstallPolicyRequest {
                sandbox_token: "runner-token".to_string(),
                policy: test_egress_policy(),
            }),
        )
        .await;
        let empty_sandbox_token = install_policy(
            State(state),
            Path(sandbox_id),
            control("control-token"),
            Json(InstallPolicyRequest {
                sandbox_token: " ".to_string(),
                policy: test_egress_policy(),
            }),
        )
        .await;

        assert_eq!(missing.status(), StatusCode::UNAUTHORIZED);
        assert_eq!(invalid.status(), StatusCode::UNAUTHORIZED);
        assert_eq!(empty_sandbox_token.status(), StatusCode::BAD_REQUEST);
    }

    #[tokio::test]
    async fn gateway_control_client_installs_and_revokes_policy_over_http() {
        let sandbox_id = Uuid::parse_str("018ff000-0000-7000-8000-000000000009").unwrap();
        let store = Arc::new(InMemoryGatewayPolicyStore::new());
        let policy_store: Arc<dyn GatewayPolicyStore> = store.clone();
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .expect("bind gateway");
        let base_url = format!("http://{}", listener.local_addr().expect("local addr"));
        let (shutdown_tx, shutdown_rx) = oneshot::channel::<()>();
        let server = tokio::spawn(async move {
            let _ = axum::serve(
                listener,
                app_with_policy_store(test_config(), Some(policy_store)),
            )
            .with_graceful_shutdown(async {
                let _ = shutdown_rx.await;
            })
            .await;
        });
        let client =
            EgressGatewayControlClient::new(&base_url, "control-token").expect("client builds");

        client
            .install_policy(sandbox_id, "runner-token", test_egress_policy())
            .await
            .expect("policy installs");
        let installed = store.get(sandbox_id).expect("policy installed");
        assert!(installed.verify_token("runner-token"));

        client
            .revoke_policy(sandbox_id)
            .await
            .expect("policy revoked");
        assert!(store.get(sandbox_id).is_none());

        let _ = shutdown_tx.send(());
        let _ = server.await;
    }

    #[test]
    fn gateway_path_parser_extracts_sandbox_route_and_rest_path() {
        let sandbox_id = Uuid::parse_str("018ff000-0000-7000-8000-000000000005").unwrap();
        let parsed = parse_gateway_path(&format!("/sandbox/{sandbox_id}/egress/llm/v1/messages"))
            .expect("valid gateway path");

        assert_eq!(parsed.0, sandbox_id);
        assert_eq!(parsed.1, "llm");
        assert_eq!(parsed.2, "/v1/messages");
    }

    #[test]
    fn gateway_extracts_sandbox_token_from_provider_auth_headers() {
        for header in ["x-api-key", "api-key", "x-goog-api-key"] {
            let mut headers = HeaderMap::new();
            headers.insert(header, "runner-token".parse().unwrap());

            assert_eq!(
                extract_sandbox_token(&headers).as_deref(),
                Some("runner-token"),
                "header {header} should be accepted as sandbox token"
            );
        }
    }

    #[test]
    fn gateway_builds_upstream_request_with_rewritten_path_query_and_injected_headers() {
        let sandbox_id = Uuid::parse_str("018ff000-0000-7000-8000-000000000011").unwrap();
        let route = EgressCredentialRoute {
            id: "llm".to_string(),
            kind: EgressKind::Llm,
            exposure: EgressExposure::Placeholder,
            match_host: LLM_EGRESS_HOST.to_string(),
            match_prefix: "/".to_string(),
            exact_path: false,
            upstream_host: "api.anthropic.com".to_string(),
            upstream_port: 443,
            upstream_prefix: "/anthropic/".to_string(),
            upstream_tls: true,
            cluster_name: "up-test".to_string(),
            inject_headers: vec![("authorization".to_string(), "Bearer platform".to_string())],
            remove_headers: vec!["x-extra-secret".to_string()],
        };
        let mut headers = bearer("attacker");
        headers.insert(
            "x-joysafeter-sandbox-token",
            "runner-token".parse().unwrap(),
        );
        headers.insert("x-api-key", "runner-token".parse().unwrap());
        headers.insert("x-extra-secret", "attacker-extra".parse().unwrap());
        headers.insert("x-trace-id", "trace-1".parse().unwrap());

        let BuiltUpstreamRequest { request, audit } = build_upstream_request(
            sandbox_id,
            &Client::new(),
            &route,
            Method::POST,
            &headers,
            Bytes::from_static(br#"{"model":"Claude-Opus-4.6"}"#),
            "/v1/messages",
            Some("beta=true"),
        )
        .expect("request builds");

        assert_eq!(request.method(), reqwest::Method::POST);
        assert_eq!(
            request.url().as_str(),
            "https://api.anthropic.com/anthropic/v1/messages?beta=true"
        );
        assert_eq!(
            request.headers().get("authorization").unwrap(),
            "Bearer platform"
        );
        assert!(request.headers().get("x-api-key").is_none());
        assert_eq!(request.headers().get("x-trace-id").unwrap(), "trace-1");
        assert!(request.headers().get("x-extra-secret").is_none());
        assert!(request
            .headers()
            .get("x-joysafeter-sandbox-token")
            .is_none());
        assert_eq!(audit.sandbox_id, sandbox_id);
        assert_eq!(audit.request_model.as_deref(), Some("Claude-Opus-4.6"));
        assert_eq!(audit.upstream_path, "/anthropic/v1/messages");
        assert_eq!(audit.upstream_query.as_deref(), Some("beta=true"));
        assert_eq!(audit.injected_header_names, vec!["authorization"]);
        assert!(audit
            .sandbox_auth_header_names
            .contains(&"authorization".to_string()));
        assert!(audit
            .sandbox_auth_header_names
            .contains(&"x-api-key".to_string()));
    }

    #[test]
    fn gateway_preserves_jdcloud_anthropic_base_url_contract() {
        let sandbox_id = Uuid::parse_str("018ff000-0000-7000-8000-000000000012").unwrap();
        let route = EgressCredentialRoute {
            id: "llm".to_string(),
            kind: EgressKind::Llm,
            exposure: EgressExposure::Placeholder,
            match_host: LLM_EGRESS_HOST.to_string(),
            match_prefix: "/".to_string(),
            exact_path: false,
            upstream_host: "ai-api.jdcloud.com".to_string(),
            upstream_port: 80,
            upstream_prefix: "/anthropic/".to_string(),
            upstream_tls: false,
            cluster_name: "up-jdcloud".to_string(),
            inject_headers: vec![("x-api-key".to_string(), "platform-secret".to_string())],
            remove_headers: vec![],
        };
        let mut headers = bearer("runner-token");
        headers.insert("anthropic-version", "2023-06-01".parse().unwrap());

        let BuiltUpstreamRequest { request, audit } = build_upstream_request(
            sandbox_id,
            &Client::new(),
            &route,
            Method::POST,
            &headers,
            Bytes::from_static(br#"{"model":"Claude-Opus-4.6","messages":[]}"#),
            "/v1/messages",
            None,
        )
        .expect("request builds");

        assert_eq!(
            request.url().as_str(),
            "http://ai-api.jdcloud.com/anthropic/v1/messages"
        );
        assert_eq!(
            request.headers().get("x-api-key").unwrap(),
            "platform-secret"
        );
        assert_eq!(
            request.headers().get("anthropic-version").unwrap(),
            "2023-06-01"
        );
        assert!(request.headers().get("authorization").is_none());
        assert_eq!(audit.upstream_host, "ai-api.jdcloud.com");
        assert_eq!(audit.upstream_port, 80);
        assert!(!audit.upstream_tls);
        assert_eq!(audit.upstream_path, "/anthropic/v1/messages");
        assert_eq!(audit.request_model.as_deref(), Some("Claude-Opus-4.6"));
    }

    #[test]
    fn gateway_rejects_exact_path_escape_before_forwarding() {
        let route = EgressCredentialRoute {
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
            cluster_name: "up-crm".to_string(),
            inject_headers: vec![("x-api-key".to_string(), "platform-key".to_string())],
            remove_headers: vec!["x-api-key".to_string()],
        };

        assert_eq!(
            upstream_path_for_route(&route, "/api/warning/getWarningDetailById")
                .expect("exact path allowed"),
            "/api/warning/getWarningDetailById"
        );
        assert!(matches!(
            upstream_path_for_route(&route, "/api/warning/getWarningDetailById/../admin"),
            Err(GatewayForwardError::RoutePathDenied)
        ));
    }

    fn test_config() -> GatewayConfig {
        GatewayConfig {
            host: "127.0.0.1".to_string(),
            port: 8088,
            require_sandbox_token: true,
            control_token_sha256: Some(hash_token("control-token")),
        }
    }

    fn bearer(token: &str) -> HeaderMap {
        let mut headers = HeaderMap::new();
        headers.insert(
            axum::http::header::AUTHORIZATION,
            format!("Bearer {token}").parse().unwrap(),
        );
        headers
    }

    fn control(token: &str) -> HeaderMap {
        let mut headers = HeaderMap::new();
        headers.insert("x-joysafeter-control-token", token.parse().unwrap());
        headers
    }

    fn test_egress_policy() -> SandboxEgressPolicy {
        SandboxEgressPolicy {
            allowlist_hosts: vec![],
            credential_routes: vec![EgressCredentialRoute {
                id: "llm".to_string(),
                kind: EgressKind::Llm,
                exposure: EgressExposure::Placeholder,
                match_host: LLM_EGRESS_HOST.to_string(),
                match_prefix: "/".to_string(),
                exact_path: false,
                upstream_host: "127.0.0.1".to_string(),
                upstream_port: 1,
                upstream_prefix: "/".to_string(),
                upstream_tls: false,
                cluster_name: "up-test".to_string(),
                inject_headers: vec![("authorization".to_string(), "Bearer secret".to_string())],
                remove_headers: vec!["authorization".to_string()],
            }],
        }
    }

    fn test_policy(sandbox_id: Uuid, token: &str) -> GatewaySandboxPolicy {
        GatewaySandboxPolicy::new(sandbox_id, Some(token), test_egress_policy())
    }
}
