use std::sync::Arc;
use std::time::Duration;

use serde_json::{json, Value};
use sqlx::PgPool;
use tokio::sync::Semaphore;
use tokio::task::JoinHandle;
use tokio::time::Instant;
use tracing::{debug, error, info, warn};
use uuid::Uuid;

use crate::config::JoySafeterConfig;
use crate::db::{
    models::{JoySafeterAgent, JoySafeterSession},
    queries,
};
use crate::egress::enforcer::EgressEnforcer;
use crate::kernel::queue::TaskQueue;
use crate::kernel::sandbox_bridge::BridgeRegistry;
use crate::kernel::sandbox_resolver::SandboxResolver;
use crate::sandbox::provider::SandboxProvider;

const QUEUE_POP_TIMEOUT: Duration = Duration::from_secs(1);
const DB_REPAIR_SWEEP_INTERVAL: Duration = Duration::from_secs(30);

#[derive(Debug, sqlx::FromRow)]
struct SchedulerEnvironmentSnapshot {
    id: Uuid,
    name: String,
    config: Value,
    image_tag: Option<String>,
    image_version: i32,
}

// Task scheduler — consumes Redis task candidates, claims them in DB, resolves
// sandboxes, and dispatches.
//
// Redis is the scheduling wakeup/candidate channel; the DB state transition is
// still authoritative. A bounded DB repair sweep recovers pending rows that
// predate the queue cutover or whose queue message was lost during an outage.

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
    bridge_registry: BridgeRegistry,
    provider: Arc<dyn SandboxProvider>,
    enforcer: Option<Arc<dyn EgressEnforcer>>,
    config: JoySafeterConfig,
) -> JoinHandle<()> {
    let resolver = Arc::new(SandboxResolver::new(
        pool.clone(),
        provider,
        enforcer,
        config.clone(),
    ));
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
            let mut admission_blocked = false;

            match queue.pop_from_global(QUEUE_POP_TIMEOUT).await {
                Ok(Some(task_id)) => {
                    match queries::claim_pending_task_by_id(
                        &pool,
                        task_id,
                        config.max_concurrent_tasks,
                    )
                    .await
                    {
                        Ok(queries::PendingTaskClaim::Claimed(task)) => tasks.push(task),
                        Ok(queries::PendingTaskClaim::AtCapacity) => {
                            admission_blocked = true;
                            if let Err(error) = queue.push_to_global(task_id).await {
                                warn!(task_id = %task_id, error = %error, "Failed to restore capacity-blocked task to global queue");
                            }
                        }
                        Ok(queries::PendingTaskClaim::NotPending) => debug!(
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
                        match queries::claim_pending_task_by_id(
                            &pool,
                            task_id,
                            config.max_concurrent_tasks,
                        )
                        .await
                        {
                            Ok(queries::PendingTaskClaim::Claimed(task)) => tasks.push(task),
                            Ok(queries::PendingTaskClaim::AtCapacity) => {
                                admission_blocked = true;
                                if let Err(error) = queue.push_to_global(task_id).await {
                                    warn!(task_id = %task_id, error = %error, "Failed to restore capacity-blocked task to global queue");
                                }
                                break;
                            }
                            Ok(queries::PendingTaskClaim::NotPending) => debug!(
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
                match queries::claim_pending_tasks(
                    &pool,
                    available_slots as i64,
                    config.max_concurrent_tasks,
                )
                .await
                {
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
                if admission_blocked {
                    tokio::time::sleep(Duration::from_millis(500)).await;
                }
                continue;
            }

            info!(count = tasks.len(), "Claimed tasks for scheduling");

            // Schedule each task concurrently
            for task in tasks {
                let pool = pool.clone();
                let queue = queue.clone();
                let bridge_registry = bridge_registry.clone();
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
                            &bridge_registry,
                            &config,
                            &resolver,
                            task_id,
                            task.agent_id,
                            task.session_id,
                            task.project_id.as_deref(),
                        ),
                    )
                    .await;

                    let result = match schedule_result {
                        Ok(inner) => inner,
                        Err(_) => Err(anyhow::anyhow!("sandbox resolution timed out after 120s")),
                    };

                    if let Err(e) = result {
                        error!(task_id = %task_id, "Failed to schedule task: {e}");
                        handle_scheduling_failure(&resolver_pool, &queue, task_id, &e.to_string())
                            .await;
                    }
                    drop(_sched_permit);
                });
            }

            if admission_blocked {
                tokio::time::sleep(Duration::from_millis(500)).await;
            }
        }
    })
}

/// Schedule a single task: resolve agent, create session if needed, inject secrets,
/// resolve environment/image, resolve sandbox, attach, enqueue.
async fn schedule_single_task(
    pool: &PgPool,
    queue: &TaskQueue,
    bridge_registry: &BridgeRegistry,
    config: &JoySafeterConfig,
    resolver: &SandboxResolver,
    task_id: Uuid,
    agent_id: Option<Uuid>,
    mut session_id: Option<Uuid>,
    project_id: Option<&str>,
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
        let agent_snapshot = build_agent_execution_snapshot(pool, &agent).await?;

        let Some(new_session) =
            create_session_and_attach_to_scheduling_task(pool, task_id, &agent, &agent_snapshot)
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
    let resolved_image = config.image_for_provider(engine_kind);

    // --- Resolve sandbox through the full provider-backed resolver ---
    // The resolver builds the effective Python-compatible context itself:
    // session/agent environment, secret_ref, environment image, and networking.
    let (sandbox_db_id, _external_id) = resolver
        .resolve(task_id, session_id, Some(agent.id), project_id)
        .await?;

    // --- Terminal status re-check ---
    let current_task = queries::get_task(pool, task_id).await?;
    if let Some(ref t) = current_task {
        if let Some(status) = crate::db::models::TaskStatus::from_str(&t.status) {
            if status.is_terminal() {
                info!(task_id = %task_id, "Task became terminal before enqueue, skipping");
                return Ok(());
            }
        }
    }

    // --- Attach sandbox (CAS: only if still scheduling) ---
    let attached = queries::attach_sandbox_to_task(pool, task_id, sandbox_db_id).await?;
    if !attached {
        info!(task_id = %task_id, "Task left scheduling before sandbox attach, skipping");
        return Ok(());
    }

    // --- Push sandbox wakeup ---
    queue.push(sandbox_db_id, task_id).await?;

    // --- Notify bridge if connected ---
    if let Some(bridge) = bridge_registry.get_by_db_id(sandbox_db_id) {
        bridge.task_available.notify_one();
    }

    info!(
        task_id = %task_id,
        sandbox_id = %sandbox_db_id,
        image = %resolved_image,
        "Task scheduled to sandbox"
    );

    Ok(())
}

async fn create_session_and_attach_to_scheduling_task(
    pool: &PgPool,
    task_id: Uuid,
    agent: &JoySafeterAgent,
    agent_snapshot: &Value,
) -> anyhow::Result<Option<JoySafeterSession>> {
    let mut tx = pool.begin().await?;
    let session_id = Uuid::now_v7();

    let session = sqlx::query_as::<_, JoySafeterSession>(
        r#"
        INSERT INTO joysafeter_sessions
            (id, agent_id, project_id, status, agent_snapshot, environment_ref, created_at, updated_at)
        VALUES ($1, $2, $3, 'idle', $4, $5, NOW(), NOW())
        RETURNING *
        "#,
    )
    .bind(session_id)
    .bind(agent.id)
    .bind(agent.project_id.as_deref())
    .bind(agent_snapshot)
    .bind(agent.environment_ref.as_deref())
    .fetch_one(&mut *tx)
    .await?;

    let attach_result = sqlx::query(
        r#"
        UPDATE joysafeter_tasks
        SET chat_session_id = $2,
            updated_at = NOW()
        WHERE id = $1
          AND status = 'scheduling'
          AND chat_session_id IS NULL
        "#,
    )
    .bind(task_id)
    .bind(session.id)
    .execute(&mut *tx)
    .await?;

    if attach_result.rows_affected() == 0 {
        tx.rollback().await?;
        return Ok(None);
    }

    tx.commit().await?;
    Ok(Some(session))
}

async fn handle_scheduling_failure(pool: &PgPool, queue: &TaskQueue, task_id: Uuid, reason: &str) {
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

    if task.retry_count < task.max_retries {
        match queries::increment_scheduling_retry(pool, task_id, task.retry_count).await {
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
                if let Err(e) = queue.push_to_global(task_id).await {
                    warn!(task_id = %task_id, error = %e, "Failed to re-enqueue task after scheduling retry");
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

    mark_terminal_task_and_session_idle(
        pool,
        task_id,
        task.session_id,
        "failed",
        reason,
        json!({"type": "error", "message": reason}),
    )
    .await;
}

async fn mark_terminal_task_and_session_idle(
    pool: &PgPool,
    task_id: Uuid,
    session_id: Option<Uuid>,
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

async fn build_agent_execution_snapshot(
    pool: &PgPool,
    agent: &JoySafeterAgent,
) -> anyhow::Result<Value> {
    let mut snapshot = json!({
        "schema": "joysafeter.agent_execution_snapshot.v1",
        "id": agent.id.to_string(),
        "version": agent.version,
        "name": agent.name.clone(),
        "engine_kind": agent.engine_kind.clone(),
        "description": agent.description.clone(),
        "model": agent.model.clone(),
        "system_prompt": agent.system_prompt.clone(),
        "metadata": agent.metadata.clone(),
        "env": agent.env.clone(),
        "tools": agent.tools.clone(),
        "skills": agent.skills.clone(),
        "agents": agent.agents.clone(),
        "commands": agent.commands.clone(),
        "mcp_servers": agent.mcp_configs.clone(),
        "mcp_configs": agent.mcp_configs.clone(),
        "permission_mode": agent.permission_mode.clone(),
        "multiagent": agent.multiagent.clone(),
        "environment_ref": agent.environment_ref.clone(),
        "secret_ref": agent.secret_ref.clone(),
    });

    if let Some(environment_ref) = agent.environment_ref.as_deref() {
        if let Some(environment) =
            load_environment_snapshot(pool, environment_ref, agent.project_id.as_deref()).await?
        {
            if let Some(object) = snapshot.as_object_mut() {
                object.insert(
                    "environment".to_string(),
                    json!({
                        "ref": environment_ref,
                        "id": environment.id.to_string(),
                        "name": environment.name,
                        "config": environment.config,
                        "image_tag": environment.image_tag,
                        "image_version": environment.image_version,
                    }),
                );
            }
        }
    }

    Ok(snapshot)
}

async fn load_environment_snapshot(
    pool: &PgPool,
    environment_ref: &str,
    project_id: Option<&str>,
) -> anyhow::Result<Option<SchedulerEnvironmentSnapshot>> {
    let normalized = environment_ref.trim();
    if normalized.is_empty() {
        return Ok(None);
    }

    if let Ok(environment_id) =
        Uuid::parse_str(normalized.strip_prefix("env_").unwrap_or(normalized))
    {
        return Ok(sqlx::query_as::<_, SchedulerEnvironmentSnapshot>(
            r#"
            SELECT id, name, config, image_tag, image_version
            FROM joysafeter_environments
            WHERE id = $1 AND deleted_at IS NULL
              AND ($2::text IS NULL OR project_id = $2)
            "#,
        )
        .bind(environment_id)
        .bind(project_id)
        .fetch_optional(pool)
        .await?);
    }

    Ok(sqlx::query_as::<_, SchedulerEnvironmentSnapshot>(
        r#"
        SELECT id, name, config, image_tag, image_version
        FROM joysafeter_environments
        WHERE name = $1 AND deleted_at IS NULL
          AND ($2::text IS NULL OR project_id = $2)
        "#,
    )
    .bind(normalized)
    .bind(project_id)
    .fetch_optional(pool)
    .await?)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sandbox::provider::{SandboxCreateConfig, SandboxProvider, SandboxStatus};
    use sqlx::postgres::PgPoolOptions;
    use std::env;

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

    async fn create_scheduler_agent(pool: &PgPool, unique: &str) -> Uuid {
        let agent_id = Uuid::now_v7();
        sqlx::query(
            r#"
            INSERT INTO joysafeter_agents (
                id, name, engine_kind, model, system_prompt, env, mcp_configs,
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

    async fn create_scheduler_session(pool: &PgPool, agent_id: Option<Uuid>, status: &str) -> Uuid {
        let session_id = Uuid::now_v7();
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
        agent_id: Option<Uuid>,
        session_id: Uuid,
        status: &str,
        retry_count: i32,
        max_retries: i32,
        sandbox_id: Option<Uuid>,
    ) -> Uuid {
        let task_id = Uuid::now_v7();
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

    async fn create_running_sandbox(pool: &PgPool, session_id: Uuid, task_id: Uuid) -> Uuid {
        let sandbox_id = Uuid::now_v7();
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
        queries::transition_sandbox(pool, sandbox_id, "idle")
            .await
            .expect("transition sandbox idle");
        queries::transition_sandbox(pool, sandbox_id, "running")
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
        task_id: Uuid,
        session_id: Uuid,
        agent_id: Option<Uuid>,
        sandbox_id: Option<Uuid>,
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
    ) -> (TaskQueue, BridgeRegistry, JoySafeterConfig, SandboxResolver) {
        let queue = test_queue();
        let bridge_registry = BridgeRegistry::new();
        let config = JoySafeterConfig::from_env();
        let resolver =
            SandboxResolver::new(pool.clone(), Arc::new(NeverProvider), None, config.clone());
        (queue, bridge_registry, config, resolver)
    }

    fn test_queue() -> TaskQueue {
        TaskQueue::new(redis::Client::open("redis://127.0.0.1:1/").expect("redis URL"))
    }

    #[tokio::test]
    async fn scheduler_auto_session_attach_skips_task_that_left_scheduling_without_leaking_session()
    {
        let Some(pool) = test_pool().await else {
            return;
        };

        let unique = Uuid::now_v7().simple().to_string();
        let agent_id = create_scheduler_agent(&pool, &unique).await;
        let task_id = Uuid::now_v7();

        sqlx::query(
            r#"
            INSERT INTO joysafeter_tasks (
                id, agent_id, chat_session_id, status, prompt, output,
                timeout_sec, retry_count, max_retries
            )
            VALUES ($1, $2, NULL, 'running', 'stale scheduler prompt', '', 7200, 0, 2)
            "#,
        )
        .bind(task_id)
        .bind(agent_id)
        .execute(&pool)
        .await
        .expect("insert stale running task without session");

        let result = async {
            let (queue, bridge_registry, config, resolver) = scheduler_noop_runtime(&pool).await;
            schedule_single_task(
                &pool,
                &queue,
                &bridge_registry,
                &config,
                &resolver,
                task_id,
                Some(agent_id),
                None,
                None,
            )
            .await
            .expect("stale auto-session scheduling should be skipped");

            let task: (String, Option<Uuid>) = sqlx::query_as(
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
            handle_scheduling_failure(&pool, &test_queue(), task_id, "resolver failed").await;

            let task: (String, i32, Option<Uuid>) = sqlx::query_as(
                "SELECT status, retry_count, sandbox_id FROM joysafeter_tasks WHERE id = $1",
            )
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load retried task");
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

            let sandbox: (String, Option<Uuid>) = sqlx::query_as(
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
            handle_scheduling_failure(&pool, &test_queue(), task_id, "late resolver failure").await;

            let task: (String, i32, Option<Uuid>, Option<String>) = sqlx::query_as(
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

            let sandbox: (String, Option<Uuid>) = sqlx::query_as(
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
            handle_scheduling_failure(&pool, &test_queue(), task_id, "resolver exhausted").await;

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
        let (queue, bridge_registry, config, resolver) = scheduler_noop_runtime(&pool).await;

        let result = async {
            schedule_single_task(
                &pool,
                &queue,
                &bridge_registry,
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
        let (queue, bridge_registry, config, resolver) = scheduler_noop_runtime(&pool).await;

        let result = async {
            schedule_single_task(
                &pool,
                &queue,
                &bridge_registry,
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

        let agent_id = Uuid::now_v7();
        let environment_id = Uuid::now_v7();
        let session_id = Uuid::now_v7();
        let unique = agent_id.simple().to_string();
        let environment_ref = format!("env_{environment_id}");

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
                    id, name, engine_kind, model, system_prompt, env, mcp_configs,
                    skills, tools, agents, commands, permission_mode, metadata,
                    multiagent, version, environment_ref
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
            .bind(&environment_ref)
            .execute(&pool)
            .await
            .expect("insert agent");

            let agent = queries::get_agent(&pool, agent_id)
                .await
                .expect("load agent")
                .expect("agent exists");
            let snapshot = build_agent_execution_snapshot(&pool, &agent)
                .await
                .expect("build scheduler snapshot");
            queries::create_session(
                &pool,
                session_id,
                Some(agent_id),
                None,
                Some(&snapshot),
                agent.environment_ref.as_deref(),
            )
            .await
            .expect("create scheduler session");

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

            assert_eq!(
                stored.environment_ref.as_deref(),
                Some(environment_ref.as_str())
            );
            let stored_snapshot = stored.agent_snapshot.expect("session snapshot");
            assert_eq!(
                stored_snapshot.get("schema").and_then(Value::as_str),
                Some("joysafeter.agent_execution_snapshot.v1")
            );
            assert_eq!(
                stored_snapshot.get("model").and_then(Value::as_str),
                Some("scheduler-snapshot-model")
            );
            assert_eq!(
                stored_snapshot.get("system_prompt").and_then(Value::as_str),
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

        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
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
    }
}
