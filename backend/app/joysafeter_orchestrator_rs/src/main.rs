//! JoySafeter Orchestrator — Rust implementation.
//!
//! Provides the joysafeter kernel: gRPC server for sandbox-runner connections,
//! task scheduling, sandbox lifecycle management, and event persistence.

mod config;
mod db;
mod events;
mod grpc;
mod kernel;
mod runtime_config;
mod sandbox;

use std::sync::Arc;

use bollard::Docker;
use config::JoySafeterConfig;
use tracing::{info, warn};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Load .env if present
    let _ = dotenvy::dotenv();

    // Initialize tracing
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .with_target(true)
        .init();

    let config = JoySafeterConfig::from_env();

    if !config.enabled {
        info!("JoySafeter kernel disabled (JOYSAFETER_ENABLED=false)");
        return Ok(());
    }

    info!(
        instance_id = %config.instance_id,
        grpc_addr = %config.grpc_addr(),
        max_concurrent_tasks = config.max_concurrent_tasks,
        sandbox_provider = %config.sandbox_provider,
        "Starting JoySafeter Orchestrator (Rust)"
    );

    // Initialize database pool
    let db_pool = db::pool::create_pool(&config.database_url).await?;
    info!("Database pool initialized");

    // Initialize Redis. The Rust orchestrator relies on Redis for API->runtime
    // task queueing, cross-instance command relay, sandbox ownership, and live
    // event fan-out. Starting without it would create a half-working runtime.
    let redis_client = match &config.redis_url {
        Some(url) => match redis::Client::open(url.as_str()) {
            Ok(client) => {
                info!("Redis client initialized");
                client
            }
            Err(e) => {
                return Err(anyhow::anyhow!("Failed to initialize Redis client: {e}"));
            }
        },
        None => {
            return Err(anyhow::anyhow!(
                "REDIS_URL is required for the Rust orchestrator runtime queue"
            ));
        }
    };

    // Initialize Redis coordinator (HA)
    let redis_coordinator = {
        let coord = kernel::redis_coordinator::RedisCoordinator::new(
            redis_client.clone(),
            &config.instance_id,
            config.heartbeat_interval,
            config.heartbeat_ttl,
        );
        coord.register_instance().await.map_err(|e| {
            anyhow::anyhow!("Failed to register orchestrator instance in Redis: {e}")
        })?;
        coord.spawn_heartbeat();
        info!(
            "RedisCoordinator registered (instance={})",
            config.instance_id
        );
        Some(Arc::new(coord))
    };

    // Initialize runtime config (hot-reloadable)
    let runtime_config = Arc::new(runtime_config::RuntimeConfig::from_config(&config));

    // Initialize event bus
    let event_bus = events::bus::EventBus::new(
        db_pool.clone(),
        &config,
        runtime_config.clone(),
        redis_client.clone(),
    );
    // Start periodic flush timer so buffered events don't sit in memory
    // indefinitely when event rate is below the batch threshold.
    let _flush_timer = event_bus.persister().spawn_flush_timer();
    info!("Event bus initialized (flush timer started)");

    // Initialize session broadcaster
    let session_broadcaster = kernel::session_broadcaster::SessionBroadcaster::new(
        redis_client.clone(),
        &config.instance_id,
    );
    info!("Session broadcaster initialized");

    // Initialize sandbox provider (select based on config)
    let sandbox_provider: Arc<dyn sandbox::provider::SandboxProvider> = match config
        .sandbox_provider
        .as_str()
    {
        "daytona" => {
            if config.daytona_api_url.is_empty() || config.daytona_api_key.is_empty() {
                return Err(anyhow::anyhow!(
                    "JOYSAFETER_DAYTONA_API_URL and JOYSAFETER_DAYTONA_API_KEY required"
                ));
            }
            Arc::new(sandbox::daytona::DaytonaProvider::new(
                &config.daytona_api_url,
                &config.daytona_api_key,
                config.daytona_target.as_deref().unwrap_or("us"),
                &config.daytona_snapshot,
            ))
        }
        "e2b" => {
            if config.e2b_api_key.is_empty() || config.e2b_template_id.is_empty() {
                return Err(anyhow::anyhow!(
                    "JOYSAFETER_E2B_API_KEY and JOYSAFETER_E2B_TEMPLATE_ID required"
                ));
            }
            Arc::new(sandbox::e2b::E2bProvider::new(
                config
                    .e2b_api_url
                    .as_deref()
                    .unwrap_or("https://api.e2b.app"),
                &config.e2b_api_key,
                &config.e2b_template_id,
            ))
        }
        "docker" | "" => Arc::new(sandbox::docker::DockerProvider::new(&config).await?),
        other => {
            return Err(anyhow::anyhow!(
                    "Unsupported JOYSAFETER_SANDBOX_PROVIDER={other}. Expected docker, daytona, or e2b."
                ));
        }
    };
    info!(
        provider = %config.sandbox_provider,
        "Sandbox provider initialized"
    );

    // Initialize Envoy network isolation when enabled.
    //
    // The LDS backend is selected by `envoy_xds_mode`:
    //   filesystem → FilesystemLds (writes lds.json into the Envoy container)
    //   grpc       → GrpcLds backed by a DeltaXdsServer that is also registered
    //                on the orchestrator gRPC server below.
    // `xds_service` is Some only in grpc mode; it is handed to start_grpc_server.
    let mut xds_service: Option<Arc<sandbox::lds_backend::DeltaXdsServer>> = None;
    let envoy_manager = if config.envoy_enabled {
        let docker = Arc::new(
            Docker::connect_with_local_defaults()
                .map_err(|e| anyhow::anyhow!("failed to connect to Docker for Envoy: {e}"))?,
        );
        let (lds, cds): (
            Arc<dyn sandbox::lds_backend::LdsBackend>,
            Arc<dyn sandbox::lds_backend::CdsBackend>,
        ) = if config.envoy_xds_mode == "grpc" {
            let server = sandbox::lds_backend::DeltaXdsServer::new();
            xds_service = Some(server.clone());
            (
                Arc::new(sandbox::lds_backend::GrpcLds::new(server.clone())),
                Arc::new(sandbox::lds_backend::GrpcCds::new(server)),
            )
        } else {
            (
                Arc::new(sandbox::lds_backend::FilesystemLds::new(
                    docker.clone(),
                    config.envoy_container_name.clone(),
                )),
                Arc::new(sandbox::lds_backend::FilesystemCds::new(
                    docker.clone(),
                    config.envoy_container_name.clone(),
                )),
            )
        };
        let manager = Arc::new(sandbox::envoy::EnvoyManager::new(
            docker,
            sandbox::envoy::EnvoyConfig {
                grpc_target_host: config.envoy_grpc_host.clone(),
                grpc_target_port: config.envoy_grpc_port,
                container_name: config.envoy_container_name.clone(),
                xds_mode: config.envoy_xds_mode.clone(),
            },
            lds,
            cds,
        ));
        if let Err(e) = manager.init().await {
            warn!("EnvoyManager initialization failed: {e}");
            None
        } else {
            // Rebuild LDS state for still-live sandboxes from the DB. The listener
            // set is not persisted (filesystem lds.json is wiped by init(); the
            // gRPC Delta xDS state is in-memory), so without this a restarted
            // orchestrator would leave running sandboxes without network egress.
            if let Err(e) = manager
                .recover_from_db(&db_pool, &config.llm_egress_allowed_hosts)
                .await
            {
                warn!("EnvoyManager LDS recovery from DB failed: {e}");
            }
            info!(xds_mode = %config.envoy_xds_mode, "EnvoyManager initialized");
            Some(manager)
        }
    } else {
        info!("Envoy network isolation disabled");
        None
    };

    let image_builder = if config.image_builder_enabled {
        match Docker::connect_with_local_defaults() {
            Ok(docker) => {
                info!("ImageBuilder initialized");
                Some(Arc::new(sandbox::image_builder::ImageBuilder::new(
                    Arc::new(docker),
                    &config.image_builder_base,
                )))
            }
            Err(e) => {
                warn!("ImageBuilder initialization failed: {e}");
                None
            }
        }
    } else {
        info!("Image builder disabled");
        None
    };

    // Initialize sandbox bridge registry
    let bridge_registry = kernel::sandbox_bridge::BridgeRegistry::new();

    // Initialize Redis-backed task queue.
    let queue = kernel::queue::TaskQueue::new(redis_client.clone());

    // Initialize memory store subscribers
    let memory_subscribers = Arc::new(kernel::memory_sync::MemoryStoreSubscribers::new());
    info!("MemoryStoreSubscribers initialized");

    // Task controller — startup recovery
    let task_controller = kernel::task_controller::TaskController::new(
        db_pool.clone(),
        queue.clone(),
        config.clone(),
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
            envoy_manager.clone(),
            redis_coordinator.clone(),
            config.clone(),
            runtime_config.clone(),
        ));
    match sandbox_controller_for_cleanup.cleanup_orphaned().await {
        Ok(n) if n > 0 => info!("Cleaned up {n} orphaned sandboxes"),
        Ok(_) => {}
        Err(e) => warn!("Orphan cleanup failed: {e}"),
    }

    // Start gRPC server
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
        xds_service,
    )
    .await?;
    info!(addr = %config.grpc_addr(), "gRPC server started");

    // Start task scheduler
    let scheduler_handle = kernel::scheduler::spawn_scheduler(
        db_pool.clone(),
        queue.clone(),
        bridge_registry.clone(),
        sandbox_provider.clone(),
        envoy_manager.clone(),
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
        envoy_manager.clone(),
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
        redis_client.clone(),
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

    // EventStreamPublisher (if Redis stream enabled)
    if config.event_stream_enabled {
        let stream_pub = events::stream_publisher::EventStreamPublisher::new(
            redis_client.clone(),
            &config.event_stream_key,
            config.event_stream_max_len,
            Some(event_bus.persister()),
            config.event_stream_fallback_to_db,
        );
        subscriber_handles.push(stream_pub.spawn(event_bus.subscribe()));
        info!(
            "EventStreamPublisher started (key={})",
            config.event_stream_key
        );
    }

    // Start command listener (cross-instance relay via Redis)
    let listener = kernel::command_listener::CommandListener::new(
        redis_client.clone(),
        &config.instance_id,
        db_pool.clone(),
        bridge_registry.clone(),
        sandbox_provider.clone(),
        envoy_manager.clone(),
        image_builder.clone(),
        redis_coordinator.clone(),
        memory_subscribers.clone(),
    );
    let cmd_listener_handle = listener.spawn();
    info!("Command listener started");

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

    let total_tasks = 3 + sandbox_ctrl_handles.len() + subscriber_handles.len() + 1;
    info!(total_tasks, "JoySafeter kernel fully started");

    // Wait for shutdown signal
    shutdown_signal().await;
    info!("Shutdown signal received, stopping...");

    // Graceful shutdown
    // 1. Send shutdown to all connected runners
    bridge_registry.shutdown_all().await;

    // 2. Stop background tasks
    // #26: gRPC graceful shutdown with 5s grace period (Python L448: stop(grace=5))
    grpc_handle.abort();
    // Give in-flight RPCs 5s to complete
    tokio::time::sleep(std::time::Duration::from_secs(5)).await;
    scheduler_handle.abort();
    task_ctrl_handle.abort();
    for h in sandbox_ctrl_handles {
        h.abort();
    }
    for h in subscriber_handles {
        h.abort();
    }
    cmd_listener_handle.abort();

    // 3. Deregister from Redis
    if let Some(ref coord) = redis_coordinator {
        let _ = coord.stop().await;
    }

    // 4. Flush remaining events
    event_bus.flush().await;

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
