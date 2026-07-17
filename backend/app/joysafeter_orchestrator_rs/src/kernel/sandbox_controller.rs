use std::sync::Arc;
use std::time::Duration;

use sqlx::PgPool;
use tokio::sync::Semaphore;
use tokio::task::JoinHandle;
use tracing::{debug, error, info, warn};
use uuid::Uuid;

use crate::config::JoySafeterConfig;
use crate::db::queries;
use crate::kernel::queue::TaskQueue;
use crate::kernel::sandbox_bridge::BridgeRegistry;
use crate::kernel::sandbox_resolver::SandboxResolver;
use crate::runtime_config::RuntimeConfig;
use crate::sandbox::envoy::EnvoyManager;
use crate::sandbox::provider::SandboxProvider;

const ORPHAN_PROVIDER_DB_INSERT_GRACE_SECS: i64 = 120;

/// Background sandbox lifecycle management with full Python parity.
///
/// Runs multiple async loops:
/// - Idle sweep: health check bridges, expire idle, force-stop stuck, destroy stopped
/// - Provisioning poll: detect timed-out provisioning
/// - Pool manager: warm pool top-up, stale pool cleanup
/// - Orphan cleanup: destroy sandboxes with no DB record
pub struct SandboxController {
    pool: PgPool,
    queue: TaskQueue,
    bridge_registry: BridgeRegistry,
    provider: Arc<dyn SandboxProvider>,
    envoy_manager: Option<Arc<EnvoyManager>>,
    redis_coordinator: Option<Arc<crate::kernel::redis_coordinator::RedisCoordinator>>,
    config: JoySafeterConfig,
    runtime_config: Arc<RuntimeConfig>,
}

impl SandboxController {
    pub fn new(
        pool: PgPool,
        queue: TaskQueue,
        bridge_registry: BridgeRegistry,
        provider: Arc<dyn SandboxProvider>,
        envoy_manager: Option<Arc<EnvoyManager>>,
        redis_coordinator: Option<Arc<crate::kernel::redis_coordinator::RedisCoordinator>>,
        config: JoySafeterConfig,
        runtime_config: Arc<RuntimeConfig>,
    ) -> Self {
        Self {
            pool,
            queue,
            bridge_registry,
            provider,
            envoy_manager,
            redis_coordinator,
            config,
            runtime_config,
        }
    }

    /// Spawn all controller loops.
    pub fn spawn(self: Arc<Self>) -> Vec<JoinHandle<()>> {
        let mut handles = Vec::new();

        let s = self.clone();
        handles.push(tokio::spawn(async move { s.idle_sweep_loop().await }));

        let s = self.clone();
        handles.push(tokio::spawn(
            async move { s.provisioning_poll_loop().await },
        ));

        let s = self.clone();
        handles.push(tokio::spawn(async move { s.cleanup_loop().await }));

        handles
    }

    /// Idle sweep loop: runs every 30s.
    /// Phase 0: Health check bridges (detect dead connections)
    /// Phase 1: Expire idle sandboxes past timeout
    /// Phase 2: Force-stop stuck stopping sandboxes (60s threshold)
    /// Phase 3: Destroy stopped sandboxes past TTL
    async fn idle_sweep_loop(self: &Arc<Self>) {
        let interval = Duration::from_secs(30);
        info!("SandboxController idle sweep started (interval=30s)");

        loop {
            tokio::time::sleep(interval).await;

            // Phase 0: Health check bridges
            if let Err(e) = self.health_check_bridges().await {
                error!("Bridge health check error: {e}");
            }

            // Phase 1: Expire idle sandboxes
            if let Err(e) = self.sweep_idle_sandboxes().await {
                error!("Idle sweep error: {e}");
            }

            // Phase 2: Force-stop stuck stopping sandboxes
            if let Err(e) = self.force_stop_stuck().await {
                error!("Force-stop stuck error: {e}");
            }

            // Phase 3: Destroy stopped sandboxes past TTL
            if let Err(e) = self.sweep_stopped_sandboxes().await {
                error!("Stopped sweep error: {e}");
            }
        }
    }

    /// Provisioning poll: detect sandboxes stuck in provisioning (5s interval).
    async fn provisioning_poll_loop(&self) {
        let interval = Duration::from_secs(5);
        info!("SandboxController provisioning poll started (interval=5s)");

        loop {
            tokio::time::sleep(interval).await;

            if let Err(e) = self.check_provisioning_timeout().await {
                error!("Provisioning poll error: {e}");
            }
        }
    }

    /// Cleanup loop: runs every 60s. Pool management + stale cleanup.
    /// S5: Also runs orphan cleanup every 5 iterations (~5 minutes).
    async fn cleanup_loop(&self) {
        let interval = Duration::from_secs(60);
        info!("SandboxController cleanup loop started (interval=60s)");
        let mut iteration: u64 = 0;

        loop {
            tokio::time::sleep(interval).await;
            iteration += 1;

            if self.config.sandbox_pool_enabled {
                if let Err(e) = self.manage_pool().await {
                    error!("Pool management error: {e}");
                }
            }

            // S5: Run orphan cleanup every 5 iterations (~5 minutes)
            if iteration % 5 == 0 {
                match self.cleanup_orphaned().await {
                    Ok(count) => {
                        if count > 0 {
                            info!(count, "Orphan cleanup completed");
                        }
                    }
                    Err(e) => {
                        error!("Orphan cleanup error: {e}");
                    }
                }
            }
        }
    }

    /// Phase 0: Health check all registered bridges.
    /// If a bridge has no active HITL and the container is dead, clean it up.
    async fn health_check_bridges(&self) -> anyhow::Result<()> {
        for bridge in self.bridge_registry.all_bridges() {
            let sandbox_id = bridge.sandbox_db_id;

            // Check sandbox DB status first — skip if already terminal
            if let Ok(Some(sandbox)) = queries::get_sandbox(&self.pool, sandbox_id).await {
                if matches!(
                    sandbox.status.as_str(),
                    "destroyed" | "stopped" | "stopping"
                ) {
                    continue;
                }
            }

            // Skip bridges with active HITL (requires_action_pending)
            if bridge
                .requires_action_pending
                .load(std::sync::atomic::Ordering::Relaxed)
            {
                continue;
            }

            // Check if bridge has an active task
            let has_task = bridge
                .current_task_id
                .try_lock()
                .map(|guard| guard.is_some())
                .unwrap_or(true);

            if has_task {
                continue;
            }

            // Check container liveness via provider
            if let Ok(Some(sandbox)) = queries::get_sandbox(&self.pool, sandbox_id).await {
                if let Some(ref ext_id) = sandbox.external_id {
                    let is_running = match self.provider.status(ext_id).await {
                        Ok(crate::sandbox::provider::SandboxStatus::Running) => true,
                        _ => false,
                    };

                    if !is_running {
                        warn!(sandbox_id = %sandbox_id, "Bridge health check: container dead, cleaning up");

                        // 1. Remove bridge
                        self.bridge_registry.remove(ext_id);

                        // 2. Destroy container
                        let _ = self.provider.destroy(ext_id).await;

                        // 3. Mark destroyed in DB
                        let _ = queries::destroy_sandbox(&self.pool, sandbox_id).await;

                        // 4. Teardown networking
                        let _ = self.teardown_networking(sandbox_id).await;

                        // 5. Drain and requeue sandbox tasks
                        let reset_count =
                            queries::reset_sandbox_tasks_to_pending(&self.pool, sandbox_id)
                                .await
                                .unwrap_or(0);
                        if reset_count > 0 {
                            info!(sandbox_id = %sandbox_id, count = reset_count, "Reset tasks to pending after health check cleanup");
                            // No task ids are returned on this bulk reset; the
                            // scheduler's DB repair sweep recovers these rows.
                        }
                    }
                }
            }
        }

        Ok(())
    }

    /// Phase 1: Reap sandboxes whose runner is done or unreachable.
    ///
    /// Three independent reap criteria (UNION'd in the SQL):
    ///   1. `idle_since` past `idle_timeout` — the runner explicitly told us
    ///      everything is done (RunnerIdle). For cc/native this is precise
    ///      because the harness holds back the turn-complete signal until
    ///      background sub-agents finish; codex multi-agent aggregates child
    ///      threads in the runtime adapter for the same guarantee.
    ///   2. `disconnected_at` past `bridge_disconnect_grace` — the bridge has
    ///      been gone too long; runner crashed or we can't talk to it. The
    ///      orchestrator stamps `disconnected_at` whenever the gRPC stream
    ///      terminates and clears it on a successful attach.
    ///   3. `created_at` past `hard_timeout` — absolute wall-clock cap on any
    ///      non-terminal sandbox lifetime. Last-resort zombie defence.
    ///
    /// All three return the row's status because the downstream stop logic
    /// only does the graceful idle→stopping→stopped dance when the row is
    /// actually idle; for disconnect/hard-timeout reaps we jump straight to
    /// stopped (no point waiting on a runner we already gave up on).
    async fn sweep_idle_sandboxes(self: &Arc<Self>) -> anyhow::Result<()> {
        let timeout_secs = self.runtime_config.idle_timeout_sec() as i64;
        let disconnect_grace = self.config.sandbox_bridge_disconnect_grace as i64;
        let hard_timeout = self.config.sandbox_hard_timeout as i64;

        let reapable: Vec<(Uuid, Option<String>, String)> = sqlx::query_as(
            r#"
            SELECT id, external_id, status FROM joysafeter_sandboxes
            WHERE destroyed_at IS NULL
              AND status NOT IN ('stopping', 'stopped', 'destroyed', 'pooled')
              AND (
                -- Criterion 1: clean idle past timeout
                (status = 'idle'
                 AND idle_since IS NOT NULL
                 AND idle_since < NOW() - make_interval(secs => $1))
                -- Criterion 2: bridge gone past grace
                OR (disconnected_at IS NOT NULL
                    AND disconnected_at < NOW() - make_interval(secs => $2))
                -- Criterion 3: absolute hard timeout (0 disables)
                OR ($3 > 0 AND created_at < NOW() - make_interval(secs => $3))
              )
            LIMIT 10
            "#,
        )
        .bind(timeout_secs as f64)
        .bind(disconnect_grace as f64)
        .bind(hard_timeout as f64)
        .fetch_all(&self.pool)
        .await?;

        if reapable.is_empty() {
            return Ok(());
        }

        // S9: Process up to 5 sandbox stops concurrently
        let semaphore = Arc::new(Semaphore::new(5));
        let mut join_set = tokio::task::JoinSet::new();

        for (sandbox_id, external_id, current_status) in reapable {
            let this = self.clone();
            let permit = semaphore.clone().acquire_owned().await?;

            join_set.spawn(async move {
                let _permit = permit; // held until this task completes
                this.stop_idle_sandbox(sandbox_id, external_id, current_status)
                    .await;
            });
        }

        // Await all concurrent stop operations
        while let Some(result) = join_set.join_next().await {
            if let Err(e) = result {
                error!("Idle sandbox stop task panicked: {e}");
            }
        }

        Ok(())
    }

    /// Stop a single sandbox flagged by the reaper.
    ///
    /// `current_status` is what the sweeper SQL saw; we use it to decide
    /// whether to walk through the graceful idle→stopping→stopped path
    /// (only valid when the row is actually idle) or to jump straight
    /// to stopped (for disconnect/hard-timeout reaps where we no longer
    /// trust the runner to flush).
    async fn stop_idle_sandbox(
        &self,
        sandbox_id: Uuid,
        external_id: Option<String>,
        current_status: String,
    ) {
        // HA: skip sandboxes owned by another instance (Python L220-225)
        if let Some(ref coord) = self.redis_coordinator {
            if let Ok(Some(owner)) = coord.get_sandbox_owner(sandbox_id).await {
                if owner != self.config.instance_id {
                    return;
                }
            }
        }

        let graceful = current_status == "idle";

        if graceful {
            // CAS: idle -> stopping
            let cas_ok =
                queries::transition_sandbox_cas(&self.pool, sandbox_id, "idle", "stopping")
                    .await
                    .unwrap_or(false);
            if !cas_ok {
                return; // Another instance or process already handling it
            }
            debug!(sandbox_id = %sandbox_id, "Stopping idle sandbox (past timeout)");
        } else {
            debug!(
                sandbox_id = %sandbox_id,
                status = %current_status,
                "Reaping sandbox (disconnect/hard-timeout fallback)"
            );
        }

        // S3: Drain and requeue pending tasks BEFORE the grace sleep
        // to prevent task loss during the 3s window.
        if let Err(e) = self.requeue_scheduling_tasks(sandbox_id).await {
            warn!(sandbox_id = %sandbox_id, "Failed to requeue tasks during stop: {e}");
        }

        // Send shutdown to runner before stop. We still try this on the
        // non-graceful path on the chance the runner is alive enough to
        // hear it — best effort.
        if let Some(ref ext_id) = external_id {
            if let Some(bridge) = self.bridge_registry.get(ext_id) {
                let msg = crate::grpc::proto::OrchestratorMessage {
                    payload: Some(crate::grpc::proto::orchestrator_message::Payload::Shutdown(
                        crate::grpc::proto::Shutdown {
                            reason: if graceful { "idle timeout" } else { "reaped" }.to_string(),
                        },
                    )),
                };
                let _ = bridge.send_to_runner(msg).await;
                // Grace period only on the graceful path; for non-graceful
                // reaps we already gave up on the runner.
                if graceful {
                    tokio::time::sleep(Duration::from_secs(3)).await;
                }
            }
            self.bridge_registry.remove(ext_id);
        }

        // Stop the container
        if let Some(ref ext_id) = external_id {
            if let Err(e) = self.provider.stop(ext_id).await {
                // Check if "no such container" -- mark as stopped anyway
                let err_str = format!("{e}");
                if err_str.contains("No such container") || err_str.contains("not running") {
                    let _ = queries::transition_sandbox(&self.pool, sandbox_id, "stopped").await;
                } else {
                    warn!(sandbox_id = %sandbox_id, "Failed to stop sandbox: {e}");
                    // Only revert to idle on the graceful path; non-graceful
                    // reaps had no reversible state.
                    if graceful {
                        let _ = queries::transition_sandbox(&self.pool, sandbox_id, "idle").await;
                    }
                    return;
                }
            }
        }

        let _ = queries::transition_sandbox(&self.pool, sandbox_id, "stopped").await;
        info!(
            sandbox_id = %sandbox_id,
            graceful = graceful,
            was = %current_status,
            "Stopped sandbox",
        );
    }

    /// Phase 2: Force-stop sandboxes stuck in 'stopping' for > 60s.
    async fn force_stop_stuck(&self) -> anyhow::Result<()> {
        let stuck: Vec<(Uuid, Option<String>)> = sqlx::query_as(
            r#"
            SELECT id, external_id FROM joysafeter_sandboxes
            WHERE status = 'stopping'
              AND destroyed_at IS NULL
              AND updated_at < NOW() - INTERVAL '60 seconds'
            LIMIT 5
            "#,
        )
        .fetch_all(&self.pool)
        .await?;

        for (sandbox_id, external_id) in stuck {
            warn!(sandbox_id = %sandbox_id, "Force-stopping stuck sandbox (>60s in stopping)");
            // Remove bridge (Python L311)
            let mut stop_succeeded = false;
            if let Some(ref ext_id) = external_id {
                self.bridge_registry.remove(ext_id);
                match self.provider.stop(ext_id).await {
                    Ok(_) => stop_succeeded = true,
                    Err(e) => {
                        let err = format!("{e}");
                        if err.contains("No such container") || err.contains("404") {
                            stop_succeeded = true;
                        } else {
                            warn!(sandbox_id = %sandbox_id, "Force stop failed: {e}");
                        }
                    }
                }
            } else {
                stop_succeeded = true;
            }
            if stop_succeeded {
                let _ = queries::transition_sandbox(&self.pool, sandbox_id, "stopped").await;
                // Teardown networking (Python L332)
                let _ = self.teardown_networking(sandbox_id).await;
            }
        }

        Ok(())
    }

    /// Phase 3: Destroy stopped/errored sandboxes past TTL.
    ///
    /// `error` is a terminal-ish state set on failure ejection
    /// (grpc/server.rs execute_sandbox_cleanup) WITHOUT a disconnected_at
    /// marker, so the idle sweep does not reliably reach it. Include it here so
    /// an errored sandbox's container / DB row / Envoy listeners are reclaimed
    /// (error -> destroyed is a valid transition) rather than leaking until the
    /// absolute hard timeout (or forever, when that timeout is disabled).
    async fn sweep_stopped_sandboxes(&self) -> anyhow::Result<()> {
        let ttl_secs = self.runtime_config.stopped_max_age_sec() as i64;

        let stopped: Vec<(Uuid, Option<String>)> = sqlx::query_as(
            r#"
            SELECT id, external_id FROM joysafeter_sandboxes
            WHERE status IN ('stopped', 'error')
              AND destroyed_at IS NULL
              AND last_used_at < NOW() - make_interval(secs => $1)
            LIMIT 10
            "#,
        )
        .bind(ttl_secs as f64)
        .fetch_all(&self.pool)
        .await?;

        for (sandbox_id, external_id) in stopped {
            let mut destroy_ok = false;
            if let Some(ref ext_id) = external_id {
                match self.provider.destroy(ext_id).await {
                    Ok(_) => destroy_ok = true,
                    Err(e) => {
                        let err = format!("{e}");
                        if err.contains("No such container") || err.contains("404") {
                            destroy_ok = true; // container already gone
                        } else {
                            warn!(sandbox_id = %sandbox_id, "Failed to destroy stopped sandbox: {e}");
                        }
                    }
                }
            } else {
                destroy_ok = true; // no container to destroy
            }

            if destroy_ok {
                let _ = self.teardown_networking(sandbox_id).await;
                let _ = queries::destroy_sandbox(&self.pool, sandbox_id).await;
                info!(sandbox_id = %sandbox_id, "Destroyed stopped sandbox (past TTL)");
            }
        }

        Ok(())
    }

    /// Detect sandboxes stuck in provisioning (>180s relative, >300s absolute).
    async fn check_provisioning_timeout(&self) -> anyhow::Result<()> {
        // Query ALL provisioning sandboxes (not just timed out ones)
        let provisioning: Vec<(Uuid, Option<String>)> = sqlx::query_as(
            r#"
            SELECT id, external_id FROM joysafeter_sandboxes
            WHERE status = 'provisioning'
              AND destroyed_at IS NULL
            LIMIT 20
            "#,
        )
        .fetch_all(&self.pool)
        .await?;

        for (sandbox_id, external_id) in provisioning {
            // Bridge fast-path: if bridge already registered, transition to idle (Python L464-473)
            if let Some(ref ext_id) = external_id {
                if self.bridge_registry.get(ext_id).is_some() {
                    let cas_ok = queries::transition_sandbox_cas(
                        &self.pool,
                        sandbox_id,
                        "provisioning",
                        "idle",
                    )
                    .await
                    .unwrap_or(false);
                    if cas_ok {
                        let _ = queries::touch_sandbox(&self.pool, sandbox_id).await;
                        info!(sandbox_id = %sandbox_id, "Provisioning sandbox → idle (bridge registered)");
                    }
                    continue;
                }
            }

            // Check timeouts: 180s relative to last_used_at OR 300s absolute from created_at.
            let timed_out: bool = sqlx::query_scalar(
                r#"
                SELECT COALESCE(last_used_at < NOW() - INTERVAL '180 seconds', true)
                    OR COALESCE(created_at < NOW() - INTERVAL '300 seconds', true)
                FROM joysafeter_sandboxes WHERE id = $1
                "#,
            )
            .bind(sandbox_id)
            .fetch_optional(&self.pool)
            .await?
            .unwrap_or(false);

            if !timed_out {
                if let Some(ref ext_id) = external_id {
                    if let Ok(Some(status)) = self.provider.provisioning_status(ext_id).await {
                        if status
                            .get("error")
                            .and_then(|value| value.as_bool())
                            .unwrap_or(false)
                        {
                            let message = status
                                .get("error_message")
                                .or_else(|| status.get("message"))
                                .and_then(|value| value.as_str())
                                .unwrap_or("provider provisioning failed");
                            warn!(sandbox_id = %sandbox_id, "Sandbox provisioning failed: {message}");
                            let _ = self.provider.stop(ext_id).await;
                            let _ = queries::transition_sandbox(&self.pool, sandbox_id, "stopped")
                                .await;
                            self.requeue_scheduling_tasks(sandbox_id).await?;
                        } else {
                            let config = serde_json::json!({
                                "provisioning": {
                                    "stage": status.get("stage").and_then(|v| v.as_str()).unwrap_or("unknown"),
                                    "progress": status.get("progress").and_then(|v| v.as_i64()).unwrap_or(0),
                                    "message": status.get("message").and_then(|v| v.as_str()).unwrap_or(""),
                                    "complete": status.get("complete").and_then(|v| v.as_bool()).unwrap_or(false),
                                    "error": false,
                                }
                            });
                            let _ = queries::update_sandbox_status_and_config(
                                &self.pool,
                                sandbox_id,
                                "provisioning",
                                &config,
                            )
                            .await;
                        }
                    }
                }
                continue;
            }

            if timed_out {
                warn!(sandbox_id = %sandbox_id, "Sandbox stuck in provisioning, resetting tasks");
                if let Some(ref ext_id) = external_id {
                    let _ = self.provider.stop(ext_id).await;
                }
                let _ = queries::transition_sandbox(&self.pool, sandbox_id, "stopped").await;
                self.requeue_scheduling_tasks(sandbox_id).await?;
            }
        }

        Ok(())
    }

    async fn requeue_scheduling_tasks(&self, sandbox_id: Uuid) -> anyhow::Result<u64> {
        let task_ids =
            queries::find_scheduling_task_ids_for_sandbox(&self.pool, sandbox_id).await?;
        let _ = self.queue.drain(sandbox_id).await;
        let count = queries::reset_sandbox_tasks_to_pending(&self.pool, sandbox_id).await?;
        for task_id in task_ids {
            if let Err(e) = self.queue.push_to_global(task_id).await {
                error!(sandbox_id = %sandbox_id, task_id = %task_id, "Failed to enqueue task after provisioning failure: {e}");
            }
        }
        if count > 0 {
            warn!(sandbox_id = %sandbox_id, count, "Requeued scheduling tasks after provisioning failure");
        }
        Ok(count)
    }

    /// Pool manager: warm pool top-up + stale pool cleanup.
    async fn manage_pool(&self) -> anyhow::Result<()> {
        // #22: HA lock with guaranteed release (Python try/finally L558-568)
        let has_lock = if let Some(ref coord) = self.redis_coordinator {
            let acquired = coord.try_lock("pool_manager", 60).await.unwrap_or(false);
            if !acquired {
                return Ok(());
            }
            true
        } else {
            false
        };

        let result = self.manage_pool_inner().await;

        // Always release lock (Python finally block L567-568)
        if has_lock {
            if let Some(ref coord) = self.redis_coordinator {
                let _ = coord.unlock("pool_manager").await;
            }
        }

        result
    }

    async fn manage_pool_inner(&self) -> anyhow::Result<()> {
        if self.config.envoy_enabled {
            debug!("Skipping warm pool provisioning while default sandbox networking is limited");
            return Ok(());
        }

        // Support multiple pool images (Python L586-606)
        let pool_images = if self.config.sandbox_pool_images.is_empty() {
            vec![self.config.sandbox_image.clone()]
        } else {
            self.config.sandbox_pool_images.clone()
        };

        for image in &pool_images {
            let pool_count: (i64,) = sqlx::query_as(
                "SELECT COUNT(*) FROM joysafeter_sandboxes WHERE status = 'pooled' AND image = $1 AND destroyed_at IS NULL",
            )
            .bind(image)
            .fetch_one(&self.pool)
            .await?;

            let current = pool_count.0 as usize;
            let min_size = self.runtime_config.pool_min_size() as usize;

            if current < min_size {
                let to_create = min_size - current;
                info!(current, min_size, to_create, image = %image, "Pool below minimum, provisioning");

                let resolver = SandboxResolver::new(
                    self.pool.clone(),
                    self.provider.clone(),
                    self.envoy_manager.clone(),
                    self.config.clone(),
                );
                for _ in 0..to_create {
                    match resolver.provision_pool_sandbox(image).await {
                        Ok(sandbox_id) => {
                            info!(sandbox_id = %sandbox_id, image = %image, "Created pooled sandbox")
                        }
                        Err(e) => {
                            error!(image = %image, "Failed to provision pool sandbox: {e}");
                            break;
                        }
                    }
                }
            }
        } // close for image in &pool_images

        // Cleanup stale pool entries (older than max_age)
        let max_age = self.runtime_config.pool_max_age_sec() as i64;
        let stale: Vec<(Uuid, Option<String>)> = sqlx::query_as(
            r#"
            SELECT id, external_id FROM joysafeter_sandboxes
            WHERE status = 'pooled'
              AND destroyed_at IS NULL
              AND created_at < NOW() - make_interval(secs => $1)
            LIMIT 5
            "#,
        )
        .bind(max_age as f64)
        .fetch_all(&self.pool)
        .await?;

        for (sandbox_id, external_id) in stale {
            let mut destroy_ok = false;
            if let Some(ref ext_id) = external_id {
                match self.provider.destroy(ext_id).await {
                    Ok(_) => destroy_ok = true,
                    Err(e) => {
                        let err = format!("{e}");
                        if err.contains("No such container") || err.contains("404") {
                            destroy_ok = true;
                        } else {
                            warn!(sandbox_id = %sandbox_id, "Failed to destroy stale pool sandbox: {e}");
                        }
                    }
                }
            } else {
                destroy_ok = true;
            }
            if destroy_ok {
                let _ = self.teardown_networking(sandbox_id).await;
                let _ = queries::destroy_sandbox(&self.pool, sandbox_id).await;
                debug!(sandbox_id = %sandbox_id, "Destroyed stale pool sandbox");
            }
        }

        Ok(())
    }

    /// Cleanup orphaned provider sandboxes by cross-referencing with DB.
    pub async fn cleanup_orphaned(&self) -> anyhow::Result<usize> {
        let mut cleaned = 0usize;

        for item in self.provider.list_active().await.unwrap_or_default() {
            let external_id = if !item.name.is_empty() {
                item.name.clone()
            } else {
                item.id.clone()
            };
            if external_id.is_empty() {
                continue;
            }

            let mut exists = false;
            if let Some(raw_id) = item.labels.get("joysafeter.sandbox_id") {
                if let Ok(sandbox_id) = Uuid::parse_str(raw_id) {
                    exists = queries::get_sandbox(&self.pool, sandbox_id)
                        .await?
                        .is_some();
                }
            }
            if !exists {
                exists = queries::get_sandbox_by_external_id(&self.pool, &external_id)
                    .await?
                    .is_some();
            }
            if exists {
                continue;
            }
            if is_recent_uncommitted_provider_sandbox(&item.labels, chrono::Utc::now().timestamp())
            {
                debug!(
                    external_id = %external_id,
                    "Skipping recent provider sandbox with no DB row; DB insert may still be in flight"
                );
                continue;
            }

            match self.provider.destroy(&external_id).await {
                Ok(_) => {
                    cleaned += 1;
                    info!(external_id = %external_id, status = %item.status, image = %item.image, "Destroyed orphaned provider sandbox");
                }
                Err(e) => {
                    warn!(external_id = %external_id, "Failed to destroy orphaned provider sandbox: {e}")
                }
            }
        }

        let db_rows: Vec<(Uuid, Option<String>)> = sqlx::query_as(
            r#"
            SELECT id, external_id FROM joysafeter_sandboxes
            WHERE status NOT IN ('destroyed', 'error')
              AND destroyed_at IS NULL
              AND external_id IS NOT NULL
              AND external_id != ''
            "#,
        )
        .fetch_all(&self.pool)
        .await?;

        for (sandbox_id, external_id) in db_rows {
            let Some(ext_id) = external_id else { continue };
            if matches!(
                self.provider.status(&ext_id).await,
                Ok(crate::sandbox::provider::SandboxStatus::NotFound)
            ) {
                let _ = self.teardown_networking(sandbox_id).await;
                let _ = queries::destroy_sandbox(&self.pool, sandbox_id).await;
                cleaned += 1;
                info!(sandbox_id = %sandbox_id, "Cleaned up orphaned DB record (container missing)");
            }
        }

        Ok(cleaned)
    }

    async fn teardown_networking(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        if let Some(ref envoy) = self.envoy_manager {
            envoy.teardown_for_sandbox(sandbox_id).await?;
        }
        Ok(())
    }
}

fn is_recent_uncommitted_provider_sandbox(
    labels: &std::collections::HashMap<String, String>,
    now_unix: i64,
) -> bool {
    labels
        .get("joysafeter.created_at_unix")
        .and_then(|raw| raw.parse::<i64>().ok())
        .map(|created_at| {
            created_at <= now_unix && now_unix - created_at < ORPHAN_PROVIDER_DB_INSERT_GRACE_SECS
        })
        .unwrap_or(false)
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use super::{is_recent_uncommitted_provider_sandbox, ORPHAN_PROVIDER_DB_INSERT_GRACE_SECS};

    #[test]
    fn recent_uncommitted_provider_sandbox_is_protected_from_orphan_cleanup() {
        let now = 1_800_000_000;
        let mut labels = HashMap::new();
        labels.insert(
            "joysafeter.created_at_unix".to_string(),
            (now - ORPHAN_PROVIDER_DB_INSERT_GRACE_SECS + 1).to_string(),
        );

        assert!(is_recent_uncommitted_provider_sandbox(&labels, now));

        labels.insert(
            "joysafeter.created_at_unix".to_string(),
            (now - ORPHAN_PROVIDER_DB_INSERT_GRACE_SECS).to_string(),
        );
        assert!(!is_recent_uncommitted_provider_sandbox(&labels, now));

        labels.clear();
        assert!(!is_recent_uncommitted_provider_sandbox(&labels, now));
    }
}
