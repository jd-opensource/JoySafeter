//! JoySafeter Orchestrator — Rust implementation.
//!
//! Provides the joysafeter kernel: gRPC server for sandbox-runner connections,
//! task scheduling, sandbox lifecycle management, and event persistence.

mod config;
mod db;
#[allow(dead_code)]
mod egress;
mod events;
mod grpc;
mod kernel;
mod runtime_config;
mod sandbox;
mod xds;
mod xds_observer;
mod xds_reconciler;
mod xds_server;

use std::sync::Arc;

use config::JoySafeterConfig;
use tokio_util::sync::CancellationToken;
use tracing::{error, info, warn};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Load .env if present
    let _ = dotenvy::dotenv();

    // rustls 0.23 refuses to auto-pick a CryptoProvider when both `ring` and
    // `aws-lc-rs` are present in the dependency tree (they are, transitively).
    // The mTLS ext_authz server builds a rustls ServerConfig via tonic, which
    // panics without a process-default provider. Install one explicitly before
    // any TLS is constructed. Idempotent: a later install by a dep is harmless.
    let _ = rustls::crypto::aws_lc_rs::default_provider().install_default();

    // Initialize tracing
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .with_target(true)
        .init();

    let config = JoySafeterConfig::from_env();

    kernel::active_standby::set_active_pod_label(&config.instance_id, false).await?;

    info!(
        instance_id = %config.instance_id,
        grpc_addr = %config.grpc_addr(),
        max_concurrent_tasks = config.max_concurrent_tasks,
        sandbox_provider = %config.sandbox_provider,
        "Starting JoySafeter Orchestrator (Rust)"
    );

    let control_plane_health = kernel::active_standby::ControlPlaneHealth::default();
    let health_handle = kernel::active_standby::start_health_server(
        &config.control_plane_health_bind,
        control_plane_health.clone(),
    )
    .await?;
    let shutdown = CancellationToken::new();
    let signal_shutdown = shutdown.clone();
    let signal_handle = tokio::spawn(async move {
        shutdown_signal().await;
        signal_shutdown.cancel();
    });
    let Some(leadership) =
        kernel::active_standby::wait_for_active(&config, shutdown.clone()).await?
    else {
        info!("Shutdown signal received while waiting for active leadership");
        health_handle.abort();
        return Ok(());
    };

    // Initialize database pool
    let db_pool = db::pool::create_pool(&config.database_url).await?;
    info!("Database pool initialized");

    // Initialize Redis (optional)
    let redis_client = match &config.redis_url {
        Some(url) => match redis::Client::open(url.as_str()) {
            Ok(client) => {
                info!("Redis client initialized");
                Some(client)
            }
            Err(e) => {
                error!("Failed to connect to Redis: {e}");
                None
            }
        },
        None => {
            info!("Redis not configured, HA coordination disabled");
            None
        }
    };

    // Initialize Redis coordinator (HA)
    let redis_coordinator = if let Some(ref client) = redis_client {
        let coord = kernel::redis_coordinator::RedisCoordinator::new(
            client.clone(),
            &config.instance_id,
            config.heartbeat_interval,
            config.heartbeat_ttl,
        );
        if let Err(e) = coord.register_instance().await {
            warn!("Failed to register instance in Redis: {e}");
        } else {
            coord.spawn_heartbeat();
            info!(
                "RedisCoordinator registered (instance={})",
                config.instance_id
            );
        }
        Some(Arc::new(coord))
    } else {
        None
    };

    // Initialize runtime config (hot-reloadable)
    let runtime_config = Arc::new(runtime_config::RuntimeConfig::from_config(&config));

    // Initialize event bus
    let event_bus = events::bus::EventBus::new(
        db_pool.clone(),
        &config,
        runtime_config.clone(),
        redis_client
            .clone()
            .expect("Redis is required for event bus"),
    );
    // Start periodic flush timer so buffered events don't sit in memory
    // indefinitely when event rate is below the batch threshold.
    let _flush_timer = event_bus.persister().spawn_flush_timer();
    info!("Event bus initialized (flush timer started)");

    // Initialize session broadcaster
    let session_broadcaster = kernel::session_broadcaster::SessionBroadcaster::new(
        redis_client
            .clone()
            .expect("Redis is required for session broadcaster"),
        &config.instance_id,
    );
    info!("Session broadcaster initialized");

    // Initialize sandbox provider (select based on config)
    let mut docker_envoy_manager: Option<Arc<sandbox::envoy::EnvoyManager>> = None;
    let (sandbox_provider, mut xds_service): (
        Arc<dyn sandbox::provider::SandboxProvider>,
        Option<Arc<sandbox::lds_backend::DeltaXdsServer>>,
    ) = match config.sandbox_provider.as_str() {
        "daytona" => {
            if config.daytona_api_url.is_empty() || config.daytona_api_key.is_empty() {
                return Err(anyhow::anyhow!(
                    "JOYSAFETER_DAYTONA_API_URL and JOYSAFETER_DAYTONA_API_KEY required"
                ));
            }
            (
                Arc::new(sandbox::daytona::DaytonaProvider::new(
                    &config.daytona_api_url,
                    &config.daytona_api_key,
                    config.daytona_target.as_deref().unwrap_or("us"),
                    &config.daytona_snapshot,
                )),
                None,
            )
        }
        "e2b" => {
            if config.e2b_api_key.is_empty() || config.e2b_template_id.is_empty() {
                return Err(anyhow::anyhow!(
                    "JOYSAFETER_E2B_API_KEY and JOYSAFETER_E2B_TEMPLATE_ID required"
                ));
            }
            (
                Arc::new(sandbox::e2b::E2bProvider::new(
                    config
                        .e2b_api_url
                        .as_deref()
                        .unwrap_or("https://api.e2b.app"),
                    &config.e2b_api_key,
                    &config.e2b_template_id,
                )),
                None,
            )
        }
        "docker" | "" => {
            let docker_provider = sandbox::docker::DockerProvider::new(&config).await?;
            let xds = docker_provider.xds_service();
            docker_envoy_manager = docker_provider.envoy_manager().cloned();
            (
                Arc::new(docker_provider) as Arc<dyn sandbox::provider::SandboxProvider>,
                xds,
            )
        }
        "k8s" | "kubernetes" => (Arc::new(sandbox::k8s::K8sProvider::new(&config)), None),
        other => {
            return Err(anyhow::anyhow!(
                    "Unsupported JOYSAFETER_SANDBOX_PROVIDER={other}. Expected docker, k8s, daytona, or e2b."
                ));
        }
    };
    info!(
        provider = %config.sandbox_provider,
        "Sandbox provider initialized"
    );
    if xds_service.is_none()
        && config.egress_xds_bind.is_some()
        && matches!(config.sandbox_provider.as_str(), "k8s" | "kubernetes")
    {
        xds_service = Some(sandbox::lds_backend::DeltaXdsServer::new_node_local());
        info!("Initialized node-local Rust ADS state for Kubernetes shadow serving");
    }
    if let Some(xds) = xds_service.as_ref() {
        control_plane_health.attach_xds_status(xds.runtime_status());
    }

    // Build the orchestrator-owned egress enforcer. It is the authority for
    // whether credentialed egress can be mediated; a `None` enforcer means the
    // resolver fails closed for secret-backed / limited-networking sandboxes.
    let egress_enforcer = egress::enforcer::build_enforcer_with_pool(
        &config,
        Some(db_pool.clone()),
        &config.sandbox_provider,
        docker_envoy_manager,
    )?;

    // Provider startup: ImageBuilder, provider-specific health, etc.
    if let Err(e) = sandbox_provider.on_startup(&db_pool).await {
        warn!("Provider on_startup failed: {e}");
    }

    // Egress data-plane startup: init (Docker: Envoy container) + recover
    // per-sandbox egress state from the DB for still-live sandboxes.
    if let Some(enforcer) = &egress_enforcer {
        if let Err(e) = enforcer.init().await {
            warn!("Egress enforcer init failed: {e}");
        }
        if let Err(e) = enforcer.recover(&db_pool).await {
            warn!("Egress enforcer recovery from DB failed: {e}");
        }
    }

    // Initialize sandbox bridge registry
    let bridge_registry = kernel::sandbox_bridge::BridgeRegistry::new();

    // Initialize task queue (Redis-backed scheduler wakeups)
    let queue = kernel::queue::TaskQueue::new(
        redis_client
            .clone()
            .expect("Redis is required for task queue"),
    );

    // Initialize memory store subscribers
    let memory_subscribers = Arc::new(kernel::memory_sync::MemoryStoreSubscribers::new());
    info!("MemoryStoreSubscribers initialized");

    // Task controller — startup recovery
    let task_controller = kernel::task_controller::TaskController::new(
        db_pool.clone(),
        queue.clone(),
        config.clone(),
        bridge_registry.clone(),
    );
    task_controller.recover_on_startup().await?;
    info!("Startup recovery complete");

    // Orphaned sandbox cleanup
    let sandbox_controller_for_cleanup =
        Arc::new(kernel::sandbox_controller::SandboxController::new(
            db_pool.clone(),
            queue.clone(),
            bridge_registry.clone(),
            sandbox_provider.clone(),
            egress_enforcer.clone(),
            redis_coordinator.clone(),
            config.clone(),
            runtime_config.clone(),
        ));
    match sandbox_controller_for_cleanup.cleanup_orphaned().await {
        Ok(n) if n > 0 => info!("Cleaned up {n} orphaned sandboxes"),
        Ok(_) => {}
        Err(e) => warn!("Orphan cleanup failed: {e}"),
    }

    let xds_shadow_shutdown = shutdown.child_token();
    let shadow_xds = if config.egress_xds_shadow_reconcile {
        anyhow::ensure!(
            matches!(config.sandbox_provider.as_str(), "k8s" | "kubernetes"),
            "JOYSAFETER_EGRESS_XDS_SHADOW_RECONCILE requires the Kubernetes sandbox provider"
        );
        Some(xds_service.clone().ok_or_else(|| {
            anyhow::anyhow!("JOYSAFETER_EGRESS_XDS_SHADOW_RECONCILE requires embedded Rust ADS")
        })?)
    } else {
        None
    };
    let xds_observer_handle = if let Some(xds) = shadow_xds.as_ref() {
        let observations = xds.take_observations()?;
        Some(xds_observer::spawn_shadow_observer(
            db_pool.clone(),
            config.instance_id.clone(),
            observations,
            xds_shadow_shutdown.clone(),
        ))
    } else {
        None
    };

    let xds_handle = if let Some(bind) = config.egress_xds_bind.as_deref() {
        let addr = bind.parse().map_err(|error| {
            anyhow::anyhow!("invalid JOYSAFETER_EGRESS_XDS_BIND {bind}: {error}")
        })?;
        let xds = xds_service.clone().ok_or_else(|| {
            anyhow::anyhow!(
                "JOYSAFETER_EGRESS_XDS_BIND requires an xDS-capable docker or k8s provider"
            )
        })?;
        Some(
            xds_server::start_xds_server(
                addr,
                xds,
                xds_server::XdsTlsConfig {
                    enabled: config.egress_xds_mtls,
                    cert_file: config.egress_xds_cert_file.clone(),
                    key_file: config.egress_xds_key_file.clone(),
                    client_ca_file: config.egress_xds_client_ca_file.clone(),
                    client_dns_san: config.egress_xds_client_dns_san.clone(),
                },
            )
            .await?,
        )
    } else {
        None
    };
    let xds_reconciler_handle = if let Some(xds) = shadow_xds {
        let compiler_config =
            xds::compiler::CompilerConfig::from_env(config.envoy_egress_denied_cidrs.clone())?;
        let interval =
            std::time::Duration::from_millis(config.egress_xds_reconcile_interval_ms.max(100));
        let ack_timeout =
            std::time::Duration::from_millis(config.egress_xds_ack_timeout_ms.max(100));
        let node_lease_ttl =
            std::time::Duration::from_millis(config.egress_xds_node_lease_ttl_ms.max(10_000));
        info!(
            interval_ms = interval.as_millis(),
            ack_timeout_ms = ack_timeout.as_millis(),
            node_lease_ttl_ms = node_lease_ttl.as_millis(),
            "Starting PostgreSQL-backed Rust xDS shadow reconciler"
        );
        Some(xds_reconciler::spawn_shadow_reconciler(
            db_pool.clone(),
            xds,
            compiler_config,
            interval,
            ack_timeout,
            config.instance_id.clone(),
            node_lease_ttl,
            xds_shadow_shutdown.clone(),
        ))
    } else {
        None
    };
    let runner_xds_service = if xds_handle.is_some() {
        None
    } else {
        xds_service
    };

    // Start runner gRPC server. Production xDS uses the dedicated mTLS listener;
    // registration here remains only for legacy local Docker compatibility.
    let grpc_handle = grpc::server::start_grpc_server(
        config.grpc_addr(),
        bridge_registry.clone(),
        event_bus.clone(),
        queue.clone(),
        db_pool.clone(),
        config.clone(),
        sandbox_provider.clone(),
        redis_coordinator.clone(),
        memory_subscribers.clone(),
        runtime_config.clone(),
        runner_xds_service,
    )
    .await?;
    info!(addr = %config.grpc_addr(), "gRPC server started");

    let ext_authz_handle = if let Some(bind) = config.egress_authz_bind.as_deref() {
        let addr = bind.parse().map_err(|error| {
            anyhow::anyhow!("invalid JOYSAFETER_EGRESS_AUTHZ_BIND {bind}: {error}")
        })?;
        Some(
            kernel::ext_authz::start_ext_authz_server(
                addr,
                db_pool.clone(),
                kernel::ext_authz::ExtAuthzTlsConfig {
                    enabled: config.egress_authz_mtls,
                    cert_file: config.egress_authz_cert_file.clone(),
                    key_file: config.egress_authz_key_file.clone(),
                    client_ca_file: config.egress_authz_client_ca_file.clone(),
                    client_dns_san: config.egress_authz_client_dns_san.clone(),
                },
            )
            .await?,
        )
    } else {
        None
    };

    // Start the credential resolution HTTP endpoint (`/resolve`). Data planes
    // call it per request to obtain injectable credential headers; the broker is
    // the single decrypt point, and the route registry is populated as sandboxes
    // enforce their egress policy.
    let resolution_handle = if let Some(bind) = config.credential_resolution_bind.clone() {
        let broker = kernel::credential_broker::init_credential_broker(db_pool.clone());
        let service_token_sha256 = config
            .credential_resolution_service_token
            .as_deref()
            .map(egress::token::hash_token);
        if service_token_sha256.is_none() {
            warn!(
                "Credential resolution endpoint bound without a service token; \
                 it will deny every request (fail closed)"
            );
        }
        let state = kernel::credential_resolution::ResolutionState {
            registry: kernel::credential_resolution::global_resolution_registry().clone(),
            broker,
            service_token_sha256,
        };
        let router = kernel::credential_resolution::resolution_router(state);
        match tokio::net::TcpListener::bind(&bind).await {
            Ok(listener) => {
                info!(addr = %bind, "Credential resolution endpoint started");
                Some(tokio::spawn(async move {
                    if let Err(e) = axum::serve(listener, router).await {
                        error!("Credential resolution server error: {e}");
                    }
                }))
            }
            Err(e) => {
                error!(addr = %bind, "Failed to bind credential resolution endpoint: {e}");
                None
            }
        }
    } else {
        None
    };

    // Start task scheduler
    let scheduler_handle = kernel::scheduler::spawn_scheduler(
        db_pool.clone(),
        queue.clone(),
        bridge_registry.clone(),
        sandbox_provider.clone(),
        egress_enforcer.clone(),
        config.clone(),
    );
    info!("Task scheduler started");

    // Start task controller (periodic checks)
    let task_ctrl_handle = task_controller.spawn();
    info!("Task controller started");

    // Start sandbox controller
    let sandbox_controller = Arc::new(kernel::sandbox_controller::SandboxController::new(
        db_pool.clone(),
        queue.clone(),
        bridge_registry.clone(),
        sandbox_provider.clone(),
        egress_enforcer.clone(),
        redis_coordinator.clone(),
        config.clone(),
        runtime_config.clone(),
    ));
    let sandbox_ctrl_handles = sandbox_controller.clone().spawn();
    info!(
        "Sandbox controller started ({} loops)",
        sandbox_ctrl_handles.len()
    );

    // Start event bus subscribers
    let mut subscriber_handles = Vec::new();

    // SessionStateSubscriber (PERSIST phase)
    let session_state_sub = events::session_state::SessionStateSubscriber::new(
        db_pool.clone(),
        redis_client
            .clone()
            .expect("Redis is required for session state subscriber"),
        config.instance_id.clone(),
    );
    subscriber_handles.push(session_state_sub.spawn(event_bus.subscribe()));
    info!("SessionStateSubscriber started");

    // SessionBroadcastSubscriber (BROADCAST phase)
    let session_broadcast_sub =
        events::session_broadcast::SessionBroadcastSubscriber::new(session_broadcaster.clone());
    subscriber_handles.push(session_broadcast_sub.spawn(event_bus.subscribe()));
    info!("SessionBroadcastSubscriber started");

    // TaskBroadcastSubscriber (BROADCAST phase)
    let task_broadcast_sub =
        events::task_broadcast::TaskBroadcastSubscriber::new(bridge_registry.clone());
    subscriber_handles.push(task_broadcast_sub.spawn(event_bus.subscribe()));
    info!("TaskBroadcastSubscriber started");

    if config.event_stream_enabled {
        info!(
            "EventStreamPublisher enabled inside EventBus (key={})",
            config.event_stream_key
        );
    }

    // Start command listener (cross-instance relay via Redis)
    let cmd_listener_handle = if let Some(ref client) = redis_client {
        let listener = kernel::command_listener::CommandListener::new(
            client.clone(),
            &config.instance_id,
            db_pool.clone(),
            bridge_registry.clone(),
            sandbox_provider.clone(),
            egress_enforcer.clone(),
            None, // image_builder
            redis_coordinator.clone(),
            memory_subscribers.clone(),
        );
        Some(listener.spawn())
    } else {
        None
    };
    if cmd_listener_handle.is_some() {
        info!("Command listener started");
    }

    // Setup SIGHUP handler for config hot-reload
    #[cfg(unix)]
    {
        let rc = runtime_config.clone();
        tokio::spawn(async move {
            let mut sighup = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::hangup())
                .expect("failed to register SIGHUP handler");
            loop {
                sighup.recv().await;
                info!("SIGHUP received, reloading runtime config...");
                let new_cfg = JoySafeterConfig::from_env();
                rc.update(
                    new_cfg.sandbox_idle_timeout,
                    new_cfg.sandbox_stopped_ttl,
                    new_cfg.heartbeat_ttl,
                    new_cfg.sandbox_failure_threshold,
                    new_cfg.sandbox_pool_min_size as u64,
                    new_cfg.sandbox_pool_max_age,
                    new_cfg.event_batch_max_size as u64,
                    new_cfg.event_batch_max_delay_ms,
                );
                info!("Runtime config reloaded successfully");
            }
        });
    }

    let total_tasks = 3
        + sandbox_ctrl_handles.len()
        + subscriber_handles.len()
        + if cmd_listener_handle.is_some() { 1 } else { 0 };
    info!(total_tasks, "JoySafeter kernel fully started");
    kernel::active_standby::set_active_pod_label(&config.instance_id, true).await?;
    control_plane_health.set_active(true);

    tokio::select! {
        _ = shutdown.cancelled() => {
            info!("Shutdown signal received, stopping...");
        }
        _ = leadership.wait_lost() => {
            warn!("Active leadership lost, stopping control plane...");
        }
    }
    control_plane_health.set_active(false);
    if let Err(error) =
        kernel::active_standby::set_active_pod_label(&config.instance_id, false).await
    {
        warn!(error = %error, "Failed to clear active control-plane Pod label");
    }

    // Graceful shutdown
    // 1. Send shutdown to all connected runners
    bridge_registry.shutdown_all().await;

    // 2. Stop background tasks
    // #26: gRPC graceful shutdown with 5s grace period (Python L448: stop(grace=5))
    grpc_handle.abort();
    if let Some(handle) = xds_handle {
        handle.abort();
    }
    xds_shadow_shutdown.cancel();
    if let Some(handle) = xds_reconciler_handle {
        handle.abort();
    }
    if let Some(mut handle) = xds_observer_handle {
        if tokio::time::timeout(std::time::Duration::from_secs(5), &mut handle)
            .await
            .is_err()
        {
            warn!("Timed out draining Rust xDS shadow observations");
            handle.abort();
        }
    }
    if let Some(handle) = ext_authz_handle {
        handle.abort();
    }
    // Give in-flight RPCs 5s to complete
    tokio::time::sleep(std::time::Duration::from_secs(5)).await;
    if let Some(handle) = resolution_handle {
        handle.abort();
    }
    scheduler_handle.abort();
    task_ctrl_handle.abort();
    for h in sandbox_ctrl_handles {
        h.abort();
    }
    for h in subscriber_handles {
        h.abort();
    }
    if let Some(h) = cmd_listener_handle {
        h.abort();
    }

    // 3. Deregister from Redis
    if let Some(ref coord) = redis_coordinator {
        let _ = coord.stop().await;
    }

    // 4. Flush remaining events
    event_bus.flush().await;

    leadership.release().await;
    signal_handle.abort();
    health_handle.abort();

    info!("JoySafeter Orchestrator shut down");
    Ok(())
}

/// Wait for SIGINT or SIGTERM.
async fn shutdown_signal() {
    let ctrl_c = tokio::signal::ctrl_c();

    #[cfg(unix)]
    {
        let mut sigterm = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
            .expect("failed to register SIGTERM handler");
        tokio::select! {
            _ = ctrl_c => {},
            _ = sigterm.recv() => {},
        }
    }

    #[cfg(not(unix))]
    {
        ctrl_c.await.expect("failed to listen for Ctrl+C");
    }
}
