use std::sync::Arc;

use axum::extract::State;
use axum::http::{header, StatusCode};
use axum::response::IntoResponse;
use axum::routing::get;
use axum::Router;

use crate::adapters::server::GatewayHttpState;

pub(crate) fn routes() -> Router<Arc<GatewayHttpState>> {
    Router::new()
        .route("/health/live", get(live))
        .route("/health/ready", get(ready))
        .route("/metrics", get(metrics))
}

async fn live() -> impl IntoResponse {
    (StatusCode::OK, "live")
}

async fn ready(State(state): State<Arc<GatewayHttpState>>) -> impl IntoResponse {
    if state.authority.phase().serves_ads() || state.replication.hot_metadata().await.is_some() {
        (StatusCode::OK, "ready")
    } else {
        (StatusCode::SERVICE_UNAVAILABLE, "replica_not_synchronized")
    }
}

async fn metrics(State(state): State<Arc<GatewayHttpState>>) -> impl IntoResponse {
    let mut body = state
        .control_plane
        .metrics_snapshot()
        .await
        .render_prometheus();
    let projected = state.application.projections().inventory().len();
    body.push_str(&format!(
        "# TYPE joysafeter_agent_gateway_projected_sandboxes gauge\n\
         joysafeter_agent_gateway_projected_sandboxes {projected}\n"
    ));
    (
        StatusCode::OK,
        [(header::CONTENT_TYPE, "text/plain; version=0.0.4")],
        body,
    )
}
