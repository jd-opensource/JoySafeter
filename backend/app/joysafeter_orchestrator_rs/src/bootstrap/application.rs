//! Orchestrator composition root and service lifecycle.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use crate::config::JoySafeterConfig;
use crate::kernel::agent_identity_config::AgentIdentityProviderKind;
use crate::{db, events, grpc, kernel, runtime_config, xds};
use tracing::{error, info, warn};

use super::supervisor::{shutdown_signal, spawn_health_server};
use super::{
    build_network_policy_material_resolver, ProviderFactoryRegistry, RuntimeComponents,
    RuntimeFactoryContext,
};

pub struct OrchestratorApplication {
    config: JoySafeterConfig,
}

impl OrchestratorApplication {
    pub async fn build(config: JoySafeterConfig) -> anyhow::Result<Self> {
        config.validate()?;
        Ok(Self { config })
    }

    pub async fn run(self) -> anyhow::Result<()> {
        let config = self.config;

        info!(
            instance_id = %config.instance_id,
            grpc_addr = %config.grpc_addr(),
            xds_addr = %config.xds_addr(),
            max_concurrent_tasks = config.max_concurrent_tasks,
            sandbox_provider = %config.sandbox_provider,
            "Starting JoySafeter Orchestrator (Rust)"
        );

        // Initialize database pool
        let db_pool = db::pool::create_pool(&config.database_url).await?;
        info!("Database pool initialized");
        kernel::sensitive_material::versioned::VersionedMaterialProtector::validate_database_state(
            &db_pool,
        )
        .await?;

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

        // Initialize Agent Identity Provider (pluggable, feature-gated)
        let identity_provider_kind =
            AgentIdentityProviderKind::from_env()?.validate_feature_availability()?;
        let identity_provider: Arc<dyn kernel::agent_identity_provider::AgentIdentityProvider> =
            match identity_provider_kind {
                AgentIdentityProviderKind::None => {
                    info!("Agent identity provider: none");
                    Arc::new(kernel::agent_identity_provider::NoopAgentIdentityProvider)
                }
                AgentIdentityProviderKind::Jd => {
                    #[cfg(feature = "jd-identity")]
                    {
                        let redis = redis_client.as_ref().ok_or_else(|| {
                            anyhow::anyhow!("Redis is required when AGENT_IDENTITY_PROVIDER=jd")
                        })?;
                        let provider =
                            jd_agent_identity::JdAgentIdentityProvider::from_env(redis.clone())?;
                        info!("Agent identity provider: jd");
                        Arc::new(provider)
                    }
                    #[cfg(not(feature = "jd-identity"))]
                    {
                        anyhow::bail!(
                        "AGENT_IDENTITY_PROVIDER=jd requires a binary built with the jd-identity feature"
                    );
                    }
                }
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

        // Initialize the single xDS authority before constructing any provider or
        // transport so every control-plane boundary observes the same lifecycle.
        let managed_xds_authority = config.ha_mode == "multi"
            && matches!(config.sandbox_provider.as_str(), "k8s" | "kubernetes")
            && config.grpc_xds_enabled();
        let xds_authority = if managed_xds_authority {
            xds::authority::XdsAuthority::managed()
        } else {
            xds::authority::XdsAuthority::standalone()
        };
        let xds_control_plane = config.grpc_xds_enabled().then(|| {
            let visibility = match config.sandbox_provider.as_str() {
                "k8s" | "kubernetes" => xds::control_plane::NodeVisibility::NodeScoped,
                _ => xds::control_plane::NodeVisibility::Unscoped,
            };
            xds::control_plane::XdsControlPlane::new(xds_authority.clone(), visibility)
        });
        let RuntimeComponents {
            sandbox_provider,
            network_policy_runtime,
            envoy_manager,
        } = ProviderFactoryRegistry::with_defaults()
            .build(
                &config.sandbox_provider,
                &config,
                &RuntimeFactoryContext {
                    xds_authority: xds_authority.clone(),
                    xds_control_plane: xds_control_plane.clone(),
                },
            )
            .await?;
        let network_policy_material_resolver = build_network_policy_material_resolver(
            db_pool.clone(),
            config.llm_egress_allowed_hosts.clone(),
        );
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

        // ── xDS leader (K8s multi mode only) ──────────────────────────────────
        // Task scheduling in multi mode is leaderless (all replicas active), but the
        // Envoy xDS control plane is stateful and must converge to a single source.
        // Elect a dedicated xDS leader and label its pod so the leader-only Service
        // routes every Envoy DaemonSet to one replica. No-op unless multi + k8s +
        // xDS enabled (Docker/standalone/leader already have a single xDS source).
        let mut xds_leader_handle = None;
        if config.ha_mode == "multi"
            && config.sandbox_provider == "k8s"
            && xds_control_plane.is_some()
        {
            let kube_client = kube::Client::try_default().await.map_err(|error| {
            anyhow::anyhow!(
                "multi+k8s gRPC xDS requires K8s leader coordination, but client init failed: {error}"
            )
        })?;
            let pod_name = std::env::var("POD_NAME").map_err(|_| {
                anyhow::anyhow!(
                    "multi+k8s gRPC xDS requires POD_NAME for leader label coordination"
                )
            })?;
            xds_leader_handle = Some(xds::leader::spawn(
                kube_client,
                xds_authority.clone(),
                config.k8s_namespace.clone(),
                pod_name,
                config.xds_leader_lease_name.clone(),
                config.leader_identity.clone(),
                std::time::Duration::from_secs(config.leader_lease_duration_sec),
                std::time::Duration::from_secs(config.leader_renew_interval_sec),
            ));
        }
        if config.ha_mode == "multi"
            && sandbox_provider.capabilities().has_egress_management
            && xds_leader_handle.is_none()
        {
            anyhow::bail!(
                "multi-replica managed egress requires the K8s leader-only xDS authority"
            );
        }

        // Health server — expose readiness/liveness for K8s probes.
        // Starts early (both leader and standby expose /healthz/live).
        // ready_flag is set to true only after services are fully started.
        let ready_flag = Arc::new(AtomicBool::new(!config.leader_election_enabled));
        spawn_health_server(
            9091,
            ready_flag.clone(),
            xds_authority.clone(),
            xds_control_plane.clone(),
        );

        let xds_handle = if let Some(service) = xds_control_plane.as_ref() {
            let authenticator = Arc::new(xds::auth::SharedTokenAuthenticator::new(
                config.parse_xds_auth_keyring()?,
            ));
            let handle =
                xds::transport::start_xds_server(config.xds_addr(), service.clone(), authenticator)
                    .await?;
            info!(addr = %config.xds_addr(), "authenticated xDS server started");
            Some(handle)
        } else {
            if config.grpc_xds_enabled() {
                anyhow::bail!(
                    "gRPC xDS is enabled but the selected sandbox provider has no xDS service"
                );
            }
            None
        };

        // Initialize the network-policy runtime before authority recovery.
        // Fail-closed: if egress control cannot initialize or recover, abort startup
        // rather than becoming ready and serving sandboxes without enforcement.
        network_policy_runtime.initialize().await?;
        if !managed_xds_authority {
            let recovery = xds_authority.begin_staging()?;
            if sandbox_provider.capabilities().has_egress_management {
                kernel::network_policy::recovery::recover_as_authority(
                    &db_pool,
                    network_policy_runtime.as_ref(),
                    network_policy_material_resolver.as_ref(),
                    &recovery,
                )
                .await?;
            }
            if matches!(
                xds_authority.phase(),
                xds::authority::AuthorityPhase::Staging { .. }
            ) {
                xds_authority.begin_recovery_serving(&recovery)?;
            }
            xds_authority.mark_ready(&recovery)?;
        }
        if let Some(manager) = envoy_manager.clone() {
            manager.spawn_health_monitor(xds_authority.clone());
        }

        // Initialize HA components (bridge store, task dispatcher, network-policy wakeup queue)
        let mut ha = kernel::ha::build_ha_components(&config, redis_client.as_ref());
        let bridge_store = ha.bridge_store.clone();
        info!(ha_mode = %ha.mode.as_str(), "HA components initialized");

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
            bridge_store.clone(),
        );
        task_controller.recover_on_startup().await?;
        info!("Startup recovery complete");

        // Orphaned sandbox cleanup
        let sandbox_controller_for_cleanup = Arc::new(
            kernel::sandbox_controller::SandboxController::new(
                db_pool.clone(),
                queue.clone(),
                bridge_store.clone(),
                sandbox_provider.clone(),
                redis_coordinator.clone(),
                config.clone(),
                runtime_config.clone(),
            )
            .with_network_policy_runtime(network_policy_runtime.clone())
            .with_network_policy_material_resolver(network_policy_material_resolver.clone())
            .with_network_policy_control(xds_authority.clone(), ha.network_policy_queue.clone()),
        );
        match sandbox_controller_for_cleanup.cleanup_orphaned().await {
            Ok(n) if n > 0 => info!("Cleaned up {n} orphaned sandboxes"),
            Ok(_) => {}
            Err(e) => warn!("Orphan cleanup failed: {e}"),
        }

        // Start gRPC server
        let grpc_sandbox_resolver = Arc::new(
            kernel::sandbox_resolver::SandboxResolver::new(
                db_pool.clone(),
                sandbox_provider.clone(),
                config.clone(),
            )
            .with_network_policy_runtime(network_policy_runtime.clone())
            .with_network_policy_material_resolver(network_policy_material_resolver.clone())
            .with_network_policy_control(xds_authority.clone(), ha.network_policy_queue.clone())
            .with_identity_provider(identity_provider.clone()),
        );
        let grpc_handle = grpc::server::start_grpc_server(
            config.grpc_addr(),
            bridge_store.clone(),
            event_bus.clone(),
            queue.clone(),
            db_pool.clone(),
            config.clone(),
            grpc_sandbox_resolver,
            redis_coordinator.clone(),
            memory_subscribers.clone(),
            runtime_config.clone(),
        )
        .await?;
        info!(addr = %config.grpc_addr(), "gRPC server started");

        if managed_xds_authority {
            let request_source = Box::new(kernel::ha::RedisNetworkPolicyRequestSource::new(
                redis_client
                    .as_ref()
                    .expect("Redis is required for multi mode")
                    .clone(),
            ));
            let authority_work = Arc::new(
                kernel::network_policy::authority::NetworkPolicyAuthorityHandler::new(
                    db_pool.clone(),
                    network_policy_runtime.clone(),
                    network_policy_material_resolver.clone(),
                ),
            );
            let xds_authority_handle = tokio::spawn(xds::authority_worker::run_authority_worker(
                request_source,
                authority_work,
                xds_authority.clone(),
            ));
            ha.background_handles.push(xds_authority_handle);
        }

        // Start task controller (periodic checks)
        let task_ctrl_handle = task_controller.spawn();
        info!("Task controller started");

        // Start sandbox controller
        let sandbox_controller = Arc::new(
            kernel::sandbox_controller::SandboxController::new(
                db_pool.clone(),
                queue.clone(),
                bridge_store.clone(),
                sandbox_provider.clone(),
                redis_coordinator.clone(),
                config.clone(),
                runtime_config.clone(),
            )
            .with_network_policy_runtime(network_policy_runtime.clone())
            .with_network_policy_material_resolver(network_policy_material_resolver.clone())
            .with_network_policy_control(xds_authority.clone(), ha.network_policy_queue.clone()),
        );
        let sandbox_ctrl_handles = sandbox_controller.clone().spawn();
        info!(
            "Sandbox controller started ({} loops)",
            sandbox_ctrl_handles.len()
        );

        // Start task scheduler (after sandbox controller so pool_replenish_notify is available)
        let scheduler_handle = kernel::scheduler::spawn_scheduler(
            db_pool.clone(),
            queue.clone(),
            bridge_store.clone(),
            ha.task_dispatcher.clone(),
            sandbox_provider.clone(),
            network_policy_runtime.clone(),
            network_policy_material_resolver.clone(),
            config.clone(),
            Some(sandbox_controller.pool_replenish_notify.clone()),
            ha.network_policy_queue.clone(),
            xds_authority.clone(),
            identity_provider.clone(),
        );
        info!("Task scheduler started");

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
            events::task_broadcast::TaskBroadcastSubscriber::new(bridge_store.clone());
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
                bridge_store.clone(),
                ha.task_dispatcher.clone(),
                sandbox_provider.clone(),
                envoy_manager.clone(),
                None, // image_builder
                redis_coordinator.clone(),
                memory_subscribers.clone(),
            )
            .with_network_policy_runtime(network_policy_runtime.clone())
            .with_network_policy_material_resolver(network_policy_material_resolver.clone())
            .with_network_policy_control(xds_authority.clone(), ha.network_policy_queue.clone());
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
                let mut sighup =
                    tokio::signal::unix::signal(tokio::signal::unix::SignalKind::hangup())
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

        // Hand off xDS leadership up front: drop our pod label (Envoy xDS Service
        // stops routing to us) and release the Lease so a peer wins within seconds
        // instead of waiting for lease expiry. Without this, the terminating pod
        // keeps the label through its whole grace period, leaving a ~lease-duration
        // gap with no xDS leader during rolling upgrades.
        if let Some(ref xh) = xds_leader_handle {
            xh.shutdown().await;
        } else {
            let _ = xds_authority.revoke();
        }

        // Stop scheduler immediately (no new tasks claimed).
        scheduler_handle.abort();

        // Give in-flight runner streams and gRPC calls time to finish.
        // Runners that are mid-task will continue autonomously (agent runs locally);
        // they reconnect to the new leader and report results there.
        const DRAIN_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(10);
        let active_bridges = bridge_store.all_bridges().len();
        if active_bridges > 0 {
            info!(
                active_bridges,
                "Waiting up to {DRAIN_TIMEOUT:?} for active bridges to finish"
            );
            tokio::time::sleep(DRAIN_TIMEOUT).await;
        }

        // Send shutdown to remaining connected runners — ONLY in standalone mode.
        //
        // In standalone the only orchestrator is going away, so runners must exit
        // (nothing to reconnect to). In multi/leader modes this replica is one of
        // several: on a rolling restart the runner's gRPC stream simply breaks and
        // it reconnects to a surviving replica via the Service (bridge state is in
        // Redis). Sending an explicit Shutdown here would needlessly kill every
        // running sandbox on each orchestrator deploy, defeating HA.
        if ha.mode.as_str() == "standalone" {
            bridge_store.shutdown_all().await;
        } else {
            info!(
                ha_mode = %ha.mode.as_str(),
                "Skipping runner shutdown broadcast; runners will reconnect to a surviving replica"
            );
        }

        // Stop remaining background tasks
        grpc_handle.abort();
        if let Some(handle) = xds_handle {
            handle.abort();
        }
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
        // Stop HA background loops (inbox, heartbeat, network-policy authority requests)
        for h in ha.background_handles {
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
}
