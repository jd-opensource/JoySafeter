//! The `CredentialResolutionService` — the orchestrator HTTP endpoint the K8s
//! egress gateway calls (per request) to turn a `(sandbox_id, route_id)` into a
//! decrypted, ready-to-inject header. It is the HTTP face of the
//! [`CredentialBroker`]; the Docker/Envoy `ext_authz` face is added in SP-3
//! Task 5.
//!
//! Trust model (SP-3, user-confirmed): reuse the gateway token scheme. A caller
//! (a data-plane sidecar) authenticates with a shared service token, checked by
//! constant-time comparison of its SHA-256; a request may only resolve a
//! sandbox that has an installed policy in the [`ResolutionRegistry`]. The
//! endpoint never logs a resolved value; failures return the structured
//! `CREDENTIAL_RESOLVE_FAILED` error without leaking why.

use std::collections::HashMap;
use std::sync::{Arc, Mutex, OnceLock};

use axum::extract::State;
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::post;
use axum::{Json, Router};
use serde::{Deserialize, Serialize};
use subtle::ConstantTimeEq;
use uuid::Uuid;

use crate::egress::gateway::hash_token;
use crate::egress::policy::EgressCredentialRoute;
use crate::kernel::credential_broker::CredentialBroker;

/// Header the caller presents its service token in.
const RESOLVE_TOKEN_HEADER: &str = "x-joysafeter-resolve-token";
/// Structured error code returned on any resolution failure. Shared by the two
/// orchestrator-side faces (this HTTP `/resolve` service and the ext_authz gRPC
/// service) so the credential-plane denial carries one identifiable code. The
/// K8s gateway (lib crate) emits a matching literal — it cannot import kernel.
pub const CREDENTIAL_RESOLVE_FAILED: &str = "CREDENTIAL_RESOLVE_FAILED";

/// Keys for the non-secret per-route data the Docker Envoy LDS passes to the
/// orchestrator ext_authz `Check` via the filter's `context_extensions` map (it
/// arrives in `CheckRequest.attributes.context_extensions`). This is the correct
/// per-route channel: route `request_headers_to_add` are applied by the router
/// filter, which runs *after* ext_authz, so headers would not reach `Check`.
/// Must stay in sync between the LDS renderer and the ext_authz service.
pub const EXT_AUTHZ_SANDBOX_ID_KEY: &str = "joysafeter_sandbox_id";
pub const EXT_AUTHZ_ROUTE_ID_KEY: &str = "joysafeter_route_id";

/// Orchestrator-side registry mapping `(sandbox_id, route_id)` to the sandbox's
/// installed credential routes. Populated when the enforcer installs a
/// sandbox's egress policy (SP-3 Task 4); read by the resolution service to map
/// a request to a non-secret [`crate::egress::policy::CredentialRef`]. Holds no
/// secret material.
#[derive(Default)]
pub struct ResolutionRegistry {
    routes: Mutex<HashMap<Uuid, HashMap<String, EgressCredentialRoute>>>,
}

impl ResolutionRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    /// Install (replace) the credential routes for a sandbox.
    pub fn install(&self, sandbox_id: Uuid, routes: &[EgressCredentialRoute]) {
        let by_id = routes
            .iter()
            .map(|route| (route.id.clone(), route.clone()))
            .collect();
        self.routes
            .lock()
            .expect("resolution registry poisoned")
            .insert(sandbox_id, by_id);
    }

    /// Drop a sandbox's routes (on teardown).
    pub fn remove(&self, sandbox_id: Uuid) {
        self.routes
            .lock()
            .expect("resolution registry poisoned")
            .remove(&sandbox_id);
    }

    /// Look up one route by `(sandbox_id, route_id)`.
    pub fn get(&self, sandbox_id: Uuid, route_id: &str) -> Option<EgressCredentialRoute> {
        self.routes
            .lock()
            .expect("resolution registry poisoned")
            .get(&sandbox_id)?
            .get(route_id)
            .cloned()
    }
}

/// Process-wide credential-route registry. There is one orchestrator and one
/// installed-policy set, so a singleton (initialized lazily, like
/// `VaultCipher`'s key and the LLM provider registry) lets the enforce/teardown
/// path and the resolution HTTP server share it without threading an `Arc`
/// through every constructor in between.
pub fn global_resolution_registry() -> &'static Arc<ResolutionRegistry> {
    static REGISTRY: OnceLock<Arc<ResolutionRegistry>> = OnceLock::new();
    REGISTRY.get_or_init(|| Arc::new(ResolutionRegistry::new()))
}

/// Forget a sandbox's credential-plane state on teardown: drop its resolvable
/// routes from the registry (so a torn-down sandbox can no longer resolve a
/// credential) and evict any cached resolved secrets from the broker (so none
/// stay resident in memory past teardown). Idempotent — safe to call from every
/// teardown path, including ones where the sandbox never had credential routes.
///
/// This must run on EVERY teardown path (create-failure rollback AND steady-state
/// destroy), not just one, or a destroyed sandbox's `(sandbox_id → routes)` entry
/// leaks and its cached secret lingers.
pub fn forget_sandbox_credentials(sandbox_id: Uuid) {
    global_resolution_registry().remove(sandbox_id);
    if let Some(broker) = crate::kernel::credential_broker::credential_broker() {
        broker.evict(sandbox_id);
    }
}

/// Shared state for the resolution HTTP service.
#[derive(Clone)]
pub struct ResolutionState {
    pub registry: Arc<ResolutionRegistry>,
    pub broker: Arc<CredentialBroker>,
    /// SHA-256 of the service token callers must present. `None` => the endpoint
    /// fails closed (denies every request).
    pub service_token_sha256: Option<[u8; 32]>,
}

/// Build the resolution router: `POST /resolve`.
pub fn resolution_router(state: ResolutionState) -> Router {
    Router::new()
        .route("/resolve", post(resolve_handler))
        .with_state(state)
}

#[derive(Deserialize)]
struct ResolveRequest {
    sandbox_id: Uuid,
    route_id: String,
}

#[derive(Serialize)]
struct ResolveResponse {
    header: String,
    value: String,
}

async fn resolve_handler(
    State(state): State<ResolutionState>,
    headers: HeaderMap,
    Json(request): Json<ResolveRequest>,
) -> Response {
    if !caller_authorized(&state, &headers) {
        // Do not distinguish missing vs wrong token to the caller.
        return resolve_error(StatusCode::UNAUTHORIZED);
    }

    let Some(route) = state.registry.get(request.sandbox_id, &request.route_id) else {
        return resolve_error(StatusCode::NOT_FOUND);
    };

    match state.broker.resolve(request.sandbox_id, &route).await {
        Ok(header) => (
            StatusCode::OK,
            Json(ResolveResponse {
                header: header.name,
                value: header.value,
            }),
        )
            .into_response(),
        Err(e) => {
            // The error may reference secret coordinates but never a value; keep
            // it at debug and return an opaque failure to the caller.
            tracing::warn!(
                sandbox_id = %request.sandbox_id,
                route_id = %request.route_id,
                "credential resolution failed: {e}"
            );
            resolve_error(StatusCode::BAD_GATEWAY)
        }
    }
}

/// Constant-time check that the caller presented the configured service token.
/// Fails closed when no service token is configured.
fn caller_authorized(state: &ResolutionState, headers: &HeaderMap) -> bool {
    let Some(expected) = state.service_token_sha256 else {
        return false;
    };
    let Some(presented) = headers
        .get(RESOLVE_TOKEN_HEADER)
        .and_then(|value| value.to_str().ok())
    else {
        return false;
    };
    hash_token(presented).ct_eq(&expected).into()
}

fn resolve_error(status: StatusCode) -> Response {
    (
        status,
        Json(serde_json::json!({
            "code": CREDENTIAL_RESOLVE_FAILED,
            "message": "credential resolution denied",
        })),
    )
        .into_response()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::egress::policy::{CredentialRef, EgressExposure, EgressKind, InjectScheme};
    use axum::body::to_bytes;
    use sqlx::postgres::PgPoolOptions;
    use sqlx::PgPool;

    fn external_route(id: &str, secret_name: &str, secret_key: &str) -> EgressCredentialRoute {
        EgressCredentialRoute {
            id: id.to_string(),
            kind: EgressKind::External,
            exposure: EgressExposure::Transparent,
            match_host: "svc.example.com".to_string(),
            match_prefix: "/".to_string(),
            exact_path: false,
            upstream_host: "svc.example.com".to_string(),
            upstream_port: 443,
            upstream_prefix: "/".to_string(),
            upstream_tls: true,
            cluster_name: String::new(),
            credential_ref: CredentialRef::External {
                secret_name: secret_name.to_string(),
                secret_key: secret_key.to_string(),
                project_id: None,
            },
            inject_header: "x-api-key".to_string(),
            inject_scheme: InjectScheme::Raw,
            remove_headers: vec![],
        }
    }

    fn state_with(routes: Vec<(Uuid, EgressCredentialRoute)>, pool: PgPool) -> ResolutionState {
        let registry = Arc::new(ResolutionRegistry::new());
        for (sandbox_id, route) in routes {
            registry.install(sandbox_id, &[route]);
        }
        ResolutionState {
            registry,
            broker: Arc::new(CredentialBroker::new(pool)),
            service_token_sha256: Some(hash_token("service-token")),
        }
    }

    fn token_headers(token: &str) -> HeaderMap {
        let mut headers = HeaderMap::new();
        headers.insert(RESOLVE_TOKEN_HEADER, token.parse().unwrap());
        headers
    }

    async fn test_pool() -> Option<PgPool> {
        let Ok(url) = std::env::var("DATABASE_URL") else {
            eprintln!("skipping resolution DB test: DATABASE_URL is not set");
            return None;
        };
        Some(
            PgPoolOptions::new()
                .max_connections(2)
                .connect(&url)
                .await
                .expect("connect to migrated Postgres test database"),
        )
    }

    // A pool we can construct without a live DB for the auth/deny paths, which
    // never touch it. Uses lazy connect so no connection is opened.
    fn offline_pool() -> PgPool {
        PgPoolOptions::new()
            .max_connections(1)
            .connect_lazy("postgres://invalid:invalid@127.0.0.1:1/none")
            .expect("lazy pool")
    }

    #[tokio::test]
    async fn resolve_rejects_missing_token() {
        let state = state_with(vec![], offline_pool());
        let response = resolve_handler(
            State(state),
            HeaderMap::new(),
            Json(ResolveRequest {
                sandbox_id: Uuid::now_v7(),
                route_id: "external:svc".to_string(),
            }),
        )
        .await;
        assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    }

    #[tokio::test]
    async fn resolve_rejects_wrong_token() {
        let state = state_with(vec![], offline_pool());
        let response = resolve_handler(
            State(state),
            token_headers("not-the-service-token"),
            Json(ResolveRequest {
                sandbox_id: Uuid::now_v7(),
                route_id: "external:svc".to_string(),
            }),
        )
        .await;
        assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    }

    #[tokio::test]
    async fn resolve_fails_closed_without_configured_service_token() {
        let mut state = state_with(vec![], offline_pool());
        state.service_token_sha256 = None;
        let response = resolve_handler(
            State(state),
            token_headers("service-token"),
            Json(ResolveRequest {
                sandbox_id: Uuid::now_v7(),
                route_id: "external:svc".to_string(),
            }),
        )
        .await;
        assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    }

    #[tokio::test]
    async fn resolve_denies_unknown_sandbox_or_route() {
        let state = state_with(vec![], offline_pool());
        let response = resolve_handler(
            State(state),
            token_headers("service-token"),
            Json(ResolveRequest {
                sandbox_id: Uuid::now_v7(),
                route_id: "external:svc".to_string(),
            }),
        )
        .await;
        assert_eq!(response.status(), StatusCode::NOT_FOUND);
    }

    #[test]
    fn forget_sandbox_credentials_drops_registry_entry() {
        // A torn-down sandbox must no longer resolve: forget removes its routes
        // from the registry (broker eviction is a no-op here — no cache entry).
        let sandbox_id = Uuid::now_v7();
        global_resolution_registry()
            .install(sandbox_id, &[external_route("external:svc", "svc", "API_KEY")]);
        assert!(global_resolution_registry()
            .get(sandbox_id, "external:svc")
            .is_some());

        forget_sandbox_credentials(sandbox_id);

        assert!(global_resolution_registry()
            .get(sandbox_id, "external:svc")
            .is_none());
    }

    #[tokio::test]
    async fn resolve_returns_formatted_header_for_authorized_request() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let sandbox_id = Uuid::now_v7();
        let secret_name = format!("resolve-test-secret-{sandbox_id}");
        sqlx::query(r#"INSERT INTO joysafeter_secrets (id, name, data) VALUES ($1, $2, $3)"#)
            .bind(Uuid::now_v7())
            .bind(&secret_name)
            .bind(serde_json::json!({ "API_KEY": "resolved-plain-value" }))
            .execute(&pool)
            .await
            .expect("insert secret");

        let route = external_route("external:svc", &secret_name, "API_KEY");
        let state = state_with(vec![(sandbox_id, route)], pool.clone());

        let response = resolve_handler(
            State(state),
            token_headers("service-token"),
            Json(ResolveRequest {
                sandbox_id,
                route_id: "external:svc".to_string(),
            }),
        )
        .await;
        assert_eq!(response.status(), StatusCode::OK);
        let body = to_bytes(response.into_body(), 4096).await.expect("body");
        let json: serde_json::Value = serde_json::from_slice(&body).expect("json");
        assert_eq!(json["header"], "x-api-key");
        assert_eq!(json["value"], "resolved-plain-value");

        sqlx::query("DELETE FROM joysafeter_secrets WHERE name = $1")
            .bind(&secret_name)
            .execute(&pool)
            .await
            .expect("cleanup");
    }
}
