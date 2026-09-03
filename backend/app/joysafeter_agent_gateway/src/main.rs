use std::sync::Arc;

use anyhow::Context;
use joysafeter_agent_gateway::adapters::management_api::ManagementAuthenticator;
use joysafeter_agent_gateway::adapters::policy_stream_subscriber::PolicyStreamSubscriber;
use joysafeter_agent_gateway::adapters::server::{start_http_server, HttpServerDependencies};
use joysafeter_agent_gateway::application::policy_publisher::PolicyPublisher;
use joysafeter_agent_gateway::application::PolicyProjectionRegistry;
use joysafeter_agent_gateway::bootstrap::leader::{self, LeaderConfig, LeaderReplication};
use joysafeter_agent_gateway::bootstrap::shutdown::ShutdownCoordinator;
use joysafeter_agent_gateway::config::GatewayConfig;
use joysafeter_agent_gateway::replication::{self, ReplicaProjector, ReplicationCoordinator};
use joysafeter_agent_gateway::xds::auth::SharedTokenAuthenticator;
use joysafeter_agent_gateway::xds::authority::XdsAuthority;
use joysafeter_agent_gateway::xds::control_plane::XdsControlPlane;
use joysafeter_agent_gateway::xds::transport::start_xds_server;
use tokio::sync::Mutex;
use tracing::{info, warn};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .with_target(true)
        .init();

    let config = GatewayConfig::from_env()?;
    let authority = XdsAuthority::standalone();
    let shutdown = ShutdownCoordinator::new();
    let control_plane = XdsControlPlane::new(authority.clone(), config.node_visibility);
    let projections = PolicyProjectionRegistry::default();
    let boot_id = uuid::Uuid::now_v7();
    let publisher = PolicyPublisher::new(control_plane.clone());
    let mutation_gate = Arc::new(Mutex::new(()));
    let replication = ReplicationCoordinator::new(
        config.instance_id.clone(),
        if config.leader_election_enabled {
            config.hot_standby_min_acks
        } else {
            0
        },
        config.replication_ack_timeout,
    );
    let replica_projector = ReplicaProjector::new(
        control_plane.clone(),
        publisher.clone(),
        projections.clone(),
        mutation_gate.clone(),
    );
    if !config.leader_election_enabled {
        let recovery = authority.begin_staging()?;
        control_plane
            .install_recovery_inventory(
                &recovery,
                joysafeter_agent_gateway::xds::inventory::RecoveryInventory::new(Vec::new())?,
            )
            .await?;
        authority.begin_recovery_serving(&recovery)?;
        authority.mark_ready(&recovery)?;
    }

    let mut xds_handle = start_xds_server(
        config.xds_addr,
        control_plane.clone(),
        Arc::new(SharedTokenAuthenticator::new(
            config.xds_auth_keyring.clone(),
        )),
        shutdown.signal(),
    )
    .await?;
    let (mut http_handle, application) = start_http_server(HttpServerDependencies {
        addr: config.http_addr,
        instance_id: config.instance_id.clone(),
        boot_id: boot_id.to_string(),
        authority: authority.clone(),
        control_plane: control_plane.clone(),
        management_authenticator: config.management_authenticator.clone(),
        publisher: publisher.clone(),
        projections: projections.clone(),
        delivery_timeout: config.delivery_timeout,
        mutation_gate,
        replication: replication.clone(),
        replication_authenticator: config
            .replication_token
            .as_ref()
            .map(|token| ManagementAuthenticator::new(token.expose()))
            .transpose()?,
        replication_enabled: config.leader_election_enabled,
        shutdown: shutdown.signal(),
    })
    .await?;

    // Management gRPC server: replaces the HTTP management API for policy
    // apply/remove. Orchestrator calls this for type-safe, high-performance ops.
    let mut management_grpc_handle = joysafeter_agent_gateway::adapters::management_grpc::start_management_grpc_server(
        config.management_grpc_addr,
        application.clone(),
        config.management_token.expose(),
        shutdown.signal(),
    )
    .await?;
    info!(addr = %config.management_grpc_addr, "Agent Gateway management gRPC server started");

    // Policy stream subscriber: when configured, subscribe to the orchestrator's
    // policy stream and apply events through the shared GatewayApplication (same
    // per-sandbox lanes as the HTTP path).
    if let Some(endpoint) = config.policy_stream_endpoint.clone() {
        let subscriber = Arc::new(PolicyStreamSubscriber::new(
            endpoint,
            config.instance_id.clone(),
            Arc::new(application),
        ));
        tokio::spawn(async move {
            if let Err(error) = subscriber.run().await {
                warn!(%error, "Agent Gateway policy stream subscriber exited");
            }
        });
        info!("Agent Gateway policy stream subscriber started");
    }
    let follower_handle = if config.leader_election_enabled {
        Some(replication::follower::spawn(
            config
                .replication_url
                .clone()
                .expect("validated replication URL"),
            config
                .replication_token
                .as_ref()
                .expect("validated replication token")
                .expose()
                .to_string(),
            config.instance_id.clone(),
            replication.clone(),
            replica_projector.clone(),
            shutdown.signal(),
        )?)
    } else {
        None
    };
    let leader_handle = if config.leader_election_enabled {
        let client = kube::Client::try_default()
            .await
            .context("initialize Kubernetes client for Agent Gateway leader election")?;
        Some(leader::spawn(
            client,
            LeaderConfig {
                namespace: config.k8s_namespace.clone(),
                pod_name: config
                    .pod_name
                    .clone()
                    .expect("validated leader-election pod name"),
                lease_name: config.leader_lease_name.clone(),
                identity: config.leader_identity.clone(),
                lease_duration: config.leader_lease_duration,
                renew_interval: config.leader_renew_interval,
            },
            authority.clone(),
            control_plane.clone(),
            projections,
            LeaderReplication {
                coordinator: replication.clone(),
                projector: replica_projector,
            },
        ))
    } else {
        None
    };

    info!(
        instance_id = %config.instance_id,
        xds_addr = %config.xds_addr,
        http_addr = %config.http_addr,
        boot_id = %boot_id,
        "JoySafeter Agent Gateway started"
    );

    let run_result: anyhow::Result<()> = tokio::select! {
        signal = shutdown_signal() => signal,
        result = &mut xds_handle => server_exit("xDS", result),
        result = &mut http_handle => server_exit("HTTP", result),
        result = &mut management_grpc_handle => server_exit("management gRPC", result),
    };

    if let Some(leader) = &leader_handle {
        leader.shutdown().await;
    } else if let Err(error) = authority.revoke() {
        warn!(%error, "failed to revoke xDS authority during shutdown");
    }
    if let Some(follower) = &follower_handle {
        follower.abort();
    }
    shutdown.begin();
    if run_result.is_ok() {
        info!(
            timeout_seconds = config.shutdown_grace.as_secs(),
            "Agent Gateway marked not-ready; draining network requests"
        );
        match tokio::time::timeout(config.shutdown_grace, async {
            let (xds_result, http_result, grpc_result) =
                tokio::join!(&mut xds_handle, &mut http_handle, &mut management_grpc_handle);
            server_shutdown("xDS", xds_result)?;
            server_shutdown("HTTP", http_result)?;
            server_shutdown("management gRPC", grpc_result)
        })
        .await
        {
            Ok(Ok(())) => info!("Agent Gateway network requests drained"),
            Ok(Err(error)) => warn!(%error, "Agent Gateway server failed while draining"),
            Err(_) => warn!("Agent Gateway drain timed out; terminating remaining requests"),
        }
    }
    xds_handle.abort();
    http_handle.abort();
    management_grpc_handle.abort();
    info!("JoySafeter Agent Gateway stopped");
    run_result
}

fn server_shutdown(
    name: &str,
    result: Result<anyhow::Result<()>, tokio::task::JoinError>,
) -> anyhow::Result<()> {
    match result {
        Ok(Ok(())) => Ok(()),
        Ok(Err(error)) => Err(error).with_context(|| format!("Agent Gateway {name} drain failed")),
        Err(error) => Err(error).with_context(|| format!("Agent Gateway {name} task failed")),
    }
}

fn server_exit(
    name: &str,
    result: Result<anyhow::Result<()>, tokio::task::JoinError>,
) -> anyhow::Result<()> {
    match result {
        Ok(Ok(())) => anyhow::bail!("Agent Gateway {name} server stopped unexpectedly"),
        Ok(Err(error)) => Err(error).with_context(|| format!("Agent Gateway {name} server failed")),
        Err(error) => Err(error).with_context(|| format!("Agent Gateway {name} task failed")),
    }
}

#[cfg(unix)]
async fn shutdown_signal() -> anyhow::Result<()> {
    use tokio::signal::unix::{signal, SignalKind};

    let mut terminate = signal(SignalKind::terminate()).context("install SIGTERM handler")?;
    tokio::select! {
        result = tokio::signal::ctrl_c() => result.context("listen for Ctrl-C"),
        signal = terminate.recv() => signal
            .map(|_| ())
            .ok_or_else(|| anyhow::anyhow!("SIGTERM signal stream closed unexpectedly")),
    }
}

#[cfg(not(unix))]
async fn shutdown_signal() -> anyhow::Result<()> {
    tokio::signal::ctrl_c().await.context("listen for Ctrl-C")
}
