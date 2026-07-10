use std::sync::Arc;
use std::time::Duration;

use serde_json::json;
use sqlx::PgPool;
use tokio::sync::Semaphore;
use tokio::task::JoinHandle;
use tracing::{error, info, warn};
use uuid::Uuid;

use crate::config::JoySafeterConfig;
use crate::db::queries;
use crate::kernel::queue::TaskQueue;
use crate::kernel::sandbox_bridge::BridgeRegistry;
use crate::kernel::sandbox_resolver::SandboxResolver;
use crate::sandbox::provider::SandboxProvider;

/// Task scheduler — polls DB for pending tasks, resolves sandboxes, dispatches.
///
/// Full parity with Python `TaskScheduler`: semaphores, auto-session creation,
/// agent archived check, secret injection, environment/networking resolution,
/// engine_kind image selection, failover on scheduling failure.

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
    config: JoySafeterConfig,
) -> JoinHandle<()> {
    let resolver = Arc::new(SandboxResolver::new(
        pool.clone(),
        provider,
        config.clone(),
    ));
    let scheduling_semaphore = Arc::new(Semaphore::new(config.max_scheduling_tasks));

    tokio::spawn(async move {
        info!(
            max_scheduling = config.max_scheduling_tasks,
            "TaskScheduler started"
        );

        loop {
            let available_slots = scheduling_semaphore
                .available_permits()
                .min(config.scheduler_batch_size);
            if available_slots == 0 {
                tokio::time::sleep(Duration::from_millis(200)).await;
                continue;
            }

            // Claim pending tasks from DB
            let tasks = match queries::claim_pending_tasks(&pool, available_slots as i64).await {
                Ok(tasks) => tasks,
                Err(e) => {
                    error!("Failed to claim pending tasks: {e}");
                    tokio::time::sleep(Duration::from_secs(1)).await;
                    continue;
                }
            };

            if tasks.is_empty() {
                // No tasks available, wait briefly then poll again
                tokio::time::sleep(Duration::from_secs(1)).await;
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
                        let _ = queries::transition_task(&pool, task.id, "pending", None).await;
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
                        // T2 fix: use CAS-style retry to prevent double-increment
                        // between scheduler error path and watchdog
                        let should_fail = match queries::get_task(&resolver_pool, task_id).await {
                            Ok(Some(t)) => t.retry_count >= t.max_retries,
                            _ => false,
                        };
                        if should_fail {
                            let _ = queries::transition_task(
                                &resolver_pool,
                                task_id,
                                "failed",
                                Some("scheduling failed after max retries"),
                            )
                            .await;
                        } else {
                            let _ = queries::increment_retry(&resolver_pool, task_id).await;
                            let _ =
                                queries::transition_task(&resolver_pool, task_id, "pending", None)
                                    .await;
                        }
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
            let _ =
                queries::transition_task(pool, task_id, "failed", Some("Agent not found")).await;
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
        let _ =
            queries::transition_task(pool, task_id, "cancelled", Some("Agent is archived")).await;
        return Ok(());
    }

    // --- Auto-create session if needed ---
    if session_id.is_none() {
        let agent_snapshot = json!({
            "type": "agent",
            "id": agent.id.to_string(),
            "version": agent.version,
            "name": agent.name,
            "description": agent.description,
            "model": agent.model,
            "system": agent.system_prompt,
            "tools": agent.tools,
            "skills": agent.skills,
            "mcp_servers": agent.mcp_configs,
            "multiagent": agent.multiagent,
        });

        let new_session = queries::create_session(
            pool,
            Uuid::now_v7(),
            Some(agent.id),
            agent.project_id.as_deref(),
            Some(&agent_snapshot),
        )
        .await?;

        session_id = Some(new_session.id);

        // Update task with new session_id
        sqlx::query(
            "UPDATE joysafeter_tasks SET chat_session_id = $2, updated_at = NOW() WHERE id = $1",
        )
        .bind(task_id)
        .bind(new_session.id)
        .execute(pool)
        .await?;

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

    // --- Push to sandbox queue ---
    queue.push(sandbox_db_id, task_id).await;

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
