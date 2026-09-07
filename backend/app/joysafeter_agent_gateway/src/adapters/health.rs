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
    let replication = state.replication.metrics_snapshot().await;
    body.push_str(
        "# HELP joysafeter_agent_gateway_replication_role Current in-memory replication role as one-hot gauges.\n\
         # TYPE joysafeter_agent_gateway_replication_role gauge\n",
    );
    for (role, active) in [
        ("leader", replication.leader),
        ("hot_standby", replication.hot_standby),
        (
            "cold_standby",
            !replication.leader && !replication.hot_standby,
        ),
    ] {
        body.push_str(&format!(
            "joysafeter_agent_gateway_replication_role{{role=\"{role}\"}} {}\n",
            u8::from(active)
        ));
    }
    for (name, help, value) in [
        (
            "joysafeter_agent_gateway_replication_revision",
            "Current leader or hot-standby replication revision.",
            replication.revision,
        ),
        (
            "joysafeter_agent_gateway_replication_connected_replicas",
            "Follower sessions currently connected to this leader replica.",
            replication.connected_replicas as u64,
        ),
        (
            "joysafeter_agent_gateway_replication_acknowledged_replicas",
            "Follower sessions with a valid acknowledgement in the current leader term.",
            replication.acknowledged_replicas as u64,
        ),
        (
            "joysafeter_agent_gateway_replication_required_acknowledgements",
            "Follower acknowledgements required before a policy mutation completes.",
            replication.required_acknowledgements as u64,
        ),
        (
            "joysafeter_agent_gateway_replication_acknowledgement_lag",
            "Leader revisions ahead of the least-current acknowledged follower.",
            replication.acknowledgement_lag,
        ),
        (
            "joysafeter_agent_gateway_replication_log_entries",
            "Mutation events retained in the leader replication log.",
            replication.log_entries as u64,
        ),
        (
            "joysafeter_agent_gateway_replication_policies",
            "Policies held in the local replication snapshot.",
            replication.policies as u64,
        ),
        (
            "joysafeter_agent_gateway_replication_placements",
            "Sandbox placements held in the local replication snapshot.",
            replication.placements as u64,
        ),
    ] {
        body.push_str(&format!(
            "# HELP {name} {help}\n# TYPE {name} gauge\n{name} {value}\n"
        ));
    }
    (
        StatusCode::OK,
        [(header::CONTENT_TYPE, "text/plain; version=0.0.4")],
        body,
    )
}
