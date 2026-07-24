use std::sync::Arc;
use std::time::Duration;

use serde_json::json;
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
        redis_coordinator: Option<Arc<crate::kernel::redis_coordinator::RedisCoordinator>>,
        config: JoySafeterConfig,
        runtime_config: Arc<RuntimeConfig>,
    ) -> Self {
        Self {
            pool,
            queue,
            bridge_registry,
            provider,
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

                        // 1. Repair any DB task/session state while the sandbox
                        // row still exists; DB remains the durable authority.
                        let failure_reason = "sandbox runtime failed bridge health check";
                        if let Err(e) = self
                            .recover_tasks_for_missing_runtime(sandbox_id, failure_reason)
                            .await
                        {
                            error!(sandbox_id = %sandbox_id, error = %e, "Failed to recover tasks after bridge health check cleanup");
                            continue;
                        }

                        // 2. Isolate the sandbox row before the external destroy
                        // side effect. Running-task recovery may have released
                        // the row to `idle`, which is valid only if no active
                        // task remains bound to the sandbox.
                        let restore_status =
                            match queries::claim_sandbox_for_passive_destroy_after_recovery(
                                &self.pool,
                                sandbox_id,
                                &sandbox.status,
                                sandbox.external_id.as_deref(),
                            )
                            .await
                            {
                                Ok(Some(status)) => status,
                                Ok(None) => {
                                    warn!(sandbox_id = %sandbox_id, status = %sandbox.status, "Skipped bridge-health provider destroy because sandbox row changed after recovery");
                                    continue;
                                }
                                Err(e) => {
                                    warn!(sandbox_id = %sandbox_id, status = %sandbox.status, "Failed to claim bridge-health sandbox before provider destroy: {e}");
                                    continue;
                                }
                            };

                        // 3. Remove bridge
                        self.bridge_registry.remove(ext_id);

                        // 4. Destroy container
                        if let Err(e) = self.provider.destroy(ext_id).await {
                            let err = format!("{e}");
                            if !(err.contains("No such container") || err.contains("404")) {
                                let _ = queries::restore_sandbox_after_passive_destroy_failure(
                                    &self.pool,
                                    sandbox_id,
                                    &restore_status,
                                    sandbox.external_id.as_deref(),
                                )
                                .await;
                                error!(sandbox_id = %sandbox_id, error = %err, "Failed to destroy bridge-health sandbox after DB recovery");
                                continue;
                            }
                        }

                        // 5. Teardown networking
                        let _ = self.teardown_networking(sandbox_id).await;

                        // 6. Mark destroyed in DB only if the cleanup still
                        // owns the isolated sandbox row.
                        match queries::destroy_sandbox_if_status_and_external_id(
                            &self.pool,
                            sandbox_id,
                            "stopping",
                            sandbox.external_id.as_deref(),
                        )
                        .await
                        {
                            Ok(true) => {}
                            Ok(false) => {
                                warn!(sandbox_id = %sandbox_id, status = %sandbox.status, "Skipped bridge-health DB destroy because sandbox row changed state");
                            }
                            Err(e) => {
                                warn!(sandbox_id = %sandbox_id, status = %sandbox.status, "Failed to mark bridge-health sandbox destroyed: {e}");
                            }
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
    ///      threads in the runtime adapter for the same guarantee. Before
    ///      stopping, we also ask the in-process bridge for the latest
    ///      runner-side heartbeat and skip the reap when it still reports busy.
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
        let mut cleanup_claimed_stopping = graceful;

        if graceful {
            if let Some(bridge) = self.bridge_registry.get_by_db_id(sandbox_id) {
                if let Some(activity) = bridge.runner_runtime_activity().await {
                    let max_age_secs = (self.runtime_config.heartbeat_timeout_sec() * 2).max(30) as i64;
                    let age_secs = chrono::Utc::now()
                        .signed_duration_since(activity.observed_at)
                        .num_seconds();
                    if activity.runtime_state == "busy" && age_secs <= max_age_secs {
                        debug!(
                            sandbox_id = %sandbox_id,
                            active_task_id = ?activity.active_task_id,
                            session_id = ?activity.session_id,
                            age_secs,
                            "Skipping idle reap because runner heartbeat reports busy runtime"
                        );
                        return;
                    }
                }
            }

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
            // M6 fix: Re-verify disconnected state before non-graceful reap.
            // The sweep query may have identified this sandbox as disconnected,
            // but it could have reconnected between the sweep and now (TOCTOU).
            if let Ok(Some(fresh)) = queries::get_sandbox(&self.pool, sandbox_id).await {
                if fresh.disconnected_at.is_none() && fresh.status == "running" {
                    debug!(
                        sandbox_id = %sandbox_id,
                        "Sandbox reconnected since sweep, skipping non-graceful reap"
                    );
                    return;
                }
            }
            debug!(
                sandbox_id = %sandbox_id,
                status = %current_status,
                "Reaping sandbox (disconnect/hard-timeout fallback)"
            );
        }

        // S3: Repair DB task/session state BEFORE the grace sleep/stop.
        // Graceful idle stops should only have scheduling residues to reset.
        // Non-graceful disconnect/hard-timeout reaps can still have DB-running
        // tasks even when the bridge is gone; repair those before stopping.
        if graceful {
            if let Err(e) = self.requeue_scheduling_tasks(sandbox_id).await {
                warn!(sandbox_id = %sandbox_id, "Failed to requeue tasks during stop: {e}");
            }
        } else {
            let failure_reason = "sandbox runtime reaped after disconnect or hard timeout";
            if let Err(e) = self
                .recover_tasks_for_missing_runtime(sandbox_id, failure_reason)
                .await
            {
                warn!(sandbox_id = %sandbox_id, "Failed to recover tasks during non-graceful reap: {e}");
                return;
            }
            if current_status != "error" {
                match queries::claim_sandbox_for_passive_stop_after_recovery(
                    &self.pool,
                    sandbox_id,
                    &current_status,
                    external_id.as_deref(),
                )
                .await
                {
                    Ok(Some(previous_status)) => {
                        cleanup_claimed_stopping = true;
                        debug!(
                            sandbox_id = %sandbox_id,
                            previous_status = %previous_status,
                            "Claimed recovered sandbox for non-graceful stop"
                        );
                    }
                    Ok(None) => {
                        debug!(
                            sandbox_id = %sandbox_id,
                            status = %current_status,
                            "Skipping non-graceful provider stop because sandbox row changed or still has active tasks"
                        );
                        return;
                    }
                    Err(e) => {
                        warn!(sandbox_id = %sandbox_id, "Failed to claim recovered sandbox before provider stop: {e}");
                        return;
                    }
                }
            }
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
                    if cleanup_claimed_stopping {
                        let _ = queries::mark_sandbox_stopped_if_status_and_external_id(
                            &self.pool,
                            sandbox_id,
                            "stopping",
                            external_id.as_deref(),
                        )
                        .await;
                    } else {
                        let _ =
                            queries::mark_sandbox_stopped_if_active(&self.pool, sandbox_id).await;
                    }
                } else {
                    warn!(sandbox_id = %sandbox_id, "Failed to stop sandbox: {e}");
                    // Only revert to idle on the graceful path; non-graceful
                    // claims stay in stopping so force_stop_stuck can retry.
                    if graceful {
                        let _ = queries::transition_sandbox_cas(
                            &self.pool, sandbox_id, "stopping", "idle",
                        )
                        .await;
                    }
                    return;
                }
            }
        }

        if cleanup_claimed_stopping {
            let _ = queries::mark_sandbox_stopped_if_status_and_external_id(
                &self.pool,
                sandbox_id,
                "stopping",
                external_id.as_deref(),
            )
            .await;
        } else {
            let _ = queries::mark_sandbox_stopped_if_active(&self.pool, sandbox_id).await;
        }
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
            let failure_reason = "sandbox force-stopped after stuck stopping state";
            if let Err(e) = self
                .recover_tasks_for_missing_runtime(sandbox_id, failure_reason)
                .await
            {
                warn!(sandbox_id = %sandbox_id, "Failed to recover tasks before force-stop: {e}");
                continue;
            }

            let claimed = queries::claim_stopping_sandbox_for_force_stop(
                &self.pool,
                sandbox_id,
                external_id.as_deref(),
            )
            .await
            .unwrap_or(false);
            if !claimed {
                debug!(
                    sandbox_id = %sandbox_id,
                    "Skipping force-stop because sandbox row changed or still has active tasks"
                );
                continue;
            }

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
                let _ = queries::mark_sandbox_stopped_if_status_and_external_id(
                    &self.pool,
                    sandbox_id,
                    "stopping",
                    external_id.as_deref(),
                )
                .await;
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

        let stopped: Vec<(Uuid, Option<String>, String)> = sqlx::query_as(
            r#"
            SELECT id, external_id, status FROM joysafeter_sandboxes
            WHERE status IN ('stopped', 'error')
              AND destroyed_at IS NULL
              AND last_used_at < NOW() - make_interval(secs => $1)
            LIMIT 10
            "#,
        )
        .bind(ttl_secs as f64)
        .fetch_all(&self.pool)
        .await?;

        for (sandbox_id, external_id, observed_status) in stopped {
            match self
                .destroy_observed_sandbox(
                    sandbox_id,
                    &observed_status,
                    external_id.as_deref(),
                    "stopped/error TTL",
                )
                .await
            {
                Ok(true) => {
                    info!(sandbox_id = %sandbox_id, status = %observed_status, "Destroyed stopped/error sandbox (past TTL)");
                }
                Ok(false) => {}
                Err(e) => {
                    warn!(sandbox_id = %sandbox_id, status = %observed_status, "Failed stopped/error TTL sandbox destroy: {e}");
                }
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
                            if !self
                                .stop_provisioning_sandbox(sandbox_id, Some(ext_id))
                                .await?
                            {
                                debug!(
                                    sandbox_id = %sandbox_id,
                                    "Skipping provisioning failure cleanup because sandbox left provisioning"
                                );
                            }
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
                if !self
                    .stop_provisioning_sandbox(sandbox_id, external_id.as_deref())
                    .await?
                {
                    debug!(
                        sandbox_id = %sandbox_id,
                        "Skipping provisioning timeout cleanup because sandbox left provisioning"
                    );
                }
            }
        }

        Ok(())
    }

    async fn stop_provisioning_sandbox(
        &self,
        sandbox_id: Uuid,
        external_id: Option<&str>,
    ) -> anyhow::Result<bool> {
        let claimed =
            queries::transition_sandbox_cas(&self.pool, sandbox_id, "provisioning", "stopping")
                .await
                .unwrap_or(false);
        if !claimed {
            return Ok(false);
        }

        self.requeue_scheduling_tasks(sandbox_id).await?;

        let mut stop_succeeded = external_id.is_none();
        if let Some(ext_id) = external_id {
            match self.provider.stop(ext_id).await {
                Ok(_) => stop_succeeded = true,
                Err(e) => {
                    let err = format!("{e}");
                    if err.contains("No such container")
                        || err.contains("not running")
                        || err.contains("404")
                    {
                        stop_succeeded = true;
                    } else {
                        warn!(sandbox_id = %sandbox_id, "Failed to stop provisioning sandbox: {e}");
                    }
                }
            }
        }

        if stop_succeeded {
            let _ = queries::mark_sandbox_stopped_if_status_and_external_id(
                &self.pool,
                sandbox_id,
                "stopping",
                external_id,
            )
            .await?;
        }

        Ok(stop_succeeded)
    }

    async fn requeue_scheduling_tasks(&self, sandbox_id: Uuid) -> anyhow::Result<u64> {
        let _ = self.queue.drain(sandbox_id).await;
        let failure_reason = "sandbox provisioning failed after retry limit";
        let failed_tasks =
            queries::fail_exhausted_sandbox_tasks_returning(&self.pool, sandbox_id, failure_reason)
                .await?;
        mark_failed_tasks_idle(&self.pool, &failed_tasks, failure_reason).await;

        let reset_tasks =
            queries::reset_sandbox_tasks_to_pending_returning(&self.pool, sandbox_id).await?;
        for task in &reset_tasks {
            if let Err(e) = self.queue.push_to_global(task.id).await {
                error!(sandbox_id = %sandbox_id, task_id = %task.id, "Failed to enqueue task after provisioning failure: {e}");
            }
        }
        let count = reset_tasks.len() as u64;
        if count > 0 {
            warn!(sandbox_id = %sandbox_id, count, "Requeued scheduling tasks after provisioning failure");
            mark_reset_tasks_rescheduling(&self.pool, &reset_tasks).await;
        }
        Ok(count)
    }

    async fn recover_tasks_for_missing_runtime(
        &self,
        sandbox_id: Uuid,
        failure_reason: &str,
    ) -> anyhow::Result<()> {
        let _ = self.queue.drain(sandbox_id).await;

        let failed_scheduling =
            queries::fail_exhausted_sandbox_tasks_returning(&self.pool, sandbox_id, failure_reason)
                .await?;
        mark_failed_tasks_idle(&self.pool, &failed_scheduling, failure_reason).await;

        let reset_scheduling =
            queries::reset_sandbox_tasks_to_pending_returning(&self.pool, sandbox_id).await?;
        for task in &reset_scheduling {
            notify_global_task_best_effort(self.queue.clone(), sandbox_id, task.id);
        }
        if !reset_scheduling.is_empty() {
            mark_reset_tasks_rescheduling(&self.pool, &reset_scheduling).await;
        }

        let running_tasks = queries::find_running_tasks_for_sandbox(&self.pool, sandbox_id).await?;
        let mut reset_running = Vec::new();
        let mut failed_running = Vec::new();
        for task in running_tasks {
            if task.retry_count < task.max_retries {
                match queries::increment_running_retry(
                    &self.pool,
                    task.id,
                    task.retry_count,
                    task.owner_epoch,
                )
                .await
                {
                    Ok(true) => {
                        notify_global_task_best_effort(self.queue.clone(), sandbox_id, task.id);
                        reset_running.push(queries::ResetSandboxTask {
                            id: task.id,
                            session_id: task.session_id,
                            previous_retry_count: task.retry_count,
                        });
                    }
                    Ok(false) => {
                        warn!(sandbox_id = %sandbox_id, task_id = %task.id, "Missing runtime cleanup skipped running-task retry because task changed");
                    }
                    Err(e) => {
                        error!(sandbox_id = %sandbox_id, task_id = %task.id, "Failed to retry running task after missing runtime cleanup: {e}");
                    }
                }
            } else {
                match queries::fail_running_task_for_sandbox(
                    &self.pool,
                    task.id,
                    sandbox_id,
                    task.retry_count,
                    task.owner_epoch,
                    failure_reason,
                )
                .await
                {
                    Ok(true) => failed_running.push(queries::FailedSandboxTask {
                        id: task.id,
                        session_id: task.session_id,
                    }),
                    Ok(false) => {
                        warn!(sandbox_id = %sandbox_id, task_id = %task.id, "Missing runtime cleanup skipped running-task failure because task changed");
                    }
                    Err(e) => {
                        error!(sandbox_id = %sandbox_id, task_id = %task.id, "Failed to mark running task failed after missing runtime cleanup: {e}");
                    }
                }
            }
        }
        if !reset_running.is_empty() || !failed_running.is_empty() {
            queries::complete_sandbox_task(&self.pool, sandbox_id).await?;
        }
        if !reset_running.is_empty() {
            mark_reset_tasks_rescheduling(&self.pool, &reset_running).await;
        }
        if !failed_running.is_empty() {
            mark_failed_tasks_idle(&self.pool, &failed_running, failure_reason).await;
        }

        Ok(())
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
        if self.provider.capabilities().has_egress_management {
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
        let stale: Vec<(Uuid, Option<String>, String)> = sqlx::query_as(
            r#"
            SELECT id, external_id, status FROM joysafeter_sandboxes
            WHERE status = 'pooled'
              AND destroyed_at IS NULL
              AND created_at < NOW() - make_interval(secs => $1)
            LIMIT 5
            "#,
        )
        .bind(max_age as f64)
        .fetch_all(&self.pool)
        .await?;

        for (sandbox_id, external_id, observed_status) in stale {
            match self
                .destroy_observed_sandbox(
                    sandbox_id,
                    &observed_status,
                    external_id.as_deref(),
                    "stale pool",
                )
                .await
            {
                Ok(true) => {
                    debug!(sandbox_id = %sandbox_id, "Destroyed stale pool sandbox");
                }
                Ok(false) => {}
                Err(e) => {
                    warn!(sandbox_id = %sandbox_id, "Failed stale pool sandbox destroy: {e}");
                }
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
                    exists = sqlx::query_scalar::<_, bool>(
                        r#"
                        SELECT EXISTS(
                            SELECT 1 FROM joysafeter_sandboxes
                            WHERE id = $1
                              AND destroyed_at IS NULL
                              AND status NOT IN ('destroyed', 'error')
                        )
                        "#,
                    )
                    .bind(sandbox_id)
                    .fetch_one(&self.pool)
                    .await?;
                }
            }
            if !exists {
                exists = sqlx::query_scalar::<_, bool>(
                    r#"
                    SELECT EXISTS(
                        SELECT 1 FROM joysafeter_sandboxes
                        WHERE external_id = $1
                          AND destroyed_at IS NULL
                          AND status NOT IN ('destroyed', 'error')
                    )
                    "#,
                )
                .bind(&external_id)
                .fetch_one(&self.pool)
                .await?;
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

        let db_rows: Vec<(Uuid, Option<String>, String)> = sqlx::query_as(
            r#"
            SELECT id, external_id, status FROM joysafeter_sandboxes
            WHERE status NOT IN ('destroyed', 'error')
              AND destroyed_at IS NULL
              AND external_id IS NOT NULL
              AND external_id != ''
            "#,
        )
        .fetch_all(&self.pool)
        .await?;

        for (sandbox_id, external_id, observed_status) in db_rows {
            let Some(ext_id) = external_id else { continue };
            if matches!(
                self.provider.status(&ext_id).await,
                Ok(crate::sandbox::provider::SandboxStatus::NotFound)
            ) {
                let failure_reason = "sandbox provider runtime missing";
                if let Err(e) = self
                    .recover_tasks_for_missing_runtime(sandbox_id, failure_reason)
                    .await
                {
                    error!(sandbox_id = %sandbox_id, error = %e, "Failed to recover tasks for missing sandbox runtime");
                    continue;
                }
                match queries::destroy_sandbox_after_passive_recovery(
                    &self.pool,
                    sandbox_id,
                    &observed_status,
                    Some(&ext_id),
                )
                .await
                {
                    Ok(true) => {
                        let _ = self.teardown_networking(sandbox_id).await;
                        cleaned += 1;
                        info!(sandbox_id = %sandbox_id, status = %observed_status, "Cleaned up orphaned DB record (container missing)");
                    }
                    Ok(false) => {
                        warn!(sandbox_id = %sandbox_id, status = %observed_status, "Skipped missing-runtime DB destroy because sandbox row changed state");
                    }
                    Err(e) => {
                        warn!(sandbox_id = %sandbox_id, status = %observed_status, "Failed to mark missing-runtime sandbox destroyed: {e}");
                    }
                }
            }
        }

        Ok(cleaned)
    }

    async fn teardown_networking(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        self.provider.teardown_networking(sandbox_id).await
    }

    async fn destroy_observed_sandbox(
        &self,
        sandbox_id: Uuid,
        observed_status: &str,
        external_id: Option<&str>,
        reason: &str,
    ) -> anyhow::Result<bool> {
        crate::kernel::sandbox_lifecycle::destroy_observed_sandbox(
            &self.pool,
            &self.provider,
            sandbox_id,
            observed_status,
            external_id,
            reason,
        )
        .await
    }
}

fn notify_global_task_best_effort(queue: TaskQueue, sandbox_id: Uuid, task_id: Uuid) {
    tokio::spawn(async move {
        if let Err(e) = queue.push_to_global(task_id).await {
            error!(sandbox_id = %sandbox_id, task_id = %task_id, "Failed to enqueue task after missing runtime cleanup: {e}");
        }
    });
}

async fn mark_failed_tasks_idle(pool: &PgPool, tasks: &[queries::FailedSandboxTask], reason: &str) {
    for task in tasks {
        let Some(session_id) = task.session_id else {
            continue;
        };
        let stop_reason = json!({"type": "error", "message": reason});
        let payload = json!({
            "task_id": task.id.to_string(),
            "stop_reason": stop_reason.clone()
        });
        if let Err(e) = queries::update_session_status_if_no_active_tasks_and_insert_event(
            pool,
            session_id,
            "idle",
            Some(&stop_reason),
            "session.status_idle",
            &payload,
        )
        .await
        {
            error!(
                task_id = %task.id,
                session_id = %session_id,
                error = %e,
                "Failed to persist exhausted sandbox task session idle status"
            );
        }
    }
}

async fn mark_reset_tasks_rescheduling(pool: &PgPool, tasks: &[queries::ResetSandboxTask]) {
    for task in tasks {
        let Some(session_id) = task.session_id else {
            continue;
        };
        let stop_reason = json!({"type": "sandbox_failed"});
        let payload = json!({
            "task_id": task.id.to_string(),
            "stop_reason": stop_reason.clone()
        });
        if let Err(e) = queries::update_session_status_and_insert_event(
            pool,
            session_id,
            "rescheduling",
            Some(&stop_reason),
            "session.status_rescheduling",
            &payload,
        )
        .await
        {
            error!(
                task_id = %task.id,
                session_id = %session_id,
                error = %e,
                "Failed to persist sandbox reset session rescheduling status"
            );
        }
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
    use std::env;
    use std::sync::Arc;

    use async_trait::async_trait;
    use serde_json::{json, Value};
    use sqlx::postgres::PgPoolOptions;

    use super::*;

    fn database_url() -> Option<String> {
        env::var("DATABASE_URL")
            .ok()
            .or_else(|| env::var("JOYSAFETER_TEST_DATABASE_URL").ok())
            .map(|url| url.replace("postgresql+asyncpg://", "postgres://"))
    }

    async fn test_pool() -> Option<PgPool> {
        let Some(url) = database_url() else {
            eprintln!("skipping real Postgres sandbox controller test: DATABASE_URL is not set");
            return None;
        };
        Some(
            PgPoolOptions::new()
                .max_connections(3)
                .connect(&url)
                .await
                .expect("connect to migrated Postgres test database"),
        )
    }

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

    struct StopMarksErrorProvider {
        pool: PgPool,
        sandbox_id: Uuid,
    }

    #[async_trait]
    impl SandboxProvider for StopMarksErrorProvider {
        async fn create(
            &self,
            config: &crate::sandbox::provider::SandboxCreateConfig,
        ) -> anyhow::Result<String> {
            Ok(format!("unused-{}", config.sandbox_id))
        }

        async fn start(&self, _external_id: &str) -> anyhow::Result<()> {
            Ok(())
        }

        async fn stop(&self, _external_id: &str) -> anyhow::Result<()> {
            queries::mark_sandbox_error(
                &self.pool,
                self.sandbox_id,
                Some("concurrent stop failure"),
            )
            .await?;
            anyhow::bail!("provider stop failed")
        }

        async fn destroy(&self, _external_id: &str) -> anyhow::Result<()> {
            Ok(())
        }

        async fn status(
            &self,
            _external_id: &str,
        ) -> anyhow::Result<crate::sandbox::provider::SandboxStatus> {
            Ok(crate::sandbox::provider::SandboxStatus::Running)
        }

        async fn exec(&self, _external_id: &str, _cmd: &[&str]) -> anyhow::Result<String> {
            Ok(String::new())
        }

        fn provider_name(&self) -> &'static str {
            "stop-marks-error"
        }
    }

    struct StopClaimsTaskProvider {
        pool: PgPool,
        sandbox_id: Uuid,
        external_id: String,
        observed_statuses: tokio::sync::Mutex<Vec<String>>,
    }

    #[async_trait]
    impl SandboxProvider for StopClaimsTaskProvider {
        async fn create(
            &self,
            config: &crate::sandbox::provider::SandboxCreateConfig,
        ) -> anyhow::Result<String> {
            Ok(format!("unused-{}", config.sandbox_id))
        }

        async fn start(&self, _external_id: &str) -> anyhow::Result<()> {
            Ok(())
        }

        async fn stop(&self, external_id: &str) -> anyhow::Result<()> {
            if external_id == self.external_id {
                if let Some(sandbox) = queries::get_sandbox(&self.pool, self.sandbox_id).await? {
                    self.observed_statuses
                        .lock()
                        .await
                        .push(sandbox.status.clone());
                    if sandbox.status == "provisioning" {
                        if let Some(task) = queries::claim_next_sandbox_task(
                            &self.pool,
                            self.sandbox_id,
                            "test-instance",
                            45,
                        )
                        .await?
                        {
                            let _ =
                                queries::start_sandbox_task(&self.pool, self.sandbox_id, task.id)
                                    .await?;
                        }
                    }
                }
            }
            Ok(())
        }

        async fn destroy(&self, _external_id: &str) -> anyhow::Result<()> {
            Ok(())
        }

        async fn status(
            &self,
            _external_id: &str,
        ) -> anyhow::Result<crate::sandbox::provider::SandboxStatus> {
            Ok(crate::sandbox::provider::SandboxStatus::Running)
        }

        async fn exec(&self, _external_id: &str, _cmd: &[&str]) -> anyhow::Result<String> {
            Ok(String::new())
        }

        fn provider_name(&self) -> &'static str {
            "stop-claims-task"
        }
    }

    struct CleanupRecordingProvider {
        active: Vec<crate::sandbox::provider::ProviderSandboxInfo>,
        statuses: HashMap<String, crate::sandbox::provider::SandboxStatus>,
        destroyed: tokio::sync::Mutex<Vec<String>>,
    }

    struct DestroyObservesDbStateProvider {
        pool: PgPool,
        sandbox_id: Uuid,
        task_id: Uuid,
        external_id: String,
        observed_states: tokio::sync::Mutex<Vec<(String, String, Option<Uuid>)>>,
        destroyed: tokio::sync::Mutex<Vec<String>>,
    }

    struct StopObservesDbStateProvider {
        pool: PgPool,
        sandbox_id: Uuid,
        task_id: Uuid,
        external_id: String,
        observed_states: tokio::sync::Mutex<Vec<(String, String, Option<Uuid>)>>,
        stopped: tokio::sync::Mutex<Vec<String>>,
    }

    struct DestroyTransitionsSandboxProvider {
        pool: PgPool,
        sandbox_id: Uuid,
        external_id: String,
        observed_statuses: tokio::sync::Mutex<Vec<String>>,
        destroyed: tokio::sync::Mutex<Vec<String>>,
    }

    #[async_trait]
    impl SandboxProvider for DestroyTransitionsSandboxProvider {
        async fn create(
            &self,
            config: &crate::sandbox::provider::SandboxCreateConfig,
        ) -> anyhow::Result<String> {
            Ok(format!("unused-{}", config.sandbox_id))
        }

        async fn start(&self, _external_id: &str) -> anyhow::Result<()> {
            Ok(())
        }

        async fn stop(&self, _external_id: &str) -> anyhow::Result<()> {
            Ok(())
        }

        async fn destroy(&self, external_id: &str) -> anyhow::Result<()> {
            self.destroyed.lock().await.push(external_id.to_string());
            if external_id == self.external_id {
                if let Some(status) = sqlx::query_scalar::<_, String>(
                    "SELECT status FROM joysafeter_sandboxes WHERE id = $1",
                )
                .bind(self.sandbox_id)
                .fetch_optional(&self.pool)
                .await?
                {
                    self.observed_statuses.lock().await.push(status);
                }
                let _ = queries::transition_sandbox_cas(
                    &self.pool,
                    self.sandbox_id,
                    "stopped",
                    "provisioning",
                )
                .await?;
            }
            Ok(())
        }

        async fn status(
            &self,
            _external_id: &str,
        ) -> anyhow::Result<crate::sandbox::provider::SandboxStatus> {
            Ok(crate::sandbox::provider::SandboxStatus::Running)
        }

        async fn exec(&self, _external_id: &str, _cmd: &[&str]) -> anyhow::Result<String> {
            Ok(String::new())
        }

        fn provider_name(&self) -> &'static str {
            "destroy-transitions-sandbox"
        }
    }

    #[async_trait]
    impl SandboxProvider for StopObservesDbStateProvider {
        async fn create(
            &self,
            config: &crate::sandbox::provider::SandboxCreateConfig,
        ) -> anyhow::Result<String> {
            Ok(format!("unused-{}", config.sandbox_id))
        }

        async fn start(&self, _external_id: &str) -> anyhow::Result<()> {
            Ok(())
        }

        async fn stop(&self, external_id: &str) -> anyhow::Result<()> {
            self.stopped.lock().await.push(external_id.to_string());
            if external_id == self.external_id {
                let observed: (String, String, Option<Uuid>) = sqlx::query_as(
                    r#"
                    SELECT s.status, t.status, t.sandbox_id
                    FROM joysafeter_sandboxes s
                    JOIN joysafeter_tasks t ON t.id = $2
                    WHERE s.id = $1
                    "#,
                )
                .bind(self.sandbox_id)
                .bind(self.task_id)
                .fetch_one(&self.pool)
                .await?;
                self.observed_states.lock().await.push(observed);
            }
            Ok(())
        }

        async fn destroy(&self, _external_id: &str) -> anyhow::Result<()> {
            Ok(())
        }

        async fn status(
            &self,
            _external_id: &str,
        ) -> anyhow::Result<crate::sandbox::provider::SandboxStatus> {
            Ok(crate::sandbox::provider::SandboxStatus::Running)
        }

        async fn exec(&self, _external_id: &str, _cmd: &[&str]) -> anyhow::Result<String> {
            Ok(String::new())
        }

        fn provider_name(&self) -> &'static str {
            "stop-observes-db-state"
        }
    }

    #[async_trait]
    impl SandboxProvider for DestroyObservesDbStateProvider {
        async fn create(
            &self,
            config: &crate::sandbox::provider::SandboxCreateConfig,
        ) -> anyhow::Result<String> {
            Ok(format!("unused-{}", config.sandbox_id))
        }

        async fn start(&self, _external_id: &str) -> anyhow::Result<()> {
            Ok(())
        }

        async fn stop(&self, _external_id: &str) -> anyhow::Result<()> {
            Ok(())
        }

        async fn destroy(&self, external_id: &str) -> anyhow::Result<()> {
            self.destroyed.lock().await.push(external_id.to_string());
            if external_id == self.external_id {
                let observed: (String, String, Option<Uuid>) = sqlx::query_as(
                    r#"
                    SELECT s.status, t.status, t.sandbox_id
                    FROM joysafeter_sandboxes s
                    JOIN joysafeter_tasks t ON t.id = $2
                    WHERE s.id = $1
                    "#,
                )
                .bind(self.sandbox_id)
                .bind(self.task_id)
                .fetch_one(&self.pool)
                .await?;
                self.observed_states.lock().await.push(observed);
            }
            Ok(())
        }

        async fn status(
            &self,
            _external_id: &str,
        ) -> anyhow::Result<crate::sandbox::provider::SandboxStatus> {
            Ok(crate::sandbox::provider::SandboxStatus::NotFound)
        }

        async fn exec(&self, _external_id: &str, _cmd: &[&str]) -> anyhow::Result<String> {
            Ok(String::new())
        }

        async fn list_active(
            &self,
        ) -> anyhow::Result<Vec<crate::sandbox::provider::ProviderSandboxInfo>> {
            Ok(Vec::new())
        }

        fn provider_name(&self) -> &'static str {
            "destroy-observes-db-state"
        }
    }

    #[async_trait]
    impl SandboxProvider for CleanupRecordingProvider {
        async fn create(
            &self,
            config: &crate::sandbox::provider::SandboxCreateConfig,
        ) -> anyhow::Result<String> {
            Ok(format!("unused-{}", config.sandbox_id))
        }

        async fn start(&self, _external_id: &str) -> anyhow::Result<()> {
            Ok(())
        }

        async fn stop(&self, _external_id: &str) -> anyhow::Result<()> {
            Ok(())
        }

        async fn destroy(&self, external_id: &str) -> anyhow::Result<()> {
            self.destroyed.lock().await.push(external_id.to_string());
            Ok(())
        }

        async fn status(
            &self,
            external_id: &str,
        ) -> anyhow::Result<crate::sandbox::provider::SandboxStatus> {
            Ok(self
                .statuses
                .get(external_id)
                .cloned()
                .unwrap_or(crate::sandbox::provider::SandboxStatus::Running))
        }

        async fn exec(&self, _external_id: &str, _cmd: &[&str]) -> anyhow::Result<String> {
            Ok(String::new())
        }

        async fn list_active(
            &self,
        ) -> anyhow::Result<Vec<crate::sandbox::provider::ProviderSandboxInfo>> {
            Ok(self.active.clone())
        }

        fn provider_name(&self) -> &'static str {
            "cleanup-recording"
        }
    }

    fn provider_sandbox_info(
        sandbox_id: Uuid,
        external_id: &str,
    ) -> crate::sandbox::provider::ProviderSandboxInfo {
        let mut labels = HashMap::new();
        labels.insert("joysafeter.sandbox_id".to_string(), sandbox_id.to_string());
        crate::sandbox::provider::ProviderSandboxInfo {
            id: external_id.to_string(),
            name: external_id.to_string(),
            status: "running".to_string(),
            image: "joysafeter/test:latest".to_string(),
            labels,
        }
    }

    #[tokio::test]
    async fn sweep_stopped_sandboxes_isolates_row_before_provider_destroy() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let sandbox_id = Uuid::now_v7();
        let external_id = format!("stopped-sweep-race-{sandbox_id}");

        async {
            queries::create_sandbox(
                &pool,
                sandbox_id,
                &external_id,
                "test",
                "joysafeter/test:latest",
                None,
                None,
                None,
                Some(&json!({})),
            )
            .await
            .expect("create stopped sweep race sandbox");
            queries::transition_sandbox(&pool, sandbox_id, "stopped")
                .await
                .expect("mark sandbox stopped before sweep race");
            sqlx::query(
                "UPDATE joysafeter_sandboxes SET last_used_at = NOW() - INTERVAL '30 days' WHERE id = $1",
            )
            .bind(sandbox_id)
            .execute(&pool)
            .await
            .expect("age stopped sandbox for sweep");

            let provider = Arc::new(DestroyTransitionsSandboxProvider {
                pool: pool.clone(),
                sandbox_id,
                external_id: external_id.clone(),
                observed_statuses: tokio::sync::Mutex::new(Vec::new()),
                destroyed: tokio::sync::Mutex::new(Vec::new()),
            });
            let redis_client =
                redis::Client::open("redis://127.0.0.1:1/").expect("build unreachable redis client");
            let queue = TaskQueue::new(redis_client);
            let bridge_registry = BridgeRegistry::new();
            let config = JoySafeterConfig::from_env();
            let runtime_config = Arc::new(RuntimeConfig::from_config(&config));
            let controller = SandboxController::new(
                pool.clone(),
                queue,
                bridge_registry,
                provider.clone(),
                None,
                config,
                runtime_config,
            );

            controller
                .sweep_stopped_sandboxes()
                .await
                .expect("sweep stopped sandboxes");

            assert_eq!(
                provider.destroyed.lock().await.as_slice(),
                &[external_id.clone()]
            );
            assert_eq!(
                provider.observed_statuses.lock().await.as_slice(),
                &["stopping".to_string()]
            );

            let sandbox: (String, bool) = sqlx::query_as(
                "SELECT status, destroyed_at IS NOT NULL FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load stopped sweep race sandbox");
            assert_eq!(sandbox.0, "destroyed");
            assert!(sandbox.1);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
    }

    #[tokio::test]
    async fn cleanup_orphaned_destroys_provider_runtime_for_destroyed_or_error_db_rows() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let destroyed_sandbox_id = Uuid::now_v7();
        let error_sandbox_id = Uuid::now_v7();
        let destroyed_external_id = format!("cleanup-destroyed-{destroyed_sandbox_id}");
        let error_external_id = format!("cleanup-error-{error_sandbox_id}");

        async {
            queries::create_sandbox(
                &pool,
                destroyed_sandbox_id,
                &destroyed_external_id,
                "test",
                "joysafeter/test:latest",
                None,
                None,
                None,
                Some(&json!({})),
            )
            .await
            .expect("create destroyed-row sandbox");
            queries::destroy_sandbox(&pool, destroyed_sandbox_id)
                .await
                .expect("mark sandbox destroyed");

            queries::create_sandbox(
                &pool,
                error_sandbox_id,
                &error_external_id,
                "test",
                "joysafeter/test:latest",
                None,
                None,
                None,
                Some(&json!({})),
            )
            .await
            .expect("create error-row sandbox");
            queries::mark_sandbox_error(&pool, error_sandbox_id, Some("setup failed"))
                .await
                .expect("mark sandbox error");

            let provider = Arc::new(CleanupRecordingProvider {
                active: vec![
                    provider_sandbox_info(destroyed_sandbox_id, &destroyed_external_id),
                    provider_sandbox_info(error_sandbox_id, &error_external_id),
                ],
                statuses: HashMap::new(),
                destroyed: tokio::sync::Mutex::new(Vec::new()),
            });
            let redis_client =
                redis::Client::open("redis://127.0.0.1:6379").expect("build redis client");
            let queue = TaskQueue::new(redis_client);
            let bridge_registry = BridgeRegistry::new();
            let config = JoySafeterConfig::from_env();
            let runtime_config = Arc::new(RuntimeConfig::from_config(&config));
            let controller = SandboxController::new(
                pool.clone(),
                queue,
                bridge_registry,
                provider.clone(),
                None,
                config,
                runtime_config,
            );

            let cleaned = controller
                .cleanup_orphaned()
                .await
                .expect("cleanup orphaned provider runtimes");
            assert_eq!(cleaned, 2);

            let mut destroyed = provider.destroyed.lock().await.clone();
            destroyed.sort();
            let mut expected = vec![destroyed_external_id.clone(), error_external_id.clone()];
            expected.sort();
            assert_eq!(destroyed, expected);

            let rows: Vec<(Uuid, String)> = sqlx::query_as(
                r#"
                SELECT id, status FROM joysafeter_sandboxes
                WHERE id IN ($1, $2)
                ORDER BY id
                "#,
            )
            .bind(destroyed_sandbox_id)
            .bind(error_sandbox_id)
            .fetch_all(&pool)
            .await
            .expect("load cleanup DB rows");
            assert_eq!(rows.len(), 2);
            assert!(rows
                .iter()
                .any(|(id, status)| *id == destroyed_sandbox_id && status == "destroyed"));
            assert!(rows
                .iter()
                .any(|(id, status)| *id == error_sandbox_id && status == "error"));
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id IN ($1, $2)")
            .bind(destroyed_sandbox_id)
            .bind(error_sandbox_id)
            .execute(&pool)
            .await;
    }

    #[tokio::test]
    async fn cleanup_orphaned_missing_runtime_recovers_scheduling_task_before_destroy() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = Uuid::now_v7();
        let session_id = Uuid::now_v7();
        let task_id = Uuid::now_v7();
        let sandbox_id = Uuid::now_v7();
        let external_id = format!("missing-runtime-{sandbox_id}");
        let unique = agent_id.simple().to_string();

        async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (
                    id, name, engine_kind, model, system_prompt, env, mcp_configs,
                    skills, tools, agents, commands, permission_mode, metadata,
                    multiagent, version
                )
                VALUES (
                    $1, $2, 'claude', $3, 'missing runtime system', '{}'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    'bypassPermissions', '{}'::jsonb, NULL, 1
                )
                "#,
            )
            .bind(agent_id)
            .bind(format!("missing-runtime-agent-{unique}"))
            .bind(json!({"id": "missing-runtime-model"}))
            .execute(&pool)
            .await
            .expect("insert missing runtime agent");

            queries::create_session(&pool, session_id, Some(agent_id), None, None, None)
                .await
                .expect("create missing runtime session");
            sqlx::query("UPDATE joysafeter_sessions SET status = 'running' WHERE id = $1")
                .bind(session_id)
                .execute(&pool)
                .await
                .expect("mark missing runtime session running");

            queries::create_sandbox(
                &pool,
                sandbox_id,
                &external_id,
                "test",
                "joysafeter/test:latest",
                Some(session_id),
                None,
                None,
                Some(&json!({})),
            )
            .await
            .expect("create missing runtime sandbox");
            queries::transition_sandbox(&pool, sandbox_id, "idle")
                .await
                .expect("sandbox idle before missing runtime cleanup");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_tasks (
                    id, agent_id, chat_session_id, sandbox_id, status, prompt, output,
                    timeout_sec, retry_count, max_retries
                )
                VALUES ($1, $2, $3, $4, 'scheduling', 'missing runtime prompt', '', 7200, 0, 2)
                "#,
            )
            .bind(task_id)
            .bind(agent_id)
            .bind(session_id)
            .bind(sandbox_id)
            .execute(&pool)
            .await
            .expect("insert missing runtime task");

            let provider = Arc::new(CleanupRecordingProvider {
                active: Vec::new(),
                statuses: HashMap::from([(
                    external_id.clone(),
                    crate::sandbox::provider::SandboxStatus::NotFound,
                )]),
                destroyed: tokio::sync::Mutex::new(Vec::new()),
            });
            let redis_client = redis::Client::open("redis://127.0.0.1:1/")
                .expect("build unreachable redis client");
            let queue = TaskQueue::new(redis_client);
            let bridge_registry = BridgeRegistry::new();
            let config = JoySafeterConfig::from_env();
            let runtime_config = Arc::new(RuntimeConfig::from_config(&config));
            let controller = SandboxController::new(
                pool.clone(),
                queue,
                bridge_registry,
                provider.clone(),
                None,
                config,
                runtime_config,
            );

            let cleaned = controller
                .cleanup_orphaned()
                .await
                .expect("cleanup missing provider runtime");
            assert_eq!(cleaned, 1);

            let task: (String, i32, Option<Uuid>) = sqlx::query_as(
                "SELECT status, retry_count, sandbox_id FROM joysafeter_tasks WHERE id = $1",
            )
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load recovered missing runtime task");
            assert_eq!(task.0, "pending");
            assert_eq!(task.1, 1);
            assert_eq!(task.2, None);

            let session: (String, Option<Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load recovered missing runtime session");
            assert_eq!(session.0, "rescheduling");
            assert_eq!(session.1, Some(json!({"type": "sandbox_failed"})));

            let sandbox: (String, bool) = sqlx::query_as(
                "SELECT status, destroyed_at IS NOT NULL FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load destroyed missing runtime sandbox");
            assert_eq!(sandbox.0, "destroyed");
            assert!(sandbox.1);

            let event_count: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_rescheduling'
                  AND payload->>'task_id' = $2
                  AND payload->'stop_reason'->>'type' = 'sandbox_failed'
                "#,
            )
            .bind(session_id)
            .bind(task_id.to_string())
            .fetch_one(&pool)
            .await
            .expect("count missing runtime rescheduling events");
            assert_eq!(event_count, 1);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
    }

    async fn create_missing_runtime_running_fixture(
        pool: &PgPool,
        task_status: &str,
        retry_count: i32,
        max_retries: i32,
        prompt: &str,
    ) -> (Uuid, Uuid, Uuid, Uuid, String) {
        let agent_id = Uuid::now_v7();
        let session_id = Uuid::now_v7();
        let task_id = Uuid::now_v7();
        let sandbox_id = Uuid::now_v7();
        let external_id = format!("{prompt}-{sandbox_id}");
        let unique = agent_id.simple().to_string();

        sqlx::query(
            r#"
            INSERT INTO joysafeter_agents (
                id, name, engine_kind, model, system_prompt, env, mcp_configs,
                skills, tools, agents, commands, permission_mode, metadata,
                multiagent, version
            )
            VALUES (
                $1, $2, 'claude', $3, 'missing runtime running system', '{}'::jsonb, '[]'::jsonb,
                '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                'bypassPermissions', '{}'::jsonb, NULL, 1
            )
            "#,
        )
        .bind(agent_id)
        .bind(format!("missing-runtime-running-agent-{unique}"))
        .bind(json!({"id": "missing-runtime-running-model"}))
        .execute(pool)
        .await
        .expect("insert missing runtime running agent");

        queries::create_session(pool, session_id, Some(agent_id), None, None, None)
            .await
            .expect("create missing runtime running session");
        sqlx::query("UPDATE joysafeter_sessions SET status = 'running' WHERE id = $1")
            .bind(session_id)
            .execute(pool)
            .await
            .expect("mark missing runtime running session running");

        queries::create_sandbox(
            pool,
            sandbox_id,
            &external_id,
            "test",
            "joysafeter/test:latest",
            Some(session_id),
            None,
            None,
            Some(&json!({})),
        )
        .await
        .expect("create missing runtime running sandbox");
        queries::transition_sandbox(pool, sandbox_id, "idle")
            .await
            .expect("sandbox idle before missing runtime running cleanup");

        sqlx::query(
            r#"
            INSERT INTO joysafeter_tasks (
                id, agent_id, chat_session_id, sandbox_id, status, prompt, output,
                timeout_sec, retry_count, max_retries
            )
            VALUES ($1, $2, $3, $4, $5, $6, '', 7200, $7, $8)
            "#,
        )
        .bind(task_id)
        .bind(agent_id)
        .bind(session_id)
        .bind(sandbox_id)
        .bind(task_status)
        .bind(prompt)
        .bind(retry_count)
        .bind(max_retries)
        .execute(pool)
        .await
        .expect("insert missing runtime running task");

        if task_status == "running" {
            assert!(queries::start_sandbox_task(pool, sandbox_id, task_id)
                .await
                .expect("mark missing runtime sandbox running"));
        }

        (agent_id, session_id, task_id, sandbox_id, external_id)
    }

    fn missing_runtime_controller(pool: PgPool, external_id: String) -> SandboxController {
        let provider = Arc::new(CleanupRecordingProvider {
            active: Vec::new(),
            statuses: HashMap::from([(
                external_id,
                crate::sandbox::provider::SandboxStatus::NotFound,
            )]),
            destroyed: tokio::sync::Mutex::new(Vec::new()),
        });
        let redis_client =
            redis::Client::open("redis://127.0.0.1:1/").expect("build unreachable redis client");
        let queue = TaskQueue::new(redis_client);
        let bridge_registry = BridgeRegistry::new();
        let config = JoySafeterConfig::from_env();
        let runtime_config = Arc::new(RuntimeConfig::from_config(&config));
        SandboxController::new(
            pool,
            queue,
            bridge_registry,
            provider,
            None,
            config,
            runtime_config,
        )
    }

    #[tokio::test]
    async fn cleanup_orphaned_missing_runtime_recovers_running_task_before_destroy() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let prompt = "missing runtime running retry prompt";
        let (agent_id, session_id, task_id, sandbox_id, external_id) =
            create_missing_runtime_running_fixture(&pool, "running", 0, 2, prompt).await;

        async {
            let controller = missing_runtime_controller(pool.clone(), external_id.clone());
            let cleaned = controller
                .cleanup_orphaned()
                .await
                .expect("cleanup missing runtime running task");
            assert_eq!(cleaned, 1);

            let task: (String, i32, Option<Uuid>) = sqlx::query_as(
                "SELECT status, retry_count, sandbox_id FROM joysafeter_tasks WHERE id = $1",
            )
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load recovered missing runtime running task");
            assert_eq!(task.0, "pending");
            assert_eq!(task.1, 1);
            assert_eq!(task.2, None);

            let session: (String, Option<Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load missing runtime running session");
            assert_eq!(session.0, "rescheduling");
            assert_eq!(session.1, Some(json!({"type": "sandbox_failed"})));

            let sandbox: (String, bool) = sqlx::query_as(
                "SELECT status, destroyed_at IS NOT NULL FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load missing runtime running sandbox");
            assert_eq!(sandbox.0, "destroyed");
            assert!(sandbox.1);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
    }

    #[tokio::test]
    async fn cleanup_orphaned_missing_runtime_fails_exhausted_running_task_before_destroy() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let prompt = "missing runtime running exhausted prompt";
        let (agent_id, session_id, task_id, sandbox_id, external_id) =
            create_missing_runtime_running_fixture(&pool, "running", 2, 2, prompt).await;

        async {
            let controller = missing_runtime_controller(pool.clone(), external_id.clone());
            let cleaned = controller
                .cleanup_orphaned()
                .await
                .expect("cleanup missing runtime exhausted running task");
            assert_eq!(cleaned, 1);

            let task: (String, i32, Option<String>, Option<Uuid>) = sqlx::query_as(
                "SELECT status, retry_count, error, sandbox_id FROM joysafeter_tasks WHERE id = $1",
            )
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load failed missing runtime running task");
            assert_eq!(task.0, "failed");
            assert_eq!(task.1, 2);
            assert_eq!(task.2.as_deref(), Some("sandbox provider runtime missing"));
            assert_eq!(task.3, None);

            let session: (String, Option<Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load missing runtime exhausted session");
            assert_eq!(session.0, "idle");
            assert_eq!(
                session.1,
                Some(json!({
                    "type": "error",
                    "message": "sandbox provider runtime missing"
                }))
            );

            let sandbox: (String, bool) = sqlx::query_as(
                "SELECT status, destroyed_at IS NOT NULL FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load missing runtime exhausted sandbox");
            assert_eq!(sandbox.0, "destroyed");
            assert!(sandbox.1);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
    }

    #[tokio::test]
    async fn health_check_dead_bridge_recovers_running_task_before_destroy() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let prompt = "health check missing runtime running prompt";
        let (agent_id, session_id, task_id, sandbox_id, external_id) =
            create_missing_runtime_running_fixture(&pool, "running", 0, 2, prompt).await;

        async {
            let provider = Arc::new(CleanupRecordingProvider {
                active: Vec::new(),
                statuses: HashMap::from([(
                    external_id.clone(),
                    crate::sandbox::provider::SandboxStatus::NotFound,
                )]),
                destroyed: tokio::sync::Mutex::new(Vec::new()),
            });
            let redis_client = redis::Client::open("redis://127.0.0.1:1/")
                .expect("build unreachable redis client");
            let queue = TaskQueue::new(redis_client);
            let bridge_registry = BridgeRegistry::new();
            let (runner_tx, _runner_rx) = tokio::sync::mpsc::channel(1);
            let bridge = Arc::new(crate::kernel::sandbox_bridge::SandboxBridge::new(
                sandbox_id, runner_tx,
            ));
            bridge_registry.register(external_id.clone(), bridge);
            let config = JoySafeterConfig::from_env();
            let runtime_config = Arc::new(RuntimeConfig::from_config(&config));
            let controller = SandboxController::new(
                pool.clone(),
                queue,
                bridge_registry.clone(),
                provider.clone(),
                None,
                config,
                runtime_config,
            );

            controller
                .health_check_bridges()
                .await
                .expect("health check dead bridge");

            assert!(bridge_registry.get(&external_id).is_none());
            assert_eq!(
                provider.destroyed.lock().await.as_slice(),
                &[external_id.clone()]
            );

            let task: (String, i32, Option<Uuid>) = sqlx::query_as(
                "SELECT status, retry_count, sandbox_id FROM joysafeter_tasks WHERE id = $1",
            )
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load health check recovered task");
            assert_eq!(task.0, "pending");
            assert_eq!(task.1, 1);
            assert_eq!(task.2, None);

            let session: (String, Option<Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load health check recovered session");
            assert_eq!(session.0, "rescheduling");
            assert_eq!(session.1, Some(json!({"type": "sandbox_failed"})));

            let sandbox: (String, bool) = sqlx::query_as(
                "SELECT status, destroyed_at IS NOT NULL FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load health check destroyed sandbox");
            assert_eq!(sandbox.0, "destroyed");
            assert!(sandbox.1);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
    }

    #[tokio::test]
    async fn health_check_dead_bridge_isolates_row_before_provider_destroy() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let prompt = "health check destroy ordering prompt";
        let (agent_id, session_id, task_id, sandbox_id, external_id) =
            create_missing_runtime_running_fixture(&pool, "running", 0, 2, prompt).await;

        async {
            let provider = Arc::new(DestroyObservesDbStateProvider {
                pool: pool.clone(),
                sandbox_id,
                task_id,
                external_id: external_id.clone(),
                observed_states: tokio::sync::Mutex::new(Vec::new()),
                destroyed: tokio::sync::Mutex::new(Vec::new()),
            });
            let redis_client = redis::Client::open("redis://127.0.0.1:1/")
                .expect("build unreachable redis client");
            let queue = TaskQueue::new(redis_client);
            let bridge_registry = BridgeRegistry::new();
            let (runner_tx, _runner_rx) = tokio::sync::mpsc::channel(1);
            let bridge = Arc::new(crate::kernel::sandbox_bridge::SandboxBridge::new(
                sandbox_id, runner_tx,
            ));
            bridge_registry.register(external_id.clone(), bridge);
            let config = JoySafeterConfig::from_env();
            let runtime_config = Arc::new(RuntimeConfig::from_config(&config));
            let controller = SandboxController::new(
                pool.clone(),
                queue,
                bridge_registry.clone(),
                provider.clone(),
                None,
                config,
                runtime_config,
            );

            controller
                .health_check_bridges()
                .await
                .expect("health check dead bridge");

            let observed = provider.observed_states.lock().await.clone();
            assert_eq!(
                observed,
                vec![("stopping".to_string(), "pending".to_string(), None)]
            );
            assert_eq!(
                provider.destroyed.lock().await.as_slice(),
                &[external_id.clone()]
            );
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
    }

    #[tokio::test]
    async fn non_graceful_reap_recovers_running_task_before_stopping_sandbox() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let prompt = "non graceful reap running prompt";
        let (agent_id, session_id, task_id, sandbox_id, external_id) =
            create_missing_runtime_running_fixture(&pool, "running", 0, 2, prompt).await;

        async {
            sqlx::query("UPDATE joysafeter_sandboxes SET disconnected_at = NOW() WHERE id = $1")
                .bind(sandbox_id)
                .execute(&pool)
                .await
                .expect("mark sandbox disconnected");

            let provider = Arc::new(CleanupRecordingProvider {
                active: Vec::new(),
                statuses: HashMap::new(),
                destroyed: tokio::sync::Mutex::new(Vec::new()),
            });
            let redis_client = redis::Client::open("redis://127.0.0.1:1/")
                .expect("build unreachable redis client");
            let queue = TaskQueue::new(redis_client);
            let bridge_registry = BridgeRegistry::new();
            let config = JoySafeterConfig::from_env();
            let runtime_config = Arc::new(RuntimeConfig::from_config(&config));
            let controller = SandboxController::new(
                pool.clone(),
                queue,
                bridge_registry,
                provider.clone(),
                None,
                config,
                runtime_config,
            );

            controller
                .stop_idle_sandbox(sandbox_id, Some(external_id.clone()), "running".to_string())
                .await;

            let task: (String, i32, Option<Uuid>) = sqlx::query_as(
                "SELECT status, retry_count, sandbox_id FROM joysafeter_tasks WHERE id = $1",
            )
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load non-graceful reap recovered task");
            assert_eq!(task.0, "pending");
            assert_eq!(task.1, 1);
            assert_eq!(task.2, None);

            let session: (String, Option<Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load non-graceful reap session");
            assert_eq!(session.0, "rescheduling");
            assert_eq!(session.1, Some(json!({"type": "sandbox_failed"})));

            let sandbox: (String, Option<Uuid>) = sqlx::query_as(
                "SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load non-graceful reap sandbox");
            assert_eq!(sandbox.0, "stopped");
            assert_eq!(sandbox.1, None);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
    }

    #[tokio::test]
    async fn non_graceful_reap_isolates_row_before_provider_stop() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let prompt = "non graceful stop ordering prompt";
        let (agent_id, session_id, task_id, sandbox_id, external_id) =
            create_missing_runtime_running_fixture(&pool, "running", 0, 2, prompt).await;

        async {
            sqlx::query("UPDATE joysafeter_sandboxes SET disconnected_at = NOW() WHERE id = $1")
                .bind(sandbox_id)
                .execute(&pool)
                .await
                .expect("mark sandbox disconnected");

            let provider = Arc::new(StopObservesDbStateProvider {
                pool: pool.clone(),
                sandbox_id,
                task_id,
                external_id: external_id.clone(),
                observed_states: tokio::sync::Mutex::new(Vec::new()),
                stopped: tokio::sync::Mutex::new(Vec::new()),
            });
            let redis_client = redis::Client::open("redis://127.0.0.1:1/")
                .expect("build unreachable redis client");
            let queue = TaskQueue::new(redis_client);
            let bridge_registry = BridgeRegistry::new();
            let config = JoySafeterConfig::from_env();
            let runtime_config = Arc::new(RuntimeConfig::from_config(&config));
            let controller = SandboxController::new(
                pool.clone(),
                queue,
                bridge_registry,
                provider.clone(),
                None,
                config,
                runtime_config,
            );

            controller
                .stop_idle_sandbox(sandbox_id, Some(external_id.clone()), "running".to_string())
                .await;

            let observed = provider.observed_states.lock().await.clone();
            assert_eq!(
                observed,
                vec![("stopping".to_string(), "pending".to_string(), None)]
            );
            assert_eq!(provider.stopped.lock().await.as_slice(), &[external_id]);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
    }

    #[tokio::test]
    async fn force_stop_stuck_recovers_running_task_before_provider_stop() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let prompt = "force stop stuck running prompt";
        let (agent_id, session_id, task_id, sandbox_id, external_id) =
            create_missing_runtime_running_fixture(&pool, "running", 0, 2, prompt).await;

        async {
            sqlx::query(
                r#"
                UPDATE joysafeter_sandboxes
                SET status = 'stopping',
                    updated_at = NOW() - INTERVAL '2 minutes'
                WHERE id = $1
                "#,
            )
            .bind(sandbox_id)
            .execute(&pool)
            .await
            .expect("mark sandbox stuck stopping");

            let provider = Arc::new(StopObservesDbStateProvider {
                pool: pool.clone(),
                sandbox_id,
                task_id,
                external_id: external_id.clone(),
                observed_states: tokio::sync::Mutex::new(Vec::new()),
                stopped: tokio::sync::Mutex::new(Vec::new()),
            });
            let redis_client = redis::Client::open("redis://127.0.0.1:1/")
                .expect("build unreachable redis client");
            let queue = TaskQueue::new(redis_client);
            let bridge_registry = BridgeRegistry::new();
            let config = JoySafeterConfig::from_env();
            let runtime_config = Arc::new(RuntimeConfig::from_config(&config));
            let controller = SandboxController::new(
                pool.clone(),
                queue,
                bridge_registry,
                provider.clone(),
                None,
                config,
                runtime_config,
            );

            controller
                .force_stop_stuck()
                .await
                .expect("force stop stuck sandbox");

            assert_eq!(
                provider.observed_states.lock().await.as_slice(),
                &[("stopping".to_string(), "pending".to_string(), None)]
            );
            assert_eq!(provider.stopped.lock().await.as_slice(), &[external_id]);

            let sandbox_status: String =
                sqlx::query_scalar("SELECT status FROM joysafeter_sandboxes WHERE id = $1")
                    .bind(sandbox_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load force-stopped sandbox");
            assert_eq!(sandbox_status, "stopped");
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
    }

    #[tokio::test]
    async fn provisioning_timeout_does_not_stop_after_running_claim_race() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = Uuid::now_v7();
        let session_id = Uuid::now_v7();
        let task_id = Uuid::now_v7();
        let sandbox_id = Uuid::now_v7();
        let external_id = format!("provisioning-timeout-race-{sandbox_id}");
        let unique = agent_id.simple().to_string();

        async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (
                    id, name, engine_kind, model, system_prompt, env, mcp_configs,
                    skills, tools, agents, commands, permission_mode, metadata,
                    multiagent, version
                )
                VALUES (
                    $1, $2, 'claude', $3, 'provisioning race system', '{}'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    'bypassPermissions', '{}'::jsonb, NULL, 1
                )
                "#,
            )
            .bind(agent_id)
            .bind(format!("provisioning-race-agent-{unique}"))
            .bind(json!({"id": "provisioning-race-model"}))
            .execute(&pool)
            .await
            .expect("insert provisioning race agent");

            queries::create_session(&pool, session_id, Some(agent_id), None, None, None)
                .await
                .expect("create provisioning race session");
            sqlx::query("UPDATE joysafeter_sessions SET status = 'running' WHERE id = $1")
                .bind(session_id)
                .execute(&pool)
                .await
                .expect("mark provisioning race session running");

            queries::create_sandbox(
                &pool,
                sandbox_id,
                &external_id,
                "test",
                "joysafeter/test:latest",
                Some(session_id),
                None,
                None,
                Some(&json!({})),
            )
            .await
            .expect("create provisioning race sandbox");
            queries::transition_sandbox(&pool, sandbox_id, "provisioning")
                .await
                .expect("mark provisioning race sandbox provisioning");
            sqlx::query(
                r#"
                UPDATE joysafeter_sandboxes
                SET last_used_at = NOW() - INTERVAL '10 minutes',
                    created_at = NOW() - INTERVAL '10 minutes'
                WHERE id = $1
                "#,
            )
            .bind(sandbox_id)
            .execute(&pool)
            .await
            .expect("age provisioning race sandbox");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_tasks (
                    id, agent_id, chat_session_id, sandbox_id, status, prompt, output,
                    timeout_sec, retry_count, max_retries
                )
                VALUES ($1, $2, $3, $4, 'scheduling', 'provisioning race prompt', '', 7200, 0, 2)
                "#,
            )
            .bind(task_id)
            .bind(agent_id)
            .bind(session_id)
            .bind(sandbox_id)
            .execute(&pool)
            .await
            .expect("insert provisioning race scheduling task");

            let provider = Arc::new(StopClaimsTaskProvider {
                pool: pool.clone(),
                sandbox_id,
                external_id: external_id.clone(),
                observed_statuses: tokio::sync::Mutex::new(Vec::new()),
            });
            let redis_client = redis::Client::open("redis://127.0.0.1:1/")
                .expect("build unreachable redis client");
            let queue = TaskQueue::new(redis_client);
            let bridge_registry = BridgeRegistry::new();
            let config = JoySafeterConfig::from_env();
            let runtime_config = Arc::new(RuntimeConfig::from_config(&config));
            let controller = SandboxController::new(
                pool.clone(),
                queue,
                bridge_registry,
                provider.clone(),
                None,
                config,
                runtime_config,
            );

            controller
                .check_provisioning_timeout()
                .await
                .expect("run provisioning timeout race check");

            let task: (String, i32, Option<Uuid>) = sqlx::query_as(
                "SELECT status, retry_count, sandbox_id FROM joysafeter_tasks WHERE id = $1",
            )
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load provisioning race task");
            assert_eq!(task.0, "pending");
            assert_eq!(task.1, 1);
            assert_eq!(task.2, None);

            let session: (String, Option<Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load provisioning race session");
            assert_eq!(session.0, "rescheduling");
            assert_eq!(session.1, Some(json!({"type": "sandbox_failed"})));

            let sandbox: (String, Option<Uuid>) = sqlx::query_as(
                "SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load provisioning race sandbox");
            assert_eq!(sandbox.0, "stopped");
            assert_eq!(sandbox.1, None);
            assert_eq!(
                provider.observed_statuses.lock().await.as_slice(),
                &["stopping".to_string()]
            );
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
    }

    #[tokio::test]
    async fn graceful_stop_failure_does_not_revert_concurrent_error_to_idle() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let sandbox_id = Uuid::now_v7();

        async {
            queries::create_sandbox(
                &pool,
                sandbox_id,
                &format!("stop-error-{sandbox_id}"),
                "test",
                "joysafeter/test:latest",
                None,
                None,
                None,
                Some(&json!({})),
            )
            .await
            .expect("create stop error sandbox");
            queries::transition_sandbox(&pool, sandbox_id, "idle")
                .await
                .expect("sandbox idle");

            let redis_client =
                redis::Client::open("redis://127.0.0.1:6379").expect("build redis client");
            let queue = TaskQueue::new(redis_client);
            let bridge_registry = BridgeRegistry::new();
            let mut config = JoySafeterConfig::from_env();
            config.instance_id = format!("stop-error-instance-{sandbox_id}");
            let runtime_config = Arc::new(RuntimeConfig::from_config(&config));
            let provider = Arc::new(StopMarksErrorProvider {
                pool: pool.clone(),
                sandbox_id,
            });
            let controller = SandboxController::new(
                pool.clone(),
                queue,
                bridge_registry,
                provider,
                None,
                config,
                runtime_config,
            );

            controller
                .stop_idle_sandbox(
                    sandbox_id,
                    Some(format!("stop-error-{sandbox_id}")),
                    "idle".to_string(),
                )
                .await;

            let sandbox: (String, Option<String>) = sqlx::query_as(
                "SELECT status, config->>'setup_error' FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load sandbox after failed graceful stop");
            assert_eq!(sandbox.0, "error");
            assert_eq!(sandbox.1.as_deref(), Some("concurrent stop failure"));
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
    }

    #[tokio::test]
    async fn sandbox_bulk_reset_marks_session_rescheduling_event() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = Uuid::now_v7();
        let session_id = Uuid::now_v7();
        let task_id = Uuid::now_v7();
        let sandbox_id = Uuid::now_v7();
        let unique = agent_id.simple().to_string();

        async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (
                    id, name, engine_kind, model, system_prompt, env, mcp_configs,
                    skills, tools, agents, commands, permission_mode, metadata,
                    multiagent, version
                )
                VALUES (
                    $1, $2, 'claude', $3, 'sandbox reset system', '{}'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    'bypassPermissions', '{}'::jsonb, NULL, 1
                )
                "#,
            )
            .bind(agent_id)
            .bind(format!("sandbox-reset-agent-{unique}"))
            .bind(json!({"id": "sandbox-reset-model"}))
            .execute(&pool)
            .await
            .expect("insert sandbox reset agent");

            queries::create_session(&pool, session_id, Some(agent_id), None, None, None)
                .await
                .expect("create sandbox reset session");
            sqlx::query("UPDATE joysafeter_sessions SET status = 'running' WHERE id = $1")
                .bind(session_id)
                .execute(&pool)
                .await
                .expect("mark session running");

            queries::create_sandbox(
                &pool,
                sandbox_id,
                &format!("sandbox-reset-{sandbox_id}"),
                "test",
                "joysafeter/test:latest",
                Some(session_id),
                None,
                None,
                Some(&json!({})),
            )
            .await
            .expect("create sandbox");
            queries::transition_sandbox(&pool, sandbox_id, "idle")
                .await
                .expect("sandbox idle");
            queries::transition_sandbox(&pool, sandbox_id, "running")
                .await
                .expect("sandbox running");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_tasks (
                    id, agent_id, chat_session_id, sandbox_id, status, prompt, output,
                    timeout_sec, retry_count, max_retries
                )
                VALUES ($1, $2, $3, $4, 'scheduling', 'sandbox reset prompt', '', 7200, 0, 2)
                "#,
            )
            .bind(task_id)
            .bind(agent_id)
            .bind(session_id)
            .bind(sandbox_id)
            .execute(&pool)
            .await
            .expect("insert sandbox reset task");

            let reset_tasks = queries::reset_sandbox_tasks_to_pending_returning(&pool, sandbox_id)
                .await
                .expect("reset scheduling tasks");
            assert_eq!(reset_tasks.len(), 1);
            assert_eq!(reset_tasks[0].id, task_id);
            assert_eq!(reset_tasks[0].session_id, Some(session_id));

            mark_reset_tasks_rescheduling(&pool, &reset_tasks).await;

            let task: (String, i32, Option<Uuid>) = sqlx::query_as(
                "SELECT status, retry_count, sandbox_id FROM joysafeter_tasks WHERE id = $1",
            )
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load reset task");
            assert_eq!(task.0, "pending");
            assert_eq!(task.1, 1);
            assert_eq!(task.2, None);

            let session: (String, Option<Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load rescheduling session");
            assert_eq!(session.0, "rescheduling");
            assert_eq!(session.1, Some(json!({"type": "sandbox_failed"})));

            let event: (String, Value, i64) = sqlx::query_as(
                r#"
                SELECT event_type, payload, seq
                FROM joysafeter_session_events
                WHERE session_id = $1
                ORDER BY seq DESC
                LIMIT 1
                "#,
            )
            .bind(session_id)
            .fetch_one(&pool)
            .await
            .expect("load rescheduling event");
            assert_eq!(event.0, "session.status_rescheduling");
            assert_eq!(
                event.1,
                json!({
                    "task_id": task_id.to_string(),
                    "stop_reason": {"type": "sandbox_failed"}
                })
            );
            assert_eq!(event.2, 1);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
    }

    #[tokio::test]
    async fn sandbox_bulk_reset_exhausted_marks_task_failed_and_session_idle() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = Uuid::now_v7();
        let session_id = Uuid::now_v7();
        let task_id = Uuid::now_v7();
        let sandbox_id = Uuid::now_v7();
        let unique = agent_id.simple().to_string();
        let failure_reason = "sandbox provisioning failed after retry limit";

        async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (
                    id, name, engine_kind, model, system_prompt, env, mcp_configs,
                    skills, tools, agents, commands, permission_mode, metadata,
                    multiagent, version
                )
                VALUES (
                    $1, $2, 'claude', $3, 'sandbox exhausted system', '{}'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    'bypassPermissions', '{}'::jsonb, NULL, 1
                )
                "#,
            )
            .bind(agent_id)
            .bind(format!("sandbox-exhausted-agent-{unique}"))
            .bind(json!({"id": "sandbox-exhausted-model"}))
            .execute(&pool)
            .await
            .expect("insert sandbox exhausted agent");

            queries::create_session(&pool, session_id, Some(agent_id), None, None, None)
                .await
                .expect("create sandbox exhausted session");
            sqlx::query("UPDATE joysafeter_sessions SET status = 'rescheduling' WHERE id = $1")
                .bind(session_id)
                .execute(&pool)
                .await
                .expect("mark session rescheduling");

            queries::create_sandbox(
                &pool,
                sandbox_id,
                &format!("sandbox-exhausted-{sandbox_id}"),
                "test",
                "joysafeter/test:latest",
                Some(session_id),
                None,
                None,
                Some(&json!({})),
            )
            .await
            .expect("create sandbox");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_tasks (
                    id, agent_id, chat_session_id, sandbox_id, status, prompt, output,
                    timeout_sec, retry_count, max_retries
                )
                VALUES ($1, $2, $3, $4, 'scheduling', 'sandbox exhausted prompt', '', 7200, 2, 2)
                "#,
            )
            .bind(task_id)
            .bind(agent_id)
            .bind(session_id)
            .bind(sandbox_id)
            .execute(&pool)
            .await
            .expect("insert sandbox exhausted task");

            let failed_tasks =
                queries::fail_exhausted_sandbox_tasks_returning(&pool, sandbox_id, failure_reason)
                    .await
                    .expect("fail exhausted task");
            assert_eq!(failed_tasks.len(), 1);
            assert_eq!(failed_tasks[0].id, task_id);

            let reset_tasks = queries::reset_sandbox_tasks_to_pending_returning(&pool, sandbox_id)
                .await
                .expect("reset retryable tasks");
            assert!(reset_tasks.is_empty());

            mark_failed_tasks_idle(&pool, &failed_tasks, failure_reason).await;

            let task: (String, i32, Option<String>) = sqlx::query_as(
                "SELECT status, retry_count, error FROM joysafeter_tasks WHERE id = $1",
            )
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load exhausted task");
            assert_eq!(task.0, "failed");
            assert_eq!(task.1, 2);
            assert_eq!(task.2.as_deref(), Some(failure_reason));

            let session: (String, Option<Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load exhausted session");
            assert_eq!(session.0, "idle");
            assert_eq!(
                session.1,
                Some(json!({"type": "error", "message": failure_reason}))
            );

            let idle_events: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_idle'
                  AND payload->>'task_id' = $2
                  AND payload->'stop_reason'->>'message' = $3
                "#,
            )
            .bind(session_id)
            .bind(task_id.to_string())
            .bind(failure_reason)
            .fetch_one(&pool)
            .await
            .expect("count exhausted idle events");
            assert_eq!(idle_events, 1);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
    }
}
