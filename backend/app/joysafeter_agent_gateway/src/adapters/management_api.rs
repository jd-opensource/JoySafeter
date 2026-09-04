use std::sync::Arc;

use axum::extract::{Path, State};
use axum::http::{header, HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, put};
use axum::{Json, Router};
use joysafeter_agent_gateway_contract::{
    ApplySandboxPolicyRequest, AssignSandboxPlacementRequest, CompleteRecoveryRequest,
    ErrorResponse, GatewayStatusResponse, PolicyAcceptedResponse, PruneSandboxPoliciesRequest,
    PruneSandboxPoliciesResponse, ReconcilePlacementsRequest, RemoveSandboxPolicyRequest,
};
use sha2::{Digest, Sha256};
use subtle::ConstantTimeEq;
use tracing::{info, warn};

use crate::adapters::server::GatewayHttpState;
use crate::application::GatewayApplicationError;
use crate::ids::SandboxId;
use crate::xds::authority::AuthorityPhase;

const MIN_TOKEN_BYTES: usize = 32;
const MAX_TOKEN_BYTES: usize = 512;

#[derive(Clone)]
pub struct ManagementAuthenticator {
    digest: [u8; 32],
}

impl std::fmt::Debug for ManagementAuthenticator {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str("ManagementAuthenticator(<redacted>)")
    }
}

impl ManagementAuthenticator {
    pub fn new(token: &str) -> anyhow::Result<Self> {
        let token = token.trim();
        if !(MIN_TOKEN_BYTES..=MAX_TOKEN_BYTES).contains(&token.len()) {
            anyhow::bail!(
                "Agent Gateway management token must be between {MIN_TOKEN_BYTES} and {MAX_TOKEN_BYTES} bytes"
            );
        }
        if !token.is_ascii() || token.bytes().any(|byte| byte.is_ascii_whitespace()) {
            anyhow::bail!("Agent Gateway management token must be non-whitespace ASCII");
        }
        Ok(Self {
            digest: Sha256::digest(token.as_bytes()).into(),
        })
    }

    pub(crate) fn authenticate(&self, headers: &HeaderMap) -> bool {
        let Some(value) = headers
            .get(header::AUTHORIZATION)
            .and_then(|value| value.to_str().ok())
            .and_then(|value| value.strip_prefix("Bearer "))
        else {
            return false;
        };
        let candidate: [u8; 32] = Sha256::digest(value.as_bytes()).into();
        bool::from(candidate.ct_eq(&self.digest))
    }
}

pub(crate) fn routes() -> Router<Arc<GatewayHttpState>> {
    Router::new()
        .route("/internal/v1/status", get(status))
        .route("/internal/v1/recovery/complete", put(complete_recovery))
        .route(
            "/internal/v1/sandboxes/:sandbox_id/policy",
            put(apply_policy).delete(remove_policy),
        )
        .route(
            "/internal/v1/sandboxes/:sandbox_id/placement",
            put(assign_placement).delete(remove_placement),
        )
        .route("/internal/v1/placements", put(reconcile_placements))
        .route("/internal/v1/policies/prune", put(prune_policies))
}

async fn complete_recovery(
    State(state): State<Arc<GatewayHttpState>>,
    headers: HeaderMap,
    Json(request): Json<CompleteRecoveryRequest>,
) -> Response {
    if !state.management_authenticator.authenticate(&headers) {
        return unauthorized();
    }
    if request.boot_id != state.boot_id {
        return api_error(
            StatusCode::CONFLICT,
            "boot_changed",
            "Gateway restarted during recovery",
        );
    }
    match state
        .application
        .complete_recovery(request.authority_epoch, request.generations)
        .await
    {
        Ok(()) => StatusCode::NO_CONTENT.into_response(),
        Err(error) => application_error(error, None),
    }
}

async fn status(State(state): State<Arc<GatewayHttpState>>, headers: HeaderMap) -> Response {
    if !state.management_authenticator.authenticate(&headers) {
        return unauthorized();
    }
    // Snapshot the phase once so epoch and phase string stay consistent. (G2)
    let phase = state.authority.phase();
    let Some(authority_epoch) = phase.epoch() else {
        return api_error(
            StatusCode::SERVICE_UNAVAILABLE,
            "authority_unavailable",
            "xDS authority has no active epoch",
        );
    };
    (
        StatusCode::OK,
        Json(GatewayStatusResponse {
            instance_id: state.instance_id.clone(),
            boot_id: state.boot_id.clone(),
            authority_epoch,
            authority_phase: match phase {
                AuthorityPhase::Standby => "standby",
                AuthorityPhase::Staging { .. } => "staging",
                AuthorityPhase::RecoveryServing { .. } => "recovery_serving",
                AuthorityPhase::Ready { .. } => "ready",
                AuthorityPhase::Revoked { .. } => "revoked",
            }
            .to_string(),
            generations: state.application.projections().inventory(),
        }),
    )
        .into_response()
}

async fn apply_policy(
    State(state): State<Arc<GatewayHttpState>>,
    Path(sandbox_id): Path<String>,
    headers: HeaderMap,
    Json(request): Json<ApplySandboxPolicyRequest>,
) -> Response {
    if !state.management_authenticator.authenticate(&headers) {
        return unauthorized();
    }
    let sandbox_id = match parse_sandbox_id(&sandbox_id) {
        Ok(id) => id,
        Err(()) => return invalid_sandbox_id(),
    };
    match state.application.apply_policy(sandbox_id, request).await {
        Ok(generation) => {
            info!(%sandbox_id, policy_version = generation.policy_version, "sandbox policy accepted");
            (
                StatusCode::OK,
                Json(PolicyAcceptedResponse {
                    sandbox_id: sandbox_id.to_string(),
                    generation,
                    status: "ready".to_string(),
                }),
            )
                .into_response()
        }
        Err(error) => application_error(error, Some(sandbox_id)),
    }
}

async fn remove_policy(
    State(state): State<Arc<GatewayHttpState>>,
    Path(sandbox_id): Path<String>,
    headers: HeaderMap,
    Json(request): Json<RemoveSandboxPolicyRequest>,
) -> Response {
    if !state.management_authenticator.authenticate(&headers) {
        return unauthorized();
    }
    let sandbox_id = match parse_sandbox_id(&sandbox_id) {
        Ok(id) => id,
        Err(()) => return invalid_sandbox_id(),
    };
    match state
        .application
        .remove_policy(sandbox_id, request.generation)
        .await
    {
        Ok(()) => StatusCode::NO_CONTENT.into_response(),
        Err(error) => application_error(error, Some(sandbox_id)),
    }
}

async fn assign_placement(
    State(state): State<Arc<GatewayHttpState>>,
    Path(sandbox_id): Path<String>,
    headers: HeaderMap,
    Json(request): Json<AssignSandboxPlacementRequest>,
) -> Response {
    if !state.management_authenticator.authenticate(&headers) {
        return unauthorized();
    }
    let sandbox_id = match parse_sandbox_id(&sandbox_id) {
        Ok(id) => id,
        Err(()) => return invalid_sandbox_id(),
    };
    match state
        .application
        .assign_placement(sandbox_id, request.node_id)
        .await
    {
        Ok(()) => StatusCode::NO_CONTENT.into_response(),
        Err(error) => application_error(error, Some(sandbox_id)),
    }
}

async fn remove_placement(
    State(state): State<Arc<GatewayHttpState>>,
    Path(sandbox_id): Path<String>,
    headers: HeaderMap,
) -> Response {
    if !state.management_authenticator.authenticate(&headers) {
        return unauthorized();
    }
    let sandbox_id = match parse_sandbox_id(&sandbox_id) {
        Ok(id) => id,
        Err(()) => return invalid_sandbox_id(),
    };
    match state.application.remove_placement(sandbox_id).await {
        Ok(()) => StatusCode::NO_CONTENT.into_response(),
        Err(error) => application_error(error, Some(sandbox_id)),
    }
}

async fn reconcile_placements(
    State(state): State<Arc<GatewayHttpState>>,
    headers: HeaderMap,
    Json(request): Json<ReconcilePlacementsRequest>,
) -> Response {
    if !state.management_authenticator.authenticate(&headers) {
        return unauthorized();
    }
    match state
        .application
        .reconcile_placements(request.assignments)
        .await
    {
        Ok(()) => StatusCode::NO_CONTENT.into_response(),
        Err(error) => application_error(error, None),
    }
}

async fn prune_policies(
    State(state): State<Arc<GatewayHttpState>>,
    headers: HeaderMap,
    Json(request): Json<PruneSandboxPoliciesRequest>,
) -> Response {
    if !state.management_authenticator.authenticate(&headers) {
        return unauthorized();
    }
    match state
        .application
        .prune_policies(request.live_sandbox_ids)
        .await
    {
        Ok(removed) => (
            StatusCode::OK,
            Json(PruneSandboxPoliciesResponse {
                removed_sandbox_ids: removed
                    .into_iter()
                    .map(|sandbox_id| sandbox_id.to_string())
                    .collect(),
            }),
        )
            .into_response(),
        Err(error) => application_error(error, None),
    }
}

fn application_error(error: GatewayApplicationError, sandbox_id: Option<SandboxId>) -> Response {
    if let Some(sandbox_id) = sandbox_id {
        warn!(%sandbox_id, %error, "Agent Gateway operation failed");
    } else {
        warn!(%error, "Agent Gateway operation failed");
    }
    match error {
        GatewayApplicationError::InvalidPolicy(message) => {
            api_error(StatusCode::BAD_REQUEST, "invalid_policy", message)
        }
        GatewayApplicationError::InvalidPlacement(message) => {
            api_error(StatusCode::BAD_REQUEST, "invalid_placement", message)
        }
        GatewayApplicationError::InvalidInventory(message) => {
            api_error(StatusCode::BAD_REQUEST, "invalid_inventory", message)
        }
        GatewayApplicationError::AuthorityUnavailable => api_error(
            StatusCode::SERVICE_UNAVAILABLE,
            "authority_unavailable",
            "xDS authority is not ready",
        ),
        GatewayApplicationError::NodeNotReady => api_error(
            StatusCode::SERVICE_UNAVAILABLE,
            "node_not_ready",
            "sandbox has no Envoy node assignment yet; retry after placement",
        ),
        GatewayApplicationError::DeliveryNack(_) => api_error(
            StatusCode::UNPROCESSABLE_ENTITY,
            "policy_nacked",
            "Envoy rejected the policy change",
        ),
        GatewayApplicationError::DeliveryTimeout(_) => api_error(
            StatusCode::GATEWAY_TIMEOUT,
            "delivery_timeout",
            "timed out waiting for Envoy to acknowledge the policy change",
        ),
        GatewayApplicationError::Delivery(_) => api_error(
            StatusCode::BAD_GATEWAY,
            "delivery_failed",
            "failed while waiting for Envoy to acknowledge the policy change",
        ),
        GatewayApplicationError::Infrastructure(_) => api_error(
            StatusCode::BAD_GATEWAY,
            "gateway_operation_failed",
            "Gateway resource operation failed",
        ),
        GatewayApplicationError::InvalidGeneration => api_error(
            StatusCode::CONFLICT,
            "invalid_generation",
            "policy generation is stale or conflicts with the in-memory projection",
        ),
        GatewayApplicationError::RecoveryMismatch => api_error(
            StatusCode::CONFLICT,
            "recovery_mismatch",
            "replayed inventory does not match the Gateway projection",
        ),
        GatewayApplicationError::Replication(_) => api_error(
            StatusCode::SERVICE_UNAVAILABLE,
            "replication_unavailable",
            "hot-standby replication quorum was not reached",
        ),
        GatewayApplicationError::AuthorityChanged => api_error(
            StatusCode::SERVICE_UNAVAILABLE,
            "authority_changed",
            "xDS authority changed during the operation",
        ),
    }
}

fn unauthorized() -> Response {
    api_error(
        StatusCode::UNAUTHORIZED,
        "unauthorized",
        "authentication failed",
    )
}

fn parse_sandbox_id(value: &str) -> Result<SandboxId, ()> {
    value.parse().map_err(|_| ())
}

fn invalid_sandbox_id() -> Response {
    api_error(
        StatusCode::BAD_REQUEST,
        "invalid_sandbox_id",
        "sandbox_id must be a UUID",
    )
}

fn api_error(status: StatusCode, code: &'static str, message: impl Into<String>) -> Response {
    (
        status,
        Json(ErrorResponse {
            code: code.to_string(),
            message: message.into(),
        }),
    )
        .into_response()
}

#[cfg(test)]
#[path = "../../tests/unit/adapters/management_api_test.rs"]
mod tests;
