use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use anyhow::Context;
use axum::Router;
use tokio::net::TcpListener;
use tokio::sync::Mutex;
use tokio::task::JoinHandle;
use tower_http::trace::TraceLayer;
use tracing::info;

use crate::application::policy_publisher::PolicyPublisher;
use crate::application::{
    ApplicationReplication, GatewayApplication, GatewayRuntimeConfig, PolicyProjectionRegistry,
};
use crate::bootstrap::shutdown::ShutdownSignal;
use crate::replication::ReplicationCoordinator;
use crate::xds::authority::XdsAuthority;
use crate::xds::control_plane::XdsControlPlane;

pub(crate) struct GatewayHttpState {
    pub authority: XdsAuthority,
    pub control_plane: XdsControlPlane,
    pub application: GatewayApplication,
    pub replication: ReplicationCoordinator,
}

pub struct HttpServerDependencies {
    pub addr: SocketAddr,
    pub authority: XdsAuthority,
    pub control_plane: XdsControlPlane,
    pub publisher: PolicyPublisher,
    pub projections: PolicyProjectionRegistry,
    pub delivery_timeout: Duration,
    pub mutation_gate: Arc<Mutex<()>>,
    pub replication: ReplicationCoordinator,
    pub replication_enabled: bool,
    pub shutdown: ShutdownSignal,
}

pub async fn start_http_server(
    dependencies: HttpServerDependencies,
) -> anyhow::Result<(JoinHandle<anyhow::Result<()>>, GatewayApplication)> {
    let HttpServerDependencies {
        addr,
        authority,
        control_plane,
        publisher,
        projections,
        delivery_timeout,
        mutation_gate,
        replication,
        replication_enabled,
        shutdown,
    } = dependencies;
    let listener = TcpListener::bind(addr).await?;
    let runtime = GatewayRuntimeConfig {
        delivery_timeout,
        node_assignment_timeout: crate::application::DEFAULT_NODE_ASSIGNMENT_TIMEOUT,
    };
    let application = if replication_enabled {
        GatewayApplication::new_replicated(
            authority.clone(),
            publisher,
            control_plane.clone(),
            projections,
            runtime,
            ApplicationReplication {
                coordinator: replication.clone(),
                mutation_gate,
            },
        )
    } else {
        GatewayApplication::new(
            authority.clone(),
            publisher,
            control_plane.clone(),
            projections,
            runtime,
        )
    };
    // The gRPC management server shares this application instance and therefore
    // the same mutation coordinator and per-sandbox lanes.
    let application_for_stream = application.clone();
    let state = Arc::new(GatewayHttpState {
        authority,
        application,
        control_plane,
        replication,
    });
    let router = Router::new()
        .merge(crate::adapters::health::routes())
        .layer(TraceLayer::new_for_http())
        .with_state(state);

    let handle = tokio::spawn(async move {
        info!(%addr, "Agent Gateway HTTP server listening");
        axum::serve(listener, router)
            .with_graceful_shutdown(shutdown.wait())
            .await
            .with_context(|| format!("Agent Gateway HTTP server failed on {addr}"))
    });
    Ok((handle, application_for_stream))
}
