use std::sync::Arc;
use std::time::Duration;

use axum::extract::{Query, State};
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use joysafeter_agent_gateway_contract::ErrorResponse;

use crate::adapters::server::GatewayHttpState;
use crate::replication::model::{AckReplicaRequest, AckReplicaResponse, WatchReplicaQuery};
use crate::replication::ReplicationError;

const WATCH_WAIT: Duration = Duration::from_secs(20);

pub(crate) fn routes() -> Router<Arc<GatewayHttpState>> {
    Router::new()
        .route("/internal/v1/replication/watch", get(watch))
        .route("/internal/v1/replication/ack", post(ack))
}

async fn watch(
    State(state): State<Arc<GatewayHttpState>>,
    headers: HeaderMap,
    Query(query): Query<WatchReplicaQuery>,
) -> Response {
    if !state
        .replication_authenticator
        .as_ref()
        .is_some_and(|authenticator| authenticator.authenticate(&headers))
    {
        return unauthorized();
    }
    match state.replication.watch(query, WATCH_WAIT).await {
        Ok(response) => (StatusCode::OK, Json(response)).into_response(),
        Err(error) => replication_error(error),
    }
}

async fn ack(
    State(state): State<Arc<GatewayHttpState>>,
    headers: HeaderMap,
    Json(request): Json<AckReplicaRequest>,
) -> Response {
    if !state
        .replication_authenticator
        .as_ref()
        .is_some_and(|authenticator| authenticator.authenticate(&headers))
    {
        return unauthorized();
    }
    match state.replication.acknowledge(request).await {
        Ok(()) => (StatusCode::OK, Json(AckReplicaResponse { accepted: true })).into_response(),
        Err(error) => replication_error(error),
    }
}

fn replication_error(error: ReplicationError) -> Response {
    let (status, code) = match error {
        ReplicationError::NotLeader => (StatusCode::SERVICE_UNAVAILABLE, "not_leader"),
        ReplicationError::InvalidAck => (StatusCode::CONFLICT, "invalid_ack"),
        ReplicationError::InvalidSnapshot(_) => (StatusCode::BAD_REQUEST, "invalid_replica_state"),
        ReplicationError::AckTimeout { .. } => {
            (StatusCode::SERVICE_UNAVAILABLE, "replica_ack_timeout")
        }
    };
    (
        status,
        Json(ErrorResponse {
            code: code.to_string(),
            message: error.to_string(),
        }),
    )
        .into_response()
}

fn unauthorized() -> Response {
    (
        StatusCode::UNAUTHORIZED,
        Json(ErrorResponse {
            code: "unauthorized".to_string(),
            message: "authentication failed".to_string(),
        }),
    )
        .into_response()
}

#[cfg(test)]
#[path = "../../tests/unit/adapters/replication_api_test.rs"]
mod tests;
