//! Envoy `ext_authz` gRPC service — the data planes' shared face of the
//! credential plane.
//!
//! Per-request, the Docker Envoy calls `envoy.service.auth.v3.Authorization/Check`
//! on the orchestrator's gRPC server. The LDS attaches the non-secret
//! `(sandbox_id, route_id)` to each credential route via the ext_authz filter's
//! per-route `context_extensions`; they arrive in
//! `CheckRequest.attributes.context_extensions`. This handler maps them to the
//! installed route, resolves the credential through the SAME [`CredentialBroker`]
//! and `ResolutionRegistry`, and returns an `OkHttpResponse` whose `headers`
//! Envoy injects upstream. One credential plane, two data planes.
//!
//! `context_extensions` (not request headers) is the correct channel: a route's
//! `request_headers_to_add` are applied by the router filter, which runs *after*
//! ext_authz, so headers would never reach `Check`.
//!
//! Trust model: Docker uses a per-sandbox Unix socket as the caller-isolation
//! boundary. The shared Kubernetes Envoy fleet additionally requires the
//! sandbox's live runner token in the route's placeholder credential header;
//! the handler validates it against PostgreSQL before resolving any secret.

use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::Arc;

use envoy_types::pb::envoy::config::core::v3::{
    header_value_option::HeaderAppendAction, HeaderValue, HeaderValueOption,
};
use envoy_types::pb::envoy::service::auth::v3::{
    authorization_server::{Authorization, AuthorizationServer},
    check_response::HttpResponse,
    CheckRequest, CheckResponse, OkHttpResponse,
};
use envoy_types::pb::google::rpc::Status as RpcStatus;
use sqlx::PgPool;
use subtle::ConstantTimeEq;
use tokio::task::JoinHandle;
use tonic::transport::{Certificate, Identity, Server, ServerTlsConfig};
use tonic::{Request, Response, Status};
use uuid::Uuid;
use x509_parser::extensions::GeneralName;
use x509_parser::parse_x509_certificate;

use crate::egress::authority::DesiredSandboxPolicy;
use crate::egress::policy::EgressCredentialRoute;
use crate::kernel::credential_broker::{
    format_header_value, init_credential_broker, CredentialBroker,
};
use crate::kernel::credential_resolution::{
    global_resolution_registry, CREDENTIAL_RESOLVE_FAILED, EXT_AUTHZ_ROUTE_ID_KEY,
    EXT_AUTHZ_SANDBOX_ID_KEY,
};

pub const EXT_AUTHZ_GROUP_KEY: &str = "joysafeter_group_key";
pub const EXT_AUTHZ_POLICY_GENERATION_KEY: &str = "joysafeter_policy_generation";

/// google.rpc.Code::Ok.
const RPC_OK: i32 = 0;
/// google.rpc.Code::PermissionDenied.
const RPC_PERMISSION_DENIED: i32 = 7;

/// The orchestrator's ext_authz service. Holds only the broker; the route
/// registry is the process-wide singleton shared with the HTTP resolver.
pub struct ExtAuthzService {
    broker: Arc<CredentialBroker>,
    pool: Option<PgPool>,
    required_client_dns_san: Option<Arc<str>>,
}

impl ExtAuthzService {
    pub fn new(broker: Arc<CredentialBroker>) -> Self {
        Self {
            broker,
            pool: None,
            required_client_dns_san: None,
        }
    }

    pub fn with_postgres(broker: Arc<CredentialBroker>, pool: PgPool) -> Self {
        Self {
            broker,
            pool: Some(pool),
            required_client_dns_san: None,
        }
    }

    fn require_client_dns_san(mut self, client_dns_san: String) -> Self {
        self.required_client_dns_san = Some(Arc::from(client_dns_san));
        self
    }

    async fn route_for_context(
        &self,
        sandbox_id: Uuid,
        route_id: &str,
        context: &HashMap<String, String>,
    ) -> anyhow::Result<Option<(EgressCredentialRoute, Option<String>)>> {
        let group_key = context.get(EXT_AUTHZ_GROUP_KEY);
        let generation = context.get(EXT_AUTHZ_POLICY_GENERATION_KEY);
        match (group_key, generation) {
            (None, None) => Ok(global_resolution_registry()
                .get(sandbox_id, route_id)
                .map(|route| (route, None))),
            (Some(group_key), Some(generation)) => {
                let generation = generation.parse::<i64>()?;
                anyhow::ensure!(generation > 0, "policy generation must be positive");
                let Some(pool) = self.pool.as_ref() else {
                    return Ok(None);
                };
                let route =
                    lookup_active_applied_route(pool, group_key, generation, sandbox_id, route_id)
                        .await?;
                Ok(route.map(|route| (route, Some(format!("{group_key}:{generation}")))))
            }
            _ => Ok(None),
        }
    }
}

#[tonic::async_trait]
impl Authorization for ExtAuthzService {
    async fn check(
        &self,
        request: Request<CheckRequest>,
    ) -> Result<Response<CheckResponse>, Status> {
        if let Some(expected_dns_san) = self.required_client_dns_san.as_deref() {
            verify_peer_dns_san(&request, expected_dns_san)
                .map_err(PeerDnsSanError::into_status)?;
        }
        let attributes = request.into_inner().attributes.unwrap_or_default();
        let headers = attributes
            .request
            .and_then(|request| request.http)
            .map(|http| http.headers)
            .unwrap_or_default();
        let context = attributes.context_extensions;

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
        let (route, policy_identity) =
            match self.route_for_context(sandbox_id, route_id, &context).await {
                Ok(Some(route)) => route,
                Ok(None) => return Ok(Response::new(deny_response())),
                Err(error) => {
                    tracing::warn!(
                        %sandbox_id,
                        route_id = %route_id,
                        %error,
                        "ext_authz durable route lookup failed"
                    );
                    return Ok(Response::new(deny_response()));
                }
            };

        if policy_identity.is_some() {
            let Some(pool) = self.pool.as_ref() else {
                return Ok(Response::new(deny_response()));
            };
            match validate_sandbox_identity(pool, sandbox_id, &route, &headers).await {
                Ok(true) => {}
                Ok(false) => {
                    let identity_header = route.inject_header.to_ascii_lowercase();
                    let actual = headers.get(&identity_header);
                    tracing::debug!(
                        %sandbox_id,
                        route_id = %route_id,
                        identity_header = %identity_header,
                        header_present = actual.is_some(),
                        actual_length = actual.map_or(0, String::len),
                        actual_has_bearer_prefix = actual.is_some_and(|value| value.starts_with("Bearer ")),
                        header_names = ?headers.keys().collect::<Vec<_>>(),
                        "ext_authz sandbox identity mismatch"
                    );
                    return Ok(Response::new(deny_response()));
                }
                Err(error) => {
                    tracing::warn!(
                        %sandbox_id,
                        route_id = %route_id,
                        %error,
                        "ext_authz sandbox identity lookup failed"
                    );
                    return Ok(Response::new(deny_response()));
                }
            }
        }

        match self
            .broker
            .resolve_versioned(sandbox_id, &route, policy_identity.as_deref())
            .await
        {
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

async fn validate_sandbox_identity(
    pool: &PgPool,
    sandbox_id: Uuid,
    route: &EgressCredentialRoute,
    headers: &HashMap<String, String>,
) -> anyhow::Result<bool> {
    let runner_token = sqlx::query_scalar::<_, String>(
        r#"
        SELECT config->>'runner_token'
        FROM joysafeter_sandboxes
        WHERE id = $1
          AND provider IN ('docker', 'k8s', 'kubernetes')
          AND status IN ('creating', 'provisioning', 'idle', 'running')
          AND destroyed_at IS NULL
          AND NULLIF(BTRIM(config->>'runner_token'), '') IS NOT NULL
        "#,
    )
    .bind(sandbox_id)
    .fetch_optional(pool)
    .await?;
    let Some(runner_token) = runner_token else {
        return Ok(false);
    };
    Ok(identity_header_matches(route, &runner_token, headers))
}

fn identity_header_matches(
    route: &EgressCredentialRoute,
    runner_token: &str,
    headers: &HashMap<String, String>,
) -> bool {
    let header_name = route.inject_header.to_ascii_lowercase();
    let Some(actual) = headers.get(&header_name) else {
        return false;
    };
    let expected = format_header_value(&route.inject_scheme, runner_token);
    bool::from(actual.as_bytes().ct_eq(expected.as_bytes()))
}

async fn lookup_active_applied_route(
    pool: &PgPool,
    group_key: &str,
    generation: i64,
    sandbox_id: Uuid,
    route_id: &str,
) -> anyhow::Result<Option<EgressCredentialRoute>> {
    let raw = sqlx::query_scalar::<_, serde_json::Value>(
        r#"
        WITH latest_desired AS (
            SELECT g.generation, COALESCE(a.state, '') AS apply_state
            FROM joysafeter_egress_group_generations AS g
            LEFT JOIN joysafeter_egress_apply_status AS a
              ON a.group_key = g.group_key AND a.generation = g.generation
            WHERE g.group_key = $1 AND g.state = 'desired'
            ORDER BY g.generation DESC
            LIMIT 1
        ), active_generation AS (
            SELECT CASE
                WHEN latest_desired.apply_state = 'applied' THEN latest_desired.generation
                ELSE (
                    SELECT MAX(previous.generation)
                    FROM joysafeter_egress_group_generations AS previous
                    JOIN joysafeter_egress_apply_status AS previous_apply
                      ON previous_apply.group_key = previous.group_key
                     AND previous_apply.generation = previous.generation
                    WHERE previous.group_key = $1
                      AND previous.generation < latest_desired.generation
                      AND previous_apply.state = 'applied'
                )
            END AS generation
            FROM latest_desired
        )
        SELECT requested.desired_policies
        FROM joysafeter_egress_group_generations AS requested
        JOIN active_generation ON active_generation.generation = requested.generation
        WHERE requested.group_key = $1 AND requested.generation = $2
        "#,
    )
    .bind(group_key)
    .bind(generation)
    .fetch_optional(pool)
    .await?;
    let Some(raw) = raw else {
        return Ok(None);
    };
    let policies = serde_json::from_value::<Vec<DesiredSandboxPolicy>>(raw)?;
    let Some(policy) = policies
        .iter()
        .find(|policy| policy.sandbox_id == sandbox_id.to_string())
    else {
        return Ok(None);
    };
    policy
        .credential_routes
        .iter()
        .find(|route| route.route_id == route_id)
        .map(|route| route.to_runtime_route())
        .transpose()
}

#[derive(Debug, Clone)]
pub struct ExtAuthzTlsConfig {
    pub enabled: bool,
    pub cert_file: String,
    pub key_file: String,
    pub client_ca_file: String,
    pub client_dns_san: String,
}

pub async fn start_ext_authz_server(
    addr: SocketAddr,
    pool: PgPool,
    tls: ExtAuthzTlsConfig,
) -> anyhow::Result<JoinHandle<()>> {
    let broker = init_credential_broker(pool.clone());
    let service = if tls.enabled {
        anyhow::ensure!(
            !tls.client_dns_san.trim().is_empty(),
            "Envoy ext_authz mTLS requires an expected client DNS SAN"
        );
        ExtAuthzService::with_postgres(broker, pool)
            .require_client_dns_san(tls.client_dns_san.clone())
    } else {
        ExtAuthzService::with_postgres(broker, pool)
    };
    let service = AuthorizationServer::new(service);
    let mut builder = Server::builder()
        .tcp_keepalive(Some(std::time::Duration::from_secs(30)))
        .http2_keepalive_interval(Some(std::time::Duration::from_secs(30)))
        .http2_keepalive_timeout(Some(std::time::Duration::from_secs(10)));
    if tls.enabled {
        let certificate = tokio::fs::read(&tls.cert_file).await?;
        let private_key = tokio::fs::read(&tls.key_file).await?;
        let client_ca = tokio::fs::read(&tls.client_ca_file).await?;
        builder = builder.tls_config(
            ServerTlsConfig::new()
                .identity(Identity::from_pem(certificate, private_key))
                .client_ca_root(Certificate::from_pem(client_ca)),
        )?;
    }
    Ok(tokio::spawn(async move {
        tracing::info!(%addr, mtls = tls.enabled, "dedicated Envoy ext_authz server listening");
        if let Err(error) = builder.add_service(service).serve(addr).await {
            tracing::error!(%error, "dedicated Envoy ext_authz server failed");
        }
    }))
}

enum PeerDnsSanError {
    Unauthenticated(&'static str),
    PermissionDenied(&'static str),
}

impl PeerDnsSanError {
    fn into_status(self) -> Status {
        match self {
            Self::Unauthenticated(message) => Status::unauthenticated(message),
            Self::PermissionDenied(message) => Status::permission_denied(message),
        }
    }
}

fn verify_peer_dns_san<T>(
    request: &Request<T>,
    expected_dns_san: &str,
) -> Result<(), PeerDnsSanError> {
    let certificates = request
        .peer_certs()
        .ok_or(PeerDnsSanError::Unauthenticated(
            "Envoy client certificate is required",
        ))?;
    let certificate = certificates
        .first()
        .ok_or(PeerDnsSanError::Unauthenticated(
            "Envoy client certificate is required",
        ))?;
    let (_, certificate) = parse_x509_certificate(certificate.as_ref())
        .map_err(|_| PeerDnsSanError::Unauthenticated("Envoy client certificate is invalid"))?;
    let subject_alt_name = certificate
        .subject_alternative_name()
        .map_err(|_| PeerDnsSanError::Unauthenticated("Envoy client certificate SAN is invalid"))?
        .ok_or(PeerDnsSanError::PermissionDenied(
            "Envoy client certificate has no DNS SAN",
        ))?;
    let allowed = has_exact_dns_san(&subject_alt_name.value.general_names, expected_dns_san);
    if allowed {
        Ok(())
    } else {
        Err(PeerDnsSanError::PermissionDenied(
            "Envoy client certificate identity is not allowed",
        ))
    }
}

fn has_exact_dns_san(names: &[GeneralName<'_>], expected_dns_san: &str) -> bool {
    names
        .iter()
        .any(|name| matches!(name, GeneralName::DNSName(value) if *value == expected_dns_san))
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
    use crate::egress::authority::NodeSelector;
    use crate::egress::policy::InjectScheme;
    use envoy_types::pb::envoy::service::auth::v3::{attribute_context, AttributeContext};
    use sqlx::postgres::PgPoolOptions;
    use std::collections::HashMap;

    /// A CheckRequest carrying the given ext_authz `context_extensions`.
    fn check_request(context: &[(&str, &str)]) -> Request<CheckRequest> {
        check_request_with_headers(context, &[])
    }

    fn check_request_with_headers(
        context: &[(&str, &str)],
        headers: &[(&str, &str)],
    ) -> Request<CheckRequest> {
        let context_extensions: HashMap<String, String> = context
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect();
        let headers = headers
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect();
        Request::new(CheckRequest {
            attributes: Some(AttributeContext {
                context_extensions,
                request: Some(attribute_context::Request {
                    http: Some(attribute_context::HttpRequest {
                        headers,
                        ..Default::default()
                    }),
                    ..Default::default()
                }),
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

    fn database_url() -> Option<String> {
        std::env::var("JOYSAFETER_TEST_DATABASE_URL")
            .ok()
            .or_else(|| std::env::var("DATABASE_URL").ok())
            .map(|url| url.replace("postgresql+asyncpg://", "postgres://"))
    }

    fn desired_policy(sandbox_id: Uuid, secret_name: &str) -> serde_json::Value {
        serde_json::json!([{
            "sandbox_id": sandbox_id,
            "mode": "limited",
            "credential_routes": [{
                "route_id": "llm:primary",
                "kind": "llm",
                "match_authority": "llm-egress.internal",
                "match_path": {"kind": "prefix", "value": "/v1"},
                "methods": ["POST"],
                "upstream": {
                    "scheme": "https",
                    "host": "api.example.com",
                    "port": 443,
                    "base_path": "/v1",
                    "protocol": "auto"
                },
                "credential_ref": {
                    "kind": "llm",
                    "secret_name": secret_name,
                    "secret_key": "api_key"
                },
                "inject_header": "authorization",
                "inject_scheme": {"kind": "bearer"},
                "remove_headers": ["authorization"],
                "timeout_profile": "streaming",
                "websocket": false
            }],
            "allowed_public_hosts": [],
            "denied_cidrs": ["10.0.0.0/8"]
        }])
    }

    fn runtime_route(sandbox_id: Uuid) -> EgressCredentialRoute {
        let policies = serde_json::from_value::<Vec<DesiredSandboxPolicy>>(desired_policy(
            sandbox_id,
            "secret-v1",
        ))
        .unwrap();
        policies[0].credential_routes[0].to_runtime_route().unwrap()
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
    async fn dedicated_mtls_service_rejects_request_without_peer_certificate() {
        let error = service()
            .require_client_dns_san(
                "joysafeter-egress-envoy.joysafeter-egress.svc.cluster.local".to_string(),
            )
            .check(check_request(&[]))
            .await
            .expect_err("missing peer certificate must fail closed");
        assert_eq!(error.code(), tonic::Code::Unauthenticated);
    }

    #[test]
    fn client_identity_requires_exact_dns_san_and_rejects_wildcards() {
        let expected = "joysafeter-egress-envoy.joysafeter-egress.svc.cluster.local";
        assert!(has_exact_dns_san(
            &[GeneralName::DNSName(expected)],
            expected
        ));
        assert!(!has_exact_dns_san(
            &[GeneralName::DNSName(
                "*.joysafeter-egress.svc.cluster.local"
            )],
            expected
        ));
        assert!(!has_exact_dns_san(
            &[GeneralName::DNSName(
                "other-client.joysafeter-egress.svc.cluster.local"
            )],
            expected
        ));
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

    #[tokio::test]
    async fn check_denies_incomplete_durable_context() {
        let response = service()
            .check(check_request_with_headers(
                &[
                    (EXT_AUTHZ_SANDBOX_ID_KEY, &Uuid::now_v7().to_string()),
                    (EXT_AUTHZ_ROUTE_ID_KEY, "llm"),
                    (EXT_AUTHZ_GROUP_KEY, "group-only"),
                ],
                &[("authorization", "Bearer runner-token")],
            ))
            .await
            .expect("check")
            .into_inner();
        assert_eq!(status_code(&response), RPC_PERMISSION_DENIED);
    }

    #[test]
    fn identity_header_match_supports_all_injection_schemes() {
        let mut route = runtime_route(Uuid::now_v7());
        let token = "runner-token";

        let bearer = HashMap::from([(
            "authorization".to_string(),
            "Bearer runner-token".to_string(),
        )]);
        assert!(identity_header_matches(&route, token, &bearer));
        assert!(!identity_header_matches(
            &route,
            token,
            &HashMap::from([(
                "authorization".to_string(),
                "Bearer wrong-token".to_string(),
            )]),
        ));
        assert!(!identity_header_matches(&route, token, &HashMap::new()));

        route.inject_header = "X-API-Key".to_string();
        route.inject_scheme = InjectScheme::Raw;
        assert!(identity_header_matches(
            &route,
            token,
            &HashMap::from([("x-api-key".to_string(), token.to_string())]),
        ));

        route.inject_header = "authorization".to_string();
        route.inject_scheme = InjectScheme::Basic {
            username: "runner".to_string(),
        };
        let expected = format_header_value(&route.inject_scheme, token);
        assert!(identity_header_matches(
            &route,
            token,
            &HashMap::from([("authorization".to_string(), expected)]),
        ));
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

    #[tokio::test]
    async fn durable_lookup_keeps_lkg_until_successor_is_applied() {
        let Some(url) = database_url() else {
            eprintln!("skipping durable ext_authz PostgreSQL test: DATABASE_URL is not set");
            return;
        };
        let pool = PgPoolOptions::new()
            .max_connections(4)
            .connect(&url)
            .await
            .expect("connect to migrated PostgreSQL test database");
        let sandbox_id = Uuid::now_v7();
        let selector = NodeSelector {
            deployment_id: format!("authz-test-{}", Uuid::now_v7().simple()),
            environment: "test".to_string(),
            region: "local".to_string(),
            provider: "k8s".to_string(),
            shard_id: "0".to_string(),
            host_id: None,
            envoy_version: "1.39.0".to_string(),
            config_schema_version: "1".to_string(),
        }
        .normalize()
        .unwrap();
        let group_key = selector.group_key().unwrap();
        let selector_json = serde_json::to_value(&selector).unwrap();

        for (generation, state, secret_name, hash_char) in [
            (1_i64, "superseded", "secret-v1", "1"),
            (2_i64, "desired", "secret-v2", "2"),
        ] {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_egress_group_generations (
                    id, group_key, generation, node_selector, policy_schema_version,
                    desired_policies, content_sha256, state
                ) VALUES ($1, $2, $3, $4, 1, $5, $6, $7)
                "#,
            )
            .bind(Uuid::now_v7())
            .bind(&group_key)
            .bind(generation)
            .bind(&selector_json)
            .bind(desired_policy(sandbox_id, secret_name))
            .bind(hash_char.repeat(64))
            .bind(state)
            .execute(&pool)
            .await
            .unwrap();
        }
        sqlx::query(
            r#"
            INSERT INTO joysafeter_egress_apply_status (
                id, group_key, generation, xds_version, required_type_urls, state,
                connected_nodes, required_acks, acked_acks
            ) VALUES ($1, $2, 1, 'v1', '["listener"]'::jsonb, 'applied', 1, 1, 1),
                     ($3, $2, 2, 'v2', '["listener"]'::jsonb, 'pending', 1, 1, 0)
            "#,
        )
        .bind(Uuid::now_v7())
        .bind(&group_key)
        .bind(Uuid::now_v7())
        .execute(&pool)
        .await
        .unwrap();

        let old = lookup_active_applied_route(&pool, &group_key, 1, sandbox_id, "llm:primary")
            .await
            .unwrap()
            .expect("last-known-good route remains active");
        assert!(matches!(
            old.credential_ref,
            crate::egress::policy::CredentialRef::Llm { ref secret_name, .. }
                if secret_name == "secret-v1"
        ));
        assert!(
            lookup_active_applied_route(&pool, &group_key, 2, sandbox_id, "llm:primary")
                .await
                .unwrap()
                .is_none()
        );

        sqlx::query(
            "UPDATE joysafeter_egress_apply_status SET state = 'applied' WHERE group_key = $1 AND generation = 2",
        )
        .bind(&group_key)
        .execute(&pool)
        .await
        .unwrap();
        assert!(
            lookup_active_applied_route(&pool, &group_key, 1, sandbox_id, "llm:primary")
                .await
                .unwrap()
                .is_none()
        );
        let new = lookup_active_applied_route(&pool, &group_key, 2, sandbox_id, "llm:primary")
            .await
            .unwrap()
            .expect("new applied route becomes active");
        assert!(matches!(
            new.credential_ref,
            crate::egress::policy::CredentialRef::Llm { ref secret_name, .. }
                if secret_name == "secret-v2"
        ));

        sqlx::query("DELETE FROM joysafeter_egress_group_generations WHERE group_key = $1")
            .bind(&group_key)
            .execute(&pool)
            .await
            .unwrap();
    }

    #[tokio::test]
    async fn durable_identity_requires_live_k8s_sandbox_and_exact_runner_token() {
        let Some(url) = database_url() else {
            eprintln!("skipping durable ext_authz identity test: DATABASE_URL is not set");
            return;
        };
        let pool = PgPoolOptions::new()
            .max_connections(2)
            .connect(&url)
            .await
            .expect("connect to migrated PostgreSQL test database");
        let sandbox_id = Uuid::now_v7();
        sqlx::query(
            r#"
            INSERT INTO joysafeter_sandboxes (
                id, external_id, provider, status, config, image
            ) VALUES ($1, $2, 'k8s', 'running', $3, 'test-image')
            "#,
        )
        .bind(sandbox_id)
        .bind(format!("authz-test-{sandbox_id}"))
        .bind(serde_json::json!({"runner_token": "runner-token"}))
        .execute(&pool)
        .await
        .unwrap();

        let route = runtime_route(sandbox_id);
        let valid_headers = HashMap::from([(
            "authorization".to_string(),
            "Bearer runner-token".to_string(),
        )]);
        assert!(
            validate_sandbox_identity(&pool, sandbox_id, &route, &valid_headers)
                .await
                .unwrap()
        );
        assert!(!validate_sandbox_identity(
            &pool,
            sandbox_id,
            &route,
            &HashMap::from([(
                "authorization".to_string(),
                "Bearer wrong-token".to_string(),
            )]),
        )
        .await
        .unwrap());
        assert!(
            !validate_sandbox_identity(&pool, sandbox_id, &route, &HashMap::new())
                .await
                .unwrap()
        );

        sqlx::query("UPDATE joysafeter_sandboxes SET status = 'error' WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await
            .unwrap();
        assert!(
            !validate_sandbox_identity(&pool, sandbox_id, &route, &valid_headers)
                .await
                .unwrap()
        );

        sqlx::query(
            "UPDATE joysafeter_sandboxes SET status = 'running', destroyed_at = NOW() WHERE id = $1",
        )
        .bind(sandbox_id)
        .execute(&pool)
        .await
        .unwrap();
        assert!(
            !validate_sandbox_identity(&pool, sandbox_id, &route, &valid_headers)
                .await
                .unwrap()
        );

        sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await
            .unwrap();
    }

    /// The unified egress plane injects credentials for Docker sandboxes too, so
    /// ext_authz identity validation must accept a live `provider='docker'`
    /// sandbox's runner token — not only k8s. (Regression: the lookup was
    /// hardcoded to `provider = 'k8s'`, denying every Docker sandbox with 403.)
    #[tokio::test]
    async fn durable_identity_accepts_docker_sandbox_runner_token() {
        let Some(url) = database_url() else {
            eprintln!("skipping docker ext_authz identity test: DATABASE_URL is not set");
            return;
        };
        let pool = PgPoolOptions::new()
            .max_connections(2)
            .connect(&url)
            .await
            .expect("connect to migrated PostgreSQL test database");
        let sandbox_id = Uuid::now_v7();
        sqlx::query(
            r#"
            INSERT INTO joysafeter_sandboxes (
                id, external_id, provider, status, config, image
            ) VALUES ($1, $2, 'docker', 'idle', $3, 'test-image')
            "#,
        )
        .bind(sandbox_id)
        .bind(format!("authz-docker-{sandbox_id}"))
        .bind(serde_json::json!({"runner_token": "docker-runner-token"}))
        .execute(&pool)
        .await
        .unwrap();

        let route = runtime_route(sandbox_id);
        let valid_headers = HashMap::from([(
            "authorization".to_string(),
            "Bearer docker-runner-token".to_string(),
        )]);
        assert!(
            validate_sandbox_identity(&pool, sandbox_id, &route, &valid_headers)
                .await
                .unwrap(),
            "docker sandbox runner token must be accepted by ext_authz"
        );
        assert!(!validate_sandbox_identity(
            &pool,
            sandbox_id,
            &route,
            &HashMap::from([(
                "authorization".to_string(),
                "Bearer wrong-token".to_string()
            )]),
        )
        .await
        .unwrap());

        sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await
            .unwrap();
    }
}
