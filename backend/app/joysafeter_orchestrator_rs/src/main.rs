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

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use config::JoySafeterConfig;
use tracing::{error, info, warn};

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
    config.validate()?;

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
    let (sandbox_provider, xds_service): (
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
            (
                Arc::new(docker_provider) as Arc<dyn sandbox::provider::SandboxProvider>,
                xds,
            )
        }
        "k8s" | "kubernetes" => {
            let provider = sandbox::k8s::K8sProvider::new(&config).await?;
            let xds = provider.xds_service();
            (Arc::new(provider), xds)
        }
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

    // ── Leader Election (K8s Lease-based HA) ──────────────────────────────
    // When enabled (K8s deployment with replicas>1), only the leader instance
    // runs services. Standby instances wait for the Lease to expire/release.
    // When disabled (single-instance / Docker Compose), skip entirely.
    let leader_election = if config.leader_election_enabled {
        let kube_client = kube::Client::try_default().await.map_err(|e| {
            anyhow::anyhow!(
                "Leader election enabled but K8s client init failed: {e}. \
                 Set JOYSAFETER_LEADER_ELECTION_ENABLED=false for non-K8s deployments."
            )
        })?;
        let le = Arc::new(kernel::leader_election::LeaderElection::new(
            kube_client,
            &config.k8s_namespace,
            &config.leader_lease_name,
            &config.leader_identity,
            std::time::Duration::from_secs(config.leader_lease_duration_sec),
            std::time::Duration::from_secs(config.leader_renew_interval_sec),
        ));
        le.clone().spawn();
        info!(
            identity = %config.leader_identity,
            lease = %config.leader_lease_name,
            "Waiting for leader election..."
        );
        le.wait_until_leading().await;
        info!(identity = %config.leader_identity, "Acquired leadership — starting services");
        Some(le)
    } else {
        None
    };

    // Health server — expose readiness/liveness for K8s probes.
    // Starts early (both leader and standby expose /healthz/live).
    // ready_flag is set to true only after services are fully started.
    let ready_flag = Arc::new(AtomicBool::new(!config.leader_election_enabled));
    spawn_health_server(9091, ready_flag.clone());

    // Provider startup: Envoy init, DB recovery, ImageBuilder, etc.
    if let Err(e) = sandbox_provider.on_startup(&db_pool).await {
        warn!("Provider on_startup failed: {e}");
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
            None, // envoy_manager
            config.llm_egress_allowed_hosts.clone(),
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
    ready_flag.store(true, Ordering::Release);

    // Wait for shutdown signal OR leadership loss
    if let Some(ref le) = leader_election {
        tokio::select! {
            _ = shutdown_signal() => {
                info!("Shutdown signal received, releasing leadership...");
                le.release().await;
            }
            _ = le.wait_until_lost() => {
                warn!("Lost leadership — shutting down to yield to new leader");
            }
        }
    } else {
        shutdown_signal().await;
    }

    // ── Graceful drain ─────────────────────────────────────────────────────
    // Mark not-ready FIRST so K8s Service stops sending new traffic, then
    // drain in-flight work before stopping services.
    ready_flag.store(false, Ordering::Release);
    info!("Marked not-ready; draining in-flight work...");

    // Stop scheduler immediately (no new tasks claimed).
    scheduler_handle.abort();

    // Give in-flight runner streams and gRPC calls time to finish.
    // Runners that are mid-task will continue autonomously (agent runs locally);
    // they reconnect to the new leader and report results there.
    const DRAIN_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(10);
    let active_bridges = bridge_registry.all_bridges().len();
    if active_bridges > 0 {
        info!(
            active_bridges,
            "Waiting up to {DRAIN_TIMEOUT:?} for active bridges to finish"
        );
        tokio::time::sleep(DRAIN_TIMEOUT).await;
    }

    // Send shutdown to remaining connected runners
    bridge_registry.shutdown_all().await;

    // Stop remaining background tasks
    grpc_handle.abort();
    tokio::time::sleep(std::time::Duration::from_secs(3)).await;
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

/// Minimal HTTP health server for K8s readinessProbe / livenessProbe.
/// - GET /healthz/ready → 200 if leader (Service routes traffic), 503 if standby
/// - GET /healthz/live  → 200 always (process is alive)
fn spawn_health_server(port: u16, ready: Arc<AtomicBool>) {
    use tokio::io::AsyncWriteExt;
    tokio::spawn(async move {
        let listener = match tokio::net::TcpListener::bind(("0.0.0.0", port)).await {
            Ok(l) => l,
            Err(e) => {
                warn!(port, error = %e, "Health server bind failed");
                return;
            }
        };
        info!(port, "Health server listening");
        loop {
            let Ok((mut stream, _)) = listener.accept().await else {
                continue;
            };
            let ready_clone = ready.clone();
            tokio::spawn(async move {
                let mut buf = [0u8; 512];
                let _ = tokio::io::AsyncReadExt::read(&mut stream, &mut buf).await;
                let req = String::from_utf8_lossy(&buf);
                let response = if req.contains("/healthz/ready") {
                    if ready_clone.load(Ordering::Acquire) {
                        "HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"
                    } else {
                        "HTTP/1.1 503 Service Unavailable\r\nContent-Length: 7\r\n\r\nstandby"
                    }
                } else {
                    // /healthz/live or any other path → always 200
                    "HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"
                };
                let _ = stream.write_all(response.as_bytes()).await;
            });
        }
    });
}
