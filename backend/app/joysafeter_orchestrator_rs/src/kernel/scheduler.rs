use std::sync::Arc;
use std::time::Duration;

use serde_json::{json, Value};
use sqlx::PgPool;
use tokio::sync::Semaphore;
use tokio::task::JoinHandle;
use tokio::time::Instant;
use tracing::{debug, error, info, warn};

use crate::config::JoySafeterConfig;
use crate::db::queries;
use crate::ids::{AgentId, ProjectId, SessionId, TaskId};
use crate::kernel::credentials::snapshot;
use crate::kernel::credentials::{error::CredentialRuntimeError, CredentialStore};
use crate::kernel::ha::BridgeStore;
use crate::kernel::queue::TaskQueue;
use crate::kernel::runtime_freshness::RuntimeFreshnessError;
use crate::kernel::sandbox_resolver::SandboxResolver;
use crate::sandbox::provider::SandboxProvider;

const QUEUE_POP_TIMEOUT: Duration = Duration::from_secs(1);
const DB_REPAIR_SWEEP_INTERVAL: Duration = Duration::from_secs(30);
const SCHEDULING_RETRY_BASE_BACKOFF: Duration = Duration::from_secs(5);
const SCHEDULING_RETRY_MAX_BACKOFF: Duration = Duration::from_secs(60);
const GENERATION_CHANGE_IMMEDIATE_RETRIES: usize = 2;

/// Task scheduler — consumes Redis task candidates, claims them in DB, resolves
/// sandboxes, and dispatches.
///
/// Redis is the scheduling wakeup/candidate channel; the DB state transition is
/// still authoritative. A bounded DB repair sweep recovers pending rows that
/// predate the queue cutover or whose queue message was lost during an outage.

/// Spawn the scheduler as a background tokio task.
///
/// T4 fix: removed the local execution_semaphore — concurrency limiting is
/// done by the gRPC server's multi_task_loop (which acquires an exec_sem
/// permit before dispatching each task). The scheduler only needs the
/// scheduling_semaphore to limit concurrent resolve operations.
///
/// T5 fix: removed the TaskScheduler struct and stop() method — they were
/// disconnected from the spawned loop. The loop runs until process exit.
pub fn spawn_scheduler(
    pool: PgPool,
    queue: TaskQueue,
    bridge_store: Arc<dyn BridgeStore>,
    task_dispatcher: Arc<dyn crate::kernel::ha::TaskDispatcher>,
    provider: Arc<dyn SandboxProvider>,
    config: JoySafeterConfig,
    pool_replenish_notify: Option<Arc<tokio::sync::Notify>>,
    network_policy_queue: Option<Arc<dyn crate::kernel::ha::NetworkPolicyRequestQueue>>,
    xds_authority: crate::kernel::xds_authority::XdsAuthorityState,
    identity_provider: Arc<dyn crate::kernel::agent_identity_provider::AgentIdentityProvider>,
) -> JoinHandle<()> {
    let mut resolver = SandboxResolver::new(pool.clone(), provider, config.clone())
        .with_network_policy_control(xds_authority, network_policy_queue);
    if let Some(notify) = pool_replenish_notify {
        resolver = resolver.with_pool_replenish_notify(notify);
    }
    resolver = resolver.with_identity_provider(identity_provider);
    let resolver = Arc::new(resolver);
    let scheduling_semaphore = Arc::new(Semaphore::new(config.max_scheduling_tasks));

    tokio::spawn(async move {
        info!(
            max_scheduling = config.max_scheduling_tasks,
            "TaskScheduler started"
        );
        let mut next_repair_sweep = Instant::now();

        loop {
            let available_slots = scheduling_semaphore
                .available_permits()
                .min(config.scheduler_batch_size);
            if available_slots == 0 {
                tokio::time::sleep(Duration::from_millis(200)).await;
                continue;
            }

            let mut tasks = Vec::new();

            match queue.pop_from_global(QUEUE_POP_TIMEOUT).await {
                Ok(Some(task_id)) => {
                    match queries::claim_pending_task_by_id(&pool, task_id).await {
                        Ok(Some(task)) => tasks.push(task),
                        Ok(None) => debug!(
                            task_id = %task_id,
                            "Ignoring stale global queue entry; task is no longer pending"
                        ),
                        Err(e) => error!(task_id = %task_id, "Failed to claim queued task: {e}"),
                    }
                }
                Ok(None) => {}
                Err(e) => {
                    warn!("Failed to pop global Redis task queue: {e}");
                    tokio::time::sleep(Duration::from_secs(1)).await;
                }
            }

            while tasks.len() < available_slots {
                match queue.try_pop_from_global().await {
                    Ok(Some(task_id)) => {
                        match queries::claim_pending_task_by_id(&pool, task_id).await {
                            Ok(Some(task)) => tasks.push(task),
                            Ok(None) => debug!(
                                task_id = %task_id,
                                "Ignoring stale global queue entry; task is no longer pending"
                            ),
                            Err(e) => {
                                error!(task_id = %task_id, "Failed to claim queued task: {e}");
                                break;
                            }
                        }
                    }
                    Ok(None) => break,
                    Err(e) => {
                        warn!("Failed to drain ready global queue entries: {e}");
                        break;
                    }
                }
            }

            if tasks.is_empty() && Instant::now() >= next_repair_sweep {
                match queries::claim_pending_tasks(&pool, available_slots as i64).await {
                    Ok(repaired_tasks) => {
                        if !repaired_tasks.is_empty() {
                            warn!(
                                count = repaired_tasks.len(),
                                "DB repair sweep claimed pending tasks missing from Redis queue"
                            );
                        }
                        tasks = repaired_tasks;
                    }
                    Err(e) => {
                        error!("Failed to run scheduler DB repair sweep: {e}");
                    }
                }
                next_repair_sweep = Instant::now() + DB_REPAIR_SWEEP_INTERVAL;
            }

            if tasks.is_empty() {
                continue;
            }

            info!(count = tasks.len(), "Claimed tasks for scheduling");

            // Schedule each task concurrently
            for task in tasks {
                let pool = pool.clone();
                let queue = queue.clone();
                let bridge_store = bridge_store.clone();
                let task_dispatcher = task_dispatcher.clone();
                let config = config.clone();
                let resolver = resolver.clone();
                let sched_sem = scheduling_semaphore.clone();

                // Acquire scheduling semaphore
                let _sched_permit = match sched_sem.try_acquire_owned() {
                    Ok(p) => p,
                    Err(_) => {
                        let _ = queries::reset_scheduling_task_to_pending(&pool, task.id).await;
                        continue;
                    }
                };

                let resolver_pool = pool.clone();
                tokio::spawn(async move {
                    let task_id = task.id;
                    // T10 fix: wrap resolver.resolve() in a timeout to prevent
                    // a hung Docker daemon from blocking the scheduling permit forever.
                    let schedule_result = tokio::time::timeout(
                        Duration::from_secs(120),
                        schedule_single_task(
                            &resolver_pool,
                            &queue,
                            &*bridge_store,
                            &*task_dispatcher,
                            &config,
                            &resolver,
                            task_id,
                            task.agent_id,
                            task.session_id,
                            task.project_id,
                        ),
                    )
                    .await;

                    let result = match schedule_result {
                        Ok(inner) => inner,
                        Err(_) => Err(anyhow::anyhow!("sandbox resolution timed out after 120s")),
                    };

                    if let Err(e) = result {
                        error!(task_id = %task_id, "Failed to schedule task: {e}");
                        let permanent_code = permanent_scheduling_failure_code(&e);
                        handle_scheduling_failure(
                            &resolver_pool,
                            &queue,
                            task_id,
                            &e.to_string(),
                            permanent_code,
                        )
                        .await;
                    }
                    drop(_sched_permit);
                });
            }
        }
    })
}

/// Schedule a single task: resolve agent, create session if needed, inject secrets,
/// resolve environment/image, resolve sandbox, attach, enqueue.
async fn schedule_single_task(
    pool: &PgPool,
    queue: &TaskQueue,
    bridge_store: &dyn BridgeStore,
    task_dispatcher: &dyn crate::kernel::ha::TaskDispatcher,
    config: &JoySafeterConfig,
    resolver: &SandboxResolver,
    task_id: TaskId,
    agent_id: Option<AgentId>,
    mut session_id: Option<SessionId>,
    project_id: Option<ProjectId>,
) -> anyhow::Result<()> {
    // --- Resolve agent ---
    let agent = match agent_id {
        Some(aid) => queries::get_agent(pool, aid).await?,
        None => None,
    };

    let agent = match agent {
        Some(a) => a,
        None => {
            mark_terminal_task_and_session_idle(
                pool,
                task_id,
                session_id,
                "failed",
                "Agent not found",
                json!({"type": "error", "message": "Agent not found"}),
            )
            .await;
            return Ok(());
        }
    };

    // --- Check if agent is archived ---
    // Query the full agent record to check archived_at
    let is_archived: Option<(Option<chrono::DateTime<chrono::Utc>>,)> =
        sqlx::query_as("SELECT archived_at FROM joysafeter_agents WHERE id = $1")
            .bind(agent.id)
            .fetch_optional(pool)
            .await?;

    if let Some((Some(_archived_at),)) = is_archived {
        warn!(
            agent_id = %agent.id,
            task_id = %task_id,
            "Agent is archived, cancelling task"
        );
        mark_terminal_task_and_session_idle(
            pool,
            task_id,
            session_id,
            "cancelled",
            "Agent is archived",
            json!({"type": "cancelled"}),
        )
        .await;
        return Ok(());
    }

    // --- Auto-create session if needed ---
    if session_id.is_none() {
        let project_id =
            project_id.ok_or_else(|| anyhow::anyhow!("scheduler task project is required"))?;
        let credential_store = CredentialStore::new(pool.clone());
        let Some(new_session) = snapshot::create_scheduler_session(
            pool,
            &credential_store,
            snapshot::SchedulerSnapshotCommand {
                task_id,
                agent_id: agent.id,
                project_id,
            },
        )
        .await?
        else {
            info!(task_id = %task_id, "Task left scheduling before auto-session attach, skipping");
            return Ok(());
        };
        session_id = Some(new_session.id);

        info!(
            task_id = %task_id,
            session_id = %new_session.id,
            "Auto-created session for task"
        );
    }

    // --- Resolve engine_kind → image ---
    let engine_kind = agent.engine_kind.as_deref().unwrap_or("claude");
    let resolved_image = config.image_for_provider(engine_kind)?;

    let session_id =
        session_id.ok_or_else(|| anyhow::anyhow!("resolved task session is missing"))?;
    let mut generation_retries = 0;
    let sandbox_db_id = loop {
        // --- Resolve sandbox through the full provider-backed resolver ---
        // The resolver builds the effective Python-compatible context itself:
        // session/agent environment, model credential, environment image, and networking.
        let resolved_sandbox = match resolver
            .resolve(task_id, Some(session_id), Some(agent.id), project_id)
            .await
        {
            Ok(resolved) => resolved,
            Err(error) if should_retry_generation_change(&error, generation_retries) => {
                generation_retries += 1;
                warn!(
                    task_id = %task_id,
                    retry = generation_retries,
                    "Runtime generation changed during sandbox resolution; retrying immediately"
                );
                continue;
            }
            Err(error) => return Err(error),
        };

        // --- Terminal status re-check ---
        let current_task = queries::get_task(pool, task_id).await?;
        if let Some(ref task) = current_task {
            if let Some(status) = crate::db::models::TaskStatus::from_str(&task.status) {
                if status.is_terminal() {
                    info!(task_id = %task_id, "Task became terminal before enqueue, skipping");
                    return Ok(());
                }
            }
        }

        // --- Attach sandbox (CAS: only if still scheduling) ---
        match queries::attach_sandbox_to_task_guarded(
            pool,
            task_id,
            resolved_sandbox.sandbox_id,
            session_id,
            project_id,
            resolved_sandbox.runtime_config_generation,
        )
        .await
        {
            Ok(()) => break resolved_sandbox.sandbox_id,
            Err(error) => {
                let error = anyhow::Error::new(error);
                if should_retry_generation_change(&error, generation_retries) {
                    generation_retries += 1;
                    warn!(
                        task_id = %task_id,
                        retry = generation_retries,
                        "Runtime generation changed before task attachment; retrying immediately"
                    );
                    continue;
                }

                if matches!(
                    error.downcast_ref::<RuntimeFreshnessError>(),
                    Some(RuntimeFreshnessError::Conflict(_))
                ) {
                    match queries::get_task(pool, task_id).await? {
                        None => return Ok(()),
                        Some(task) if task.status != "scheduling" => return Ok(()),
                        Some(task) if task.sandbox_id == Some(resolved_sandbox.sandbox_id) => {
                            break resolved_sandbox.sandbox_id;
                        }
                        Some(_) => {}
                    }
                }

                return Err(error);
            }
        }
    };

    // --- Push sandbox wakeup ---
    queue.push(sandbox_db_id, task_id).await?;

    // --- Notify bridge if connected ---
    if let Some(bridge) = bridge_store.get_by_db_id(sandbox_db_id) {
        // Bridge is local — notify directly (zero latency)
        bridge.task_available.notify_one();
    } else {
        // Bridge on another instance — send wakeup via TaskDispatcher (Redis inbox)
        if let Err(e) = task_dispatcher
            .dispatch_command(
                sandbox_db_id,
                crate::kernel::ha::DispatchCommand::TaskWakeup,
            )
            .await
        {
            // Non-fatal: the idle_wait polling in multi_task_loop will pick it up
            debug!(
                sandbox_id = %sandbox_db_id,
                "Cross-instance task wakeup failed (idle poll will recover): {e}"
            );
        }
    }

    info!(
        task_id = %task_id,
        sandbox_id = %sandbox_db_id,
        image = %resolved_image,
        "Task scheduled to sandbox"
    );

    Ok(())
}

/// Returns a stable machine code when the scheduling error is a permanent
/// credential-resolution failure (corrupt/unsupported/mismatched material that
/// can never succeed on retry). Transient failures (resolver timeouts, Docker
/// hiccups, transient DB errors) return `None` and keep normal retry behavior.
///
/// The `.context(...)` wrappers used at the credential error sites preserve the
/// original type, so `downcast_ref` still recovers the `CredentialRuntimeError`.
fn permanent_scheduling_failure_code(err: &anyhow::Error) -> Option<&'static str> {
    if let Some(credential_error) = err.downcast_ref::<CredentialRuntimeError>() {
        return Some(credential_error.contract_code());
    }

    match err.downcast_ref::<RuntimeFreshnessError>() {
        Some(RuntimeFreshnessError::RuntimeRestartRequired { .. }) => {
            Some("runtime_restart_required")
        }
        Some(RuntimeFreshnessError::SessionBindingInvalid { .. }) => {
            Some("session_binding_invalid")
        }
        _ => None,
    }
}

fn should_retry_generation_change(error: &anyhow::Error, retries_completed: usize) -> bool {
    retries_completed < GENERATION_CHANGE_IMMEDIATE_RETRIES
        && matches!(
            error.downcast_ref::<RuntimeFreshnessError>(),
            Some(RuntimeFreshnessError::GenerationChanged { .. })
        )
}

async fn handle_scheduling_failure(
    pool: &PgPool,
    _queue: &TaskQueue,
    task_id: TaskId,
    reason: &str,
    permanent_code: Option<&str>,
) {
    let task = match queries::get_task(pool, task_id).await {
        Ok(Some(task)) => task,
        Ok(None) => {
            warn!(task_id = %task_id, "Scheduling failure ignored because task no longer exists");
            return;
        }
        Err(e) => {
            error!(task_id = %task_id, error = %e, "Failed to load task after scheduling failure");
            return;
        }
    };

    if task.status != "scheduling" {
        debug!(task_id = %task_id, status = task.status, "Scheduling failure ignored because task left scheduling");
        return;
    }

    if let Some(sandbox_id) = task.sandbox_id {
        let _ = queries::complete_sandbox_task(pool, sandbox_id).await;
    }

    // Permanent credential failures can never succeed on retry. Fail fast to a
    // terminal state carrying the machine code instead of burning retries while
    // the UI shows a misleading "rescheduling" status.
    if permanent_code.is_none() && task.retry_count < task.max_retries {
        let next_retry_count = task.retry_count + 1;
        let backoff = scheduling_retry_backoff(next_retry_count);
        match queries::increment_scheduling_retry_keep_scheduling(
            pool,
            task_id,
            task.retry_count,
            backoff.as_secs() as i64,
            classify_scheduling_error(reason),
            reason,
        )
        .await
        {
            Ok(true) => {
                if let Some(session_id) = task.session_id {
                    let stop_reason = json!({"type": "sandbox_failed"});
                    let payload = json!({
                        "task_id": task_id.to_string(),
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
                            task_id = %task_id,
                            session_id = %session_id,
                            error = %e,
                            "Failed to persist scheduler rescheduling status"
                        );
                    }
                }
                match queries::release_scheduling_retry_to_pending(pool, task_id, next_retry_count)
                    .await
                {
                    Ok(true) => debug!(
                        task_id = %task_id,
                        retry = next_retry_count,
                        backoff_seconds = backoff.as_secs(),
                        "Scheduling retry persisted with durable DB backoff"
                    ),
                    Ok(false) => {
                        warn!(task_id = %task_id, "Scheduling retry release skipped due to CAS conflict")
                    }
                    Err(e) => {
                        error!(task_id = %task_id, error = %e, "Failed to release scheduling retry after persisting backoff")
                    }
                }
            }
            Ok(false) => {
                warn!(task_id = %task_id, "Scheduling retry skipped due to CAS conflict");
            }
            Err(e) => {
                error!(task_id = %task_id, error = %e, "Failed to retry task after scheduling failure");
            }
        }
        return;
    }

    let stop_reason = match permanent_code {
        Some(code) => json!({"type": "error", "message": reason, "code": code}),
        None => json!({"type": "error", "message": reason}),
    };
    mark_terminal_task_and_session_idle(
        pool,
        task_id,
        task.session_id,
        "failed",
        reason,
        stop_reason,
    )
    .await;
}

fn scheduling_retry_backoff(retry_count: i32) -> Duration {
    let exponent = retry_count.saturating_sub(1).clamp(0, 4) as u32;
    let seconds = SCHEDULING_RETRY_BASE_BACKOFF.as_secs() * 2u64.saturating_pow(exponent);
    Duration::from_secs(seconds.min(SCHEDULING_RETRY_MAX_BACKOFF.as_secs()))
}

fn classify_scheduling_error(reason: &str) -> &'static str {
    if reason.contains("Envoy NACK") || reason.contains("NACK'd xDS") {
        "envoy_nack"
    } else if reason.contains("Envoy") || reason.contains("socket") {
        "envoy_setup"
    } else if reason.contains("Storage volume") || reason.contains("mount") {
        "storage_mount"
    } else if reason.contains("Docker") || reason.contains("container") {
        "sandbox_provider"
    } else {
        "schedule_error"
    }
}

async fn mark_terminal_task_and_session_idle(
    pool: &PgPool,
    task_id: TaskId,
    session_id: Option<SessionId>,
    task_status: &str,
    reason: &str,
    stop_reason: Value,
) {
    match queries::transition_task_cas(pool, task_id, "scheduling", task_status, Some(reason), None)
        .await
    {
        Ok(true) => {
            if let Some(session_id) = session_id {
                let payload = json!({
                    "task_id": task_id.to_string(),
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
                        task_id = %task_id,
                        session_id = %session_id,
                        error = %e,
                        "Failed to persist scheduler idle status"
                    );
                }
            }
        }
        Ok(false) => {
            warn!(task_id = %task_id, status = task_status, "Scheduler terminal task transition skipped");
        }
        Err(e) => {
            error!(task_id = %task_id, status = task_status, error = %e, "Failed to mark scheduler task terminal");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ids::{EnvironmentId, OrganizationId, SandboxId};
    use crate::kernel::sandbox_bridge::BridgeRegistry;
    use crate::sandbox::provider::{SandboxCreateConfig, SandboxProvider, SandboxStatus};
    use sqlx::postgres::PgPoolOptions;
    use std::env;
    use uuid::Uuid;

    fn database_url() -> Option<String> {
        env::var("JOYSAFETER_TEST_DATABASE_URL")
            .ok()
            .or_else(|| env::var("DATABASE_URL").ok())
            .map(|url| url.replace("postgresql+asyncpg://", "postgres://"))
    }

    async fn test_pool() -> Option<PgPool> {
        let Some(url) = database_url() else {
            eprintln!("skipping real Postgres scheduler test: DATABASE_URL is not set");
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

    struct NeverProvider;

    #[async_trait::async_trait]
    impl SandboxProvider for NeverProvider {
        async fn create(&self, _config: &SandboxCreateConfig) -> anyhow::Result<String> {
            anyhow::bail!("test provider must not be invoked")
        }

        async fn start(&self, _external_id: &str) -> anyhow::Result<()> {
            anyhow::bail!("test provider must not be invoked")
        }

        async fn stop(&self, _external_id: &str) -> anyhow::Result<()> {
            anyhow::bail!("test provider must not be invoked")
        }

        async fn destroy(&self, _external_id: &str) -> anyhow::Result<()> {
            anyhow::bail!("test provider must not be invoked")
        }

        async fn status(&self, _external_id: &str) -> anyhow::Result<SandboxStatus> {
            anyhow::bail!("test provider must not be invoked")
        }

        async fn exec(&self, _external_id: &str, _cmd: &[&str]) -> anyhow::Result<String> {
            anyhow::bail!("test provider must not be invoked")
        }

        fn provider_name(&self) -> &'static str {
            "never"
        }
    }

    async fn create_scheduler_agent(pool: &PgPool, unique: &str) -> AgentId {
        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        sqlx::query(
            r#"
            INSERT INTO joysafeter_agents (
                id, name, engine_kind, model, system_prompt, env, mcp_servers,
                skills, tools, agents, commands, permission_mode, metadata,
                multiagent, version
            )
            VALUES (
                $1, $2, 'claude', $3, 'scheduler failure system', '{}'::jsonb, '[]'::jsonb,
                '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                'bypassPermissions', '{}'::jsonb, NULL, 1
            )
            "#,
        )
        .bind(agent_id)
        .bind(format!("scheduler-failure-agent-{unique}"))
        .bind(json!({"id": "scheduler-failure-model"}))
        .execute(pool)
        .await
        .expect("insert scheduler failure agent");
        agent_id
    }

    async fn create_scheduler_session(
        pool: &PgPool,
        agent_id: Option<AgentId>,
        status: &str,
    ) -> SessionId {
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        queries::create_session(pool, session_id, agent_id, None, None, None)
            .await
            .expect("create scheduler failure session");
        sqlx::query("UPDATE joysafeter_sessions SET status = $2 WHERE id = $1")
            .bind(session_id)
            .bind(status)
            .execute(pool)
            .await
            .expect("set scheduler failure session status");
        session_id
    }

    async fn create_scheduler_task(
        pool: &PgPool,
        agent_id: Option<AgentId>,
        session_id: SessionId,
        status: &str,
        retry_count: i32,
        max_retries: i32,
        sandbox_id: Option<SandboxId>,
    ) -> TaskId {
        let task_id = TaskId::from_uuid(Uuid::now_v7());
        sqlx::query(
            r#"
            INSERT INTO joysafeter_tasks (
                id, agent_id, chat_session_id, sandbox_id, status, prompt, output,
                timeout_sec, retry_count, max_retries
            )
            VALUES ($1, $2, $3, $4, $5, 'scheduler failure prompt', '', 7200, $6, $7)
            "#,
        )
        .bind(task_id)
        .bind(agent_id)
        .bind(session_id)
        .bind(sandbox_id)
        .bind(status)
        .bind(retry_count)
        .bind(max_retries)
        .execute(pool)
        .await
        .expect("insert scheduler failure task");
        task_id
    }

    async fn create_running_sandbox(
        pool: &PgPool,
        session_id: SessionId,
        task_id: TaskId,
    ) -> SandboxId {
        let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
        queries::create_sandbox(
            pool,
            sandbox_id,
            &format!("scheduler-failure-sandbox-{sandbox_id}"),
            "test",
            "joysafeter/test:latest",
            Some(session_id),
            None,
            None,
            Some(&json!({})),
        )
        .await
        .expect("create scheduler failure sandbox");
        queries::transition_sandbox_cas(pool, sandbox_id, "creating", "idle")
            .await
            .expect("transition sandbox idle");
        queries::transition_sandbox_cas(pool, sandbox_id, "idle", "running")
            .await
            .expect("transition sandbox running");
        sqlx::query("UPDATE joysafeter_sandboxes SET last_task_id = $2 WHERE id = $1")
            .bind(sandbox_id)
            .bind(task_id)
            .execute(pool)
            .await
            .expect("attach last task to sandbox");
        sandbox_id
    }

    async fn cleanup_scheduler_rows(
        pool: &PgPool,
        task_id: TaskId,
        session_id: SessionId,
        agent_id: Option<AgentId>,
        sandbox_id: Option<SandboxId>,
    ) {
        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(pool)
            .await;
        if let Some(sandbox_id) = sandbox_id {
            let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
                .bind(sandbox_id)
                .execute(pool)
                .await;
        }
        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(pool)
            .await;
        if let Some(agent_id) = agent_id {
            let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
                .bind(agent_id)
                .execute(pool)
                .await;
        }
    }

    async fn scheduler_noop_runtime(
        pool: &PgPool,
    ) -> (
        TaskQueue,
        Arc<dyn BridgeStore>,
        Arc<dyn crate::kernel::ha::TaskDispatcher>,
        JoySafeterConfig,
        SandboxResolver,
    ) {
        let queue = test_queue();
        let bridge_store: Arc<dyn BridgeStore> = Arc::new(BridgeRegistry::new());
        let task_dispatcher: Arc<dyn crate::kernel::ha::TaskDispatcher> = Arc::new(
            crate::kernel::ha::LocalTaskDispatcher::new(bridge_store.clone()),
        );
        let config = JoySafeterConfig::from_env();
        let resolver = SandboxResolver::new(pool.clone(), Arc::new(NeverProvider), config.clone());
        (queue, bridge_store, task_dispatcher, config, resolver)
    }

    fn test_queue() -> TaskQueue {
        TaskQueue::new(redis::Client::open("redis://127.0.0.1:1/").expect("redis URL"))
    }

    #[test]
    fn scheduling_retry_backoff_is_bounded_exponential() {
        assert_eq!(scheduling_retry_backoff(0), Duration::from_secs(5));
        assert_eq!(scheduling_retry_backoff(1), Duration::from_secs(5));
        assert_eq!(scheduling_retry_backoff(2), Duration::from_secs(10));
        assert_eq!(scheduling_retry_backoff(3), Duration::from_secs(20));
        assert_eq!(scheduling_retry_backoff(4), Duration::from_secs(40));
        assert_eq!(scheduling_retry_backoff(5), Duration::from_secs(60));
        assert_eq!(scheduling_retry_backoff(99), Duration::from_secs(60));
    }

    #[test]
    fn permanent_failure_code_detects_credential_errors_through_context() {
        // Credential errors are wrapped with `.context(...)` at the origin sites;
        // downcast must still recover the typed error so we classify them permanent.
        let corrupt = anyhow::Error::new(CredentialRuntimeError::CorruptRecord)
            .context("invalid persisted agent snapshot model_credential_id \"old-key\"");
        assert_eq!(
            permanent_scheduling_failure_code(&corrupt),
            Some("corrupt_record")
        );

        let unsupported = anyhow::Error::new(CredentialRuntimeError::UnsupportedScheme);
        assert_eq!(
            permanent_scheduling_failure_code(&unsupported),
            Some("unsupported_scheme")
        );

        // Transient scheduling failures must NOT be classified permanent.
        let transient = anyhow::anyhow!("sandbox resolution timed out after 120s");
        assert_eq!(permanent_scheduling_failure_code(&transient), None);

        let restart_required = anyhow::Error::new(
            crate::kernel::runtime_freshness::RuntimeFreshnessError::RuntimeRestartRequired {
                sandbox_id: SandboxId::from_uuid(Uuid::now_v7()),
            },
        );
        assert_eq!(
            permanent_scheduling_failure_code(&restart_required),
            Some("runtime_restart_required")
        );

        let session_binding_invalid = anyhow::Error::new(
            crate::kernel::runtime_freshness::RuntimeFreshnessError::SessionBindingInvalid {
                session_id: SessionId::from_uuid(Uuid::now_v7()),
                reason: "inactive session",
            },
        );
        assert_eq!(
            permanent_scheduling_failure_code(&session_binding_invalid),
            Some("session_binding_invalid")
        );

        let generation_changed = anyhow::Error::new(
            crate::kernel::runtime_freshness::RuntimeFreshnessError::GenerationChanged {
                expected: 1,
                actual: 2,
            },
        );
        assert_eq!(permanent_scheduling_failure_code(&generation_changed), None);

        let cleanup_failed = anyhow::Error::new(
            crate::kernel::runtime_freshness::RuntimeFreshnessError::CleanupFailed(
                "provider cleanup failed".to_string(),
            ),
        );
        assert_eq!(permanent_scheduling_failure_code(&cleanup_failed), None);
    }

    #[test]
    fn only_generation_changes_receive_bounded_immediate_retries() {
        let generation_changed = anyhow::Error::new(
            crate::kernel::runtime_freshness::RuntimeFreshnessError::GenerationChanged {
                expected: 1,
                actual: 2,
            },
        );
        assert!(should_retry_generation_change(&generation_changed, 0));
        assert!(should_retry_generation_change(&generation_changed, 1));
        assert!(!should_retry_generation_change(&generation_changed, 2));

        let restart_required = anyhow::Error::new(
            crate::kernel::runtime_freshness::RuntimeFreshnessError::RuntimeRestartRequired {
                sandbox_id: SandboxId::from_uuid(Uuid::now_v7()),
            },
        );
        assert!(!should_retry_generation_change(&restart_required, 0));

        let conflict = anyhow::Error::new(
            crate::kernel::runtime_freshness::RuntimeFreshnessError::Conflict(
                "ownership changed".to_string(),
            ),
        );
        assert!(!should_retry_generation_change(&conflict, 0));

        let cleanup_failed = anyhow::Error::new(
            crate::kernel::runtime_freshness::RuntimeFreshnessError::CleanupFailed(
                "provider cleanup failed".to_string(),
            ),
        );
        assert!(!should_retry_generation_change(&cleanup_failed, 0));
    }

    #[tokio::test]
    async fn scheduler_auto_session_attach_skips_task_that_left_scheduling_without_leaking_session()
    {
        let Some(pool) = test_pool().await else {
            return;
        };

        let unique = Uuid::now_v7().simple().to_string();
        let agent_id = create_scheduler_agent(&pool, &unique).await;
        let task_id = TaskId::from_uuid(Uuid::now_v7());
        let organization_id = OrganizationId::new();
        let project_id = ProjectId::new();

        sqlx::query(
            "INSERT INTO joysafeter_organizations (id, name, slug, storage_used_bytes, departed_member_usage) VALUES ($1, $2, $3, 0, 0)",
        )
        .bind(&organization_id)
        .bind("Scheduler Stale Task Org")
        .bind(format!("scheduler-stale-task-org-{unique}"))
        .execute(&pool)
        .await
        .expect("insert stale task organization");
        sqlx::query(
            "INSERT INTO joysafeter_organization_projects (id, org_id, name, slug, is_default) VALUES ($1, $2, $3, $4, false)",
        )
        .bind(&project_id)
        .bind(&organization_id)
        .bind("Scheduler Stale Task Project")
        .bind(format!("scheduler-stale-task-project-{unique}"))
        .execute(&pool)
        .await
        .expect("insert stale task project");
        sqlx::query("UPDATE joysafeter_agents SET project_id = $2 WHERE id = $1")
            .bind(agent_id)
            .bind(&project_id)
            .execute(&pool)
            .await
            .expect("scope stale task agent");

        sqlx::query(
            r#"
            INSERT INTO joysafeter_tasks (
                id, agent_id, chat_session_id, project_id, status, prompt, output,
                timeout_sec, retry_count, max_retries
            )
            VALUES ($1, $2, NULL, $3, 'running', 'stale scheduler prompt', '', 7200, 0, 2)
            "#,
        )
        .bind(task_id)
        .bind(agent_id)
        .bind(&project_id)
        .execute(&pool)
        .await
        .expect("insert stale running task without session");

        let result = async {
            let (queue, bridge_store, task_dispatcher, config, resolver) =
                scheduler_noop_runtime(&pool).await;
            schedule_single_task(
                &pool,
                &queue,
                &*bridge_store,
                &*task_dispatcher,
                &config,
                &resolver,
                task_id,
                Some(agent_id),
                None,
                Some(project_id),
            )
            .await
            .expect("stale auto-session scheduling should be skipped");

            let task: (String, Option<SandboxId>) = sqlx::query_as(
                "SELECT status, chat_session_id FROM joysafeter_tasks WHERE id = $1",
            )
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load stale task after auto-session skip");
            assert_eq!(task.0, "running");
            assert_eq!(task.1, None);

            let session_count: i64 =
                sqlx::query_scalar("SELECT COUNT(*) FROM joysafeter_sessions WHERE agent_id = $1")
                    .bind(agent_id)
                    .fetch_one(&pool)
                    .await
                    .expect("count leaked auto-created sessions");
            assert_eq!(session_count, 0);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_organization_projects WHERE id = $1")
            .bind(&project_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_organizations WHERE id = $1")
            .bind(&organization_id)
            .execute(&pool)
            .await;
        result
    }

    #[tokio::test]
    async fn scheduler_failure_retry_marks_session_rescheduling_and_releases_sandbox() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let unique = Uuid::now_v7().simple().to_string();
        let agent_id = create_scheduler_agent(&pool, &unique).await;
        let session_id = create_scheduler_session(&pool, Some(agent_id), "running").await;
        let task_id =
            create_scheduler_task(&pool, Some(agent_id), session_id, "scheduling", 0, 2, None)
                .await;
        let sandbox_id = create_running_sandbox(&pool, session_id, task_id).await;
        sqlx::query("UPDATE joysafeter_tasks SET sandbox_id = $2 WHERE id = $1")
            .bind(task_id)
            .bind(sandbox_id)
            .execute(&pool)
            .await
            .expect("attach sandbox to task");

        let result = async {
            handle_scheduling_failure(&pool, &test_queue(), task_id, "resolver failed", None).await;

            let task: (String, i32, Option<Uuid>, i32, Option<chrono::DateTime<chrono::Utc>>) = sqlx::query_as(
                "SELECT status, retry_count, sandbox_id, schedule_attempts, next_schedule_at FROM joysafeter_tasks WHERE id = $1",
            )
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load retried task");
            assert_eq!(task.0, "pending");
            assert_eq!(task.1, 1);
            assert_eq!(task.2, None);
            assert_eq!(task.3, 1);
            assert!(task.4.is_some());

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

            let sandbox: (String, Option<TaskId>) = sqlx::query_as(
                "SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load released sandbox");
            assert_eq!(sandbox.0, "idle");
            assert_eq!(sandbox.1, None);
        }
        .await;

        cleanup_scheduler_rows(&pool, task_id, session_id, Some(agent_id), Some(sandbox_id)).await;
        result
    }

    #[tokio::test]
    async fn scheduler_failure_ignores_task_that_already_left_scheduling() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let unique = Uuid::now_v7().simple().to_string();
        let agent_id = create_scheduler_agent(&pool, &unique).await;
        let session_id = create_scheduler_session(&pool, Some(agent_id), "running").await;
        let task_id =
            create_scheduler_task(&pool, Some(agent_id), session_id, "running", 0, 2, None).await;
        let sandbox_id = create_running_sandbox(&pool, session_id, task_id).await;
        sqlx::query("UPDATE joysafeter_tasks SET sandbox_id = $2 WHERE id = $1")
            .bind(task_id)
            .bind(sandbox_id)
            .execute(&pool)
            .await
            .expect("attach running sandbox to task");

        let result = async {
            handle_scheduling_failure(&pool, &test_queue(), task_id, "late resolver failure", None)
                .await;

            let task: (String, i32, Option<SandboxId>, Option<String>) = sqlx::query_as(
                "SELECT status, retry_count, sandbox_id, error FROM joysafeter_tasks WHERE id = $1",
            )
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load running task after stale scheduler failure");
            assert_eq!(task.0, "running");
            assert_eq!(task.1, 0);
            assert_eq!(task.2, Some(sandbox_id));
            assert_eq!(task.3, None);

            let session: (String, Option<Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load session after stale scheduler failure");
            assert_eq!(session.0, "running");
            assert_eq!(session.1, None);

            let status_events: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type LIKE 'session.status_%'
                "#,
            )
            .bind(session_id)
            .fetch_one(&pool)
            .await
            .expect("count stale scheduler status events");
            assert_eq!(status_events, 0);

            let sandbox: (String, Option<TaskId>) = sqlx::query_as(
                "SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load sandbox after stale scheduler failure");
            assert_eq!(sandbox.0, "running");
            assert_eq!(sandbox.1, Some(task_id));
        }
        .await;

        cleanup_scheduler_rows(&pool, task_id, session_id, Some(agent_id), Some(sandbox_id)).await;
        result
    }

    #[tokio::test]
    async fn scheduler_failure_exhausted_marks_session_idle() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let unique = Uuid::now_v7().simple().to_string();
        let agent_id = create_scheduler_agent(&pool, &unique).await;
        let session_id = create_scheduler_session(&pool, Some(agent_id), "rescheduling").await;
        let task_id =
            create_scheduler_task(&pool, Some(agent_id), session_id, "scheduling", 2, 2, None)
                .await;

        let result = async {
            handle_scheduling_failure(&pool, &test_queue(), task_id, "resolver exhausted", None)
                .await;

            let task: (String, i32, Option<String>) = sqlx::query_as(
                "SELECT status, retry_count, error FROM joysafeter_tasks WHERE id = $1",
            )
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load exhausted task");
            assert_eq!(task.0, "failed");
            assert_eq!(task.1, 2);
            assert_eq!(task.2.as_deref(), Some("resolver exhausted"));

            let stop_reason = json!({"type": "error", "message": "resolver exhausted"});
            let session: (String, Option<Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load idle session");
            assert_eq!(session.0, "idle");
            assert_eq!(session.1, Some(stop_reason.clone()));

            let event: (String, Value) = sqlx::query_as(
                r#"
                SELECT event_type, payload
                FROM joysafeter_session_events
                WHERE session_id = $1
                ORDER BY seq DESC
                LIMIT 1
                "#,
            )
            .bind(session_id)
            .fetch_one(&pool)
            .await
            .expect("load idle event");
            assert_eq!(event.0, "session.status_idle");
            assert_eq!(
                event.1,
                json!({"task_id": task_id.to_string(), "stop_reason": stop_reason})
            );
        }
        .await;

        cleanup_scheduler_rows(&pool, task_id, session_id, Some(agent_id), None).await;
        result
    }

    #[tokio::test]
    async fn scheduler_permanent_credential_failure_fails_fast_without_retry() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let unique = Uuid::now_v7().simple().to_string();
        let agent_id = create_scheduler_agent(&pool, &unique).await;
        let session_id = create_scheduler_session(&pool, Some(agent_id), "running").await;
        // retry_count 0 of max_retries 2: a transient failure would reschedule,
        // but a permanent credential failure must terminate immediately.
        let task_id =
            create_scheduler_task(&pool, Some(agent_id), session_id, "scheduling", 0, 2, None)
                .await;

        let result = async {
            handle_scheduling_failure(
                &pool,
                &test_queue(),
                task_id,
                "credential record is corrupt",
                Some("corrupt_record"),
            )
            .await;

            let task: (String, i32, Option<String>) = sqlx::query_as(
                "SELECT status, retry_count, error FROM joysafeter_tasks WHERE id = $1",
            )
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load permanently failed task");
            // Failed immediately, no retry consumed, no rescheduling detour.
            assert_eq!(task.0, "failed");
            assert_eq!(task.1, 0);
            assert_eq!(task.2.as_deref(), Some("credential record is corrupt"));

            let stop_reason = json!({
                "type": "error",
                "message": "credential record is corrupt",
                "code": "corrupt_record"
            });
            let session: (String, Option<Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load idle session");
            assert_eq!(session.0, "idle");
            assert_eq!(session.1, Some(stop_reason.clone()));

            // The terminal event carries the machine code so the UI can surface
            // a localized reason instead of a silent "session idle".
            let event: (String, Value) = sqlx::query_as(
                r#"
                SELECT event_type, payload
                FROM joysafeter_session_events
                WHERE session_id = $1
                ORDER BY seq DESC
                LIMIT 1
                "#,
            )
            .bind(session_id)
            .fetch_one(&pool)
            .await
            .expect("load terminal event");
            assert_eq!(event.0, "session.status_idle");
            assert_eq!(
                event.1,
                json!({"task_id": task_id.to_string(), "stop_reason": stop_reason})
            );

            // No rescheduling status event was emitted on the way to failure.
            let rescheduling_events: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_rescheduling'
                "#,
            )
            .bind(session_id)
            .fetch_one(&pool)
            .await
            .expect("count rescheduling events");
            assert_eq!(rescheduling_events, 0);
        }
        .await;

        cleanup_scheduler_rows(&pool, task_id, session_id, Some(agent_id), None).await;
        result
    }

    #[tokio::test]
    async fn scheduler_deleted_agent_marks_existing_session_idle() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let unique = Uuid::now_v7().simple().to_string();
        let agent_id = create_scheduler_agent(&pool, &unique).await;
        sqlx::query("UPDATE joysafeter_agents SET deleted_at = NOW() WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await
            .expect("soft-delete scheduler agent");
        let session_id = create_scheduler_session(&pool, Some(agent_id), "running").await;
        let task_id =
            create_scheduler_task(&pool, Some(agent_id), session_id, "scheduling", 0, 2, None)
                .await;
        let (queue, bridge_store, task_dispatcher, config, resolver) =
            scheduler_noop_runtime(&pool).await;

        let result = async {
            schedule_single_task(
                &pool,
                &queue,
                &*bridge_store,
                &*task_dispatcher,
                &config,
                &resolver,
                task_id,
                Some(agent_id),
                Some(session_id),
                None,
            )
            .await
            .expect("missing agent is handled as terminal task");

            let task: (String, Option<String>) =
                sqlx::query_as("SELECT status, error FROM joysafeter_tasks WHERE id = $1")
                    .bind(task_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load missing-agent task");
            assert_eq!(task.0, "failed");
            assert_eq!(task.1.as_deref(), Some("Agent not found"));

            let session: (String, Option<Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load missing-agent session");
            assert_eq!(session.0, "idle");
            assert_eq!(
                session.1,
                Some(json!({"type": "error", "message": "Agent not found"}))
            );
        }
        .await;

        cleanup_scheduler_rows(&pool, task_id, session_id, Some(agent_id), None).await;
        result
    }

    #[tokio::test]
    async fn scheduler_archived_agent_cancels_task_and_idles_session() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let unique = Uuid::now_v7().simple().to_string();
        let agent_id = create_scheduler_agent(&pool, &unique).await;
        sqlx::query("UPDATE joysafeter_agents SET archived_at = NOW() WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await
            .expect("archive scheduler agent");
        let session_id = create_scheduler_session(&pool, Some(agent_id), "running").await;
        let task_id =
            create_scheduler_task(&pool, Some(agent_id), session_id, "scheduling", 0, 2, None)
                .await;
        let (queue, bridge_store, task_dispatcher, config, resolver) =
            scheduler_noop_runtime(&pool).await;

        let result = async {
            schedule_single_task(
                &pool,
                &queue,
                &*bridge_store,
                &*task_dispatcher,
                &config,
                &resolver,
                task_id,
                Some(agent_id),
                Some(session_id),
                None,
            )
            .await
            .expect("archived agent is handled as cancelled task");

            let task: (String, Option<String>) =
                sqlx::query_as("SELECT status, error FROM joysafeter_tasks WHERE id = $1")
                    .bind(task_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load archived-agent task");
            assert_eq!(task.0, "cancelled");
            assert_eq!(task.1.as_deref(), Some("Agent is archived"));

            let session: (String, Option<Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load archived-agent session");
            assert_eq!(session.0, "idle");
            assert_eq!(session.1, Some(json!({"type": "cancelled"})));
        }
        .await;

        cleanup_scheduler_rows(&pool, task_id, session_id, Some(agent_id), None).await;
        result
    }

    #[tokio::test]
    async fn scheduler_auto_session_snapshot_includes_environment_before_live_mutation() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let environment_id = EnvironmentId::from_uuid(Uuid::now_v7());
        let task_id = TaskId::from_uuid(Uuid::now_v7());
        let unique = agent_id.as_uuid().simple().to_string();

        async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_environments
                    (id, name, description, config, image_tag, image_version)
                VALUES ($1, $2, '', $3, 'joysafeter/scheduler:before', 11)
                "#,
            )
            .bind(environment_id)
            .bind(format!("scheduler-env-{unique}"))
            .bind(json!({
                "setup_commands": ["echo scheduler-before"],
                "network": {"mode": "egress"}
            }))
            .execute(&pool)
            .await
            .expect("insert environment");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (
                    id, name, engine_kind, model, system_prompt, env, mcp_servers,
                    skills, tools, agents, commands, permission_mode, metadata,
                    multiagent, version, environment_id
                )
                VALUES (
                    $1, $2, 'claude', $3, 'scheduler snapshot system', $4, $5,
                    '[]'::jsonb, $6, '[]'::jsonb, '[]'::jsonb,
                    'bypassPermissions', '{}'::jsonb, NULL, 3, $7
                )
                "#,
            )
            .bind(agent_id)
            .bind(format!("scheduler-agent-{unique}"))
            .bind(json!({"id": "scheduler-snapshot-model"}))
            .bind(json!({"SCHEDULER_ENV": "before"}))
            .bind(json!([{"name": "scheduler-mcp", "url": "https://mcp.before.test"}]))
            .bind(json!([{"name": "scheduler-tool"}]))
            .bind(environment_id)
            .execute(&pool)
            .await
            .expect("insert agent");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_tasks (
                    id, agent_id, status, prompt, output, timeout_sec,
                    retry_count, max_retries
                )
                VALUES ($1, $2, 'scheduling', 'snapshot test', '', 7200, 0, 3)
                "#,
            )
            .bind(task_id)
            .bind(agent_id)
            .execute(&pool)
            .await
            .expect("insert scheduling task");
            let store = CredentialStore::new(pool.clone());
            let organization_id = OrganizationId::new();
            let project_id = ProjectId::new();
            sqlx::query(
                "INSERT INTO joysafeter_organizations (id, name, slug, storage_used_bytes, departed_member_usage) VALUES ($1, $2, $3, 0, 0)",
            )
            .bind(&organization_id)
            .bind("Scheduler Snapshot Test Org")
            .bind(format!("scheduler-snapshot-test-org-{unique}"))
            .execute(&pool)
            .await
            .expect("insert scheduler test organization");
            sqlx::query(
                "INSERT INTO joysafeter_organization_projects (id, org_id, name, slug, is_default) VALUES ($1, $2, $3, $4, false)",
            )
            .bind(&project_id)
            .bind(&organization_id)
            .bind("Scheduler Snapshot Test Project")
            .bind(format!("scheduler-snapshot-test-project-{unique}"))
            .execute(&pool)
            .await
            .expect("insert scheduler test project");
            sqlx::query("UPDATE joysafeter_agents SET project_id = $2 WHERE id = $1")
                .bind(agent_id)
                .bind(&project_id)
                .execute(&pool)
                .await
                .expect("scope scheduler test agent");
            sqlx::query("UPDATE joysafeter_environments SET project_id = $2 WHERE id = $1")
                .bind(environment_id)
                .bind(&project_id)
                .execute(&pool)
                .await
                .expect("scope scheduler test environment");
            sqlx::query("UPDATE joysafeter_tasks SET project_id = $2 WHERE id = $1")
                .bind(task_id)
                .bind(&project_id)
                .execute(&pool)
                .await
                .expect("scope scheduler test task");
            let session = snapshot::create_scheduler_session(
                &pool,
                &store,
                snapshot::SchedulerSnapshotCommand {
                    task_id,
                    agent_id,
                    project_id,
                },
            )
            .await
            .expect("create scheduler session")
            .expect("task remains scheduling");
            let session_id = session.id;

            sqlx::query(
                r#"
                UPDATE joysafeter_agents
                SET model = $2, system_prompt = 'mutated scheduler system', env = $3
                WHERE id = $1
                "#,
            )
            .bind(agent_id)
            .bind(json!({"id": "scheduler-mutated-model"}))
            .bind(json!({"SCHEDULER_ENV": "after"}))
            .execute(&pool)
            .await
            .expect("mutate live agent");

            sqlx::query(
                r#"
                UPDATE joysafeter_environments
                SET config = $2, image_tag = 'joysafeter/scheduler:after', image_version = 12
                WHERE id = $1
                "#,
            )
            .bind(environment_id)
            .bind(json!({
                "setup_commands": ["echo scheduler-after"],
                "network": {"mode": "blocked"}
            }))
            .execute(&pool)
            .await
            .expect("mutate live environment");

            let stored = sqlx::query_as::<_, crate::db::models::JoySafeterSession>(
                "SELECT * FROM joysafeter_sessions WHERE id = $1",
            )
            .bind(session_id)
            .fetch_one(&pool)
            .await
            .expect("load created session");

            assert_eq!(stored.environment_id, Some(environment_id));
            let stored_snapshot = stored.agent_snapshot.expect("session snapshot");
            assert_eq!(
                stored_snapshot.get("schema").and_then(Value::as_str),
                Some("joysafeter.agent_execution_snapshot.v2")
            );
            assert_eq!(
                stored_snapshot.get("model").and_then(Value::as_str),
                Some("scheduler-snapshot-model")
            );
            assert_eq!(
                stored_snapshot.get("system").and_then(Value::as_str),
                Some("scheduler snapshot system")
            );
            assert_eq!(
                stored_snapshot
                    .get("env")
                    .and_then(|env| env.get("SCHEDULER_ENV"))
                    .and_then(Value::as_str),
                Some("before")
            );
            assert_eq!(
                stored_snapshot
                    .get("environment")
                    .and_then(|environment| environment.get("config"))
                    .and_then(|config| config.get("setup_commands"))
                    .and_then(Value::as_array)
                    .and_then(|commands| commands.first())
                    .and_then(Value::as_str),
                Some("echo scheduler-before")
            );
            assert_eq!(
                stored_snapshot
                    .get("environment")
                    .and_then(|environment| environment.get("image_tag"))
                    .and_then(Value::as_str),
                Some("joysafeter/scheduler:before")
            );
            assert_eq!(
                stored_snapshot
                    .get("environment")
                    .and_then(|environment| environment.get("image_version"))
                    .and_then(Value::as_i64),
                Some(11)
            );
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE agent_id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_environments WHERE id = $1")
            .bind(environment_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_organization_projects WHERE id = $1")
            .bind(format!("scheduler-snapshot-test-project-{unique}"))
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_organizations WHERE id = $1")
            .bind(format!("scheduler-snapshot-test-org-{unique}"))
            .execute(&pool)
            .await;
    }
}
