//! Envoy `ext_authz` gRPC service — the Docker data plane's face of the
//! credential plane, the counterpart to the K8s gateway's HTTP `/resolve`.
//!
//! Per-request, the Docker Envoy calls `envoy.service.auth.v3.Authorization/Check`
//! on the orchestrator's gRPC server. The LDS attaches the non-secret
//! `(sandbox_id, route_id)` to each credential route via the ext_authz filter's
//! per-route `context_extensions`; they arrive in
//! `CheckRequest.attributes.context_extensions`. This handler maps them to the
//! installed route, resolves the credential through the SAME [`CredentialBroker`]
//! and `ResolutionRegistry` the HTTP `/resolve` uses, and returns an
//! `OkHttpResponse` whose `headers` Envoy injects upstream. One credential
//! plane, two data planes.
//!
//! `context_extensions` (not request headers) is the correct channel: a route's
//! `request_headers_to_add` are applied by the router filter, which runs *after*
//! ext_authz, so headers would never reach `Check`.
//!
//! Trust model: this rides the orchestrator's existing gRPC server, the same
//! channel Envoy already uses for xDS — Envoy is an orchestrator-controlled
//! sidecar, so it inherits the xDS trust boundary (no per-call token).

use std::sync::Arc;

use envoy_types::pb::envoy::config::core::v3::{
    header_value_option::HeaderAppendAction, HeaderValue, HeaderValueOption,
};
use envoy_types::pb::envoy::service::auth::v3::{
    authorization_server::Authorization, check_response::HttpResponse, CheckRequest, CheckResponse,
    OkHttpResponse,
};
use envoy_types::pb::google::rpc::Status as RpcStatus;
use tonic::{Request, Response, Status};
use uuid::Uuid;

use crate::kernel::credential_broker::CredentialBroker;
use crate::kernel::credential_resolution::{
    global_resolution_registry, CREDENTIAL_RESOLVE_FAILED, EXT_AUTHZ_ROUTE_ID_KEY,
    EXT_AUTHZ_SANDBOX_ID_KEY,
};

/// google.rpc.Code::Ok.
const RPC_OK: i32 = 0;
/// google.rpc.Code::PermissionDenied.
const RPC_PERMISSION_DENIED: i32 = 7;

/// The orchestrator's ext_authz service. Holds only the broker; the route
/// registry is the process-wide singleton shared with the HTTP resolver.
pub struct ExtAuthzService {
    broker: Arc<CredentialBroker>,
}

impl ExtAuthzService {
    pub fn new(broker: Arc<CredentialBroker>) -> Self {
        Self { broker }
    }
}

#[tonic::async_trait]
impl Authorization for ExtAuthzService {
    async fn check(
        &self,
        request: Request<CheckRequest>,
    ) -> Result<Response<CheckResponse>, Status> {
        let context = request
            .into_inner()
            .attributes
            .map(|attrs| attrs.context_extensions)
            .unwrap_or_default();

        // No identity context => not a credential-injection route (per-route
        // ext_authz should prevent this, but be robust): allow with no injection.
        let (Some(sandbox_id_raw), Some(route_id)) = (
            context.get(EXT_AUTHZ_SANDBOX_ID_KEY),
            context.get(EXT_AUTHZ_ROUTE_ID_KEY),
        ) else {
            return Ok(Response::new(ok_response(None)));
        };

        let Ok(sandbox_id) = Uuid::parse_str(sandbox_id_raw) else {
            return Ok(Response::new(deny_response()));
        };
        let Some(route) = global_resolution_registry().get(sandbox_id, route_id) else {
            return Ok(Response::new(deny_response()));
        };

        match self.broker.resolve(sandbox_id, &route).await {
            Ok(header) => Ok(Response::new(ok_response(Some((
                header.name,
                header.value,
            ))))),
            Err(e) => {
                // Never log the resolved value; only the non-secret coordinates.
                tracing::warn!(
                    sandbox_id = %sandbox_id,
                    route_id = %route_id,
                    "ext_authz credential resolution failed: {e}"
                );
                Ok(Response::new(deny_response()))
            }
        }
    }
}

/// Build an OK CheckResponse. When `injected` is present, Envoy adds that header
/// (overriding any sandbox-supplied one) before forwarding upstream.
fn ok_response(injected: Option<(String, String)>) -> CheckResponse {
    let headers = injected
        .into_iter()
        .map(|(name, value)| HeaderValueOption {
            header: Some(HeaderValue {
                key: name,
                value,
                ..Default::default()
            }),
            append_action: HeaderAppendAction::OverwriteIfExistsOrAdd as i32,
            ..Default::default()
        })
        .collect();
    CheckResponse {
        status: Some(RpcStatus {
            code: RPC_OK,
            ..Default::default()
        }),
        http_response: Some(HttpResponse::OkResponse(OkHttpResponse {
            headers,
            ..Default::default()
        })),
        ..Default::default()
    }
}

/// Build a deny CheckResponse. A non-OK status makes Envoy reject the request
/// (default 403); the sandbox never reaches the upstream without its credential.
fn deny_response() -> CheckResponse {
    CheckResponse {
        status: Some(RpcStatus {
            code: RPC_PERMISSION_DENIED,
            message: format!("{CREDENTIAL_RESOLVE_FAILED}: credential resolution denied"),
            ..Default::default()
        }),
        ..Default::default()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use envoy_types::pb::envoy::service::auth::v3::AttributeContext;
    use std::collections::HashMap;

    /// A CheckRequest carrying the given ext_authz `context_extensions`.
    fn check_request(context: &[(&str, &str)]) -> Request<CheckRequest> {
        let context_extensions: HashMap<String, String> = context
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect();
        Request::new(CheckRequest {
            attributes: Some(AttributeContext {
                context_extensions,
                ..Default::default()
            }),
        })
    }

    fn status_code(response: &CheckResponse) -> i32 {
        response.status.as_ref().map(|s| s.code).unwrap_or(-1)
    }

    fn service() -> ExtAuthzService {
        // The DB pool is only touched on a registry hit; these tests exercise the
        // no-context and unknown-route paths, which never resolve.
        use sqlx::postgres::PgPoolOptions;
        let pool = PgPoolOptions::new()
            .max_connections(1)
            .connect_lazy("postgres://invalid:invalid@127.0.0.1:1/none")
            .expect("lazy pool");
        ExtAuthzService::new(Arc::new(CredentialBroker::new(pool)))
    }

    #[tokio::test]
    async fn check_allows_without_injection_when_context_absent() {
        let response = service()
            .check(check_request(&[]))
            .await
            .expect("check")
            .into_inner();
        assert_eq!(status_code(&response), RPC_OK);
        // OK, but injects nothing.
        match response.http_response {
            Some(HttpResponse::OkResponse(ok)) => assert!(ok.headers.is_empty()),
            other => panic!("expected OkResponse, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn check_denies_unknown_sandbox_or_route() {
        let response = service()
            .check(check_request(&[
                (EXT_AUTHZ_SANDBOX_ID_KEY, &Uuid::now_v7().to_string()),
                (EXT_AUTHZ_ROUTE_ID_KEY, "llm"),
            ]))
            .await
            .expect("check")
            .into_inner();
        assert_eq!(status_code(&response), RPC_PERMISSION_DENIED);
    }

    #[tokio::test]
    async fn check_denies_malformed_sandbox_id() {
        let response = service()
            .check(check_request(&[
                (EXT_AUTHZ_SANDBOX_ID_KEY, "not-a-uuid"),
                (EXT_AUTHZ_ROUTE_ID_KEY, "llm"),
            ]))
            .await
            .expect("check")
            .into_inner();
        assert_eq!(status_code(&response), RPC_PERMISSION_DENIED);
    }

    #[test]
    fn deny_response_carries_structured_error_code() {
        // Both credential-plane faces surface the same structured code; the
        // ext_authz denial embeds it in the gRPC status message.
        let response = deny_response();
        let message = response
            .status
            .as_ref()
            .map(|s| s.message.clone())
            .unwrap_or_default();
        assert!(message.contains(CREDENTIAL_RESOLVE_FAILED));
    }
}
