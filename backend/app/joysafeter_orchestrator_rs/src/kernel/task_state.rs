use serde_json::{json, Value};

use crate::db::queries::{
    FailedSandboxTask, ResetSandboxTask, TaskRetryOutcome, TaskTerminalOutcome,
};
use crate::events::bus::EventBus;
use crate::events::envelope::EventEnvelope;
use crate::ids::{SandboxId, TaskId};

pub async fn publish_retry_outcome(
    event_bus: &EventBus,
    task_id: TaskId,
    stop_reason: &Value,
    outcome: &TaskRetryOutcome,
) {
    let (Some(session_id), Some((event_id, seq))) = (outcome.session_id, outcome.session_event)
    else {
        return;
    };

    let payload = json!({
        "task_id": task_id.to_string(),
        "stop_reason": stop_reason,
    });
    let mut envelope = EventEnvelope::new(session_id, "session.status_rescheduling", payload)
        .with_task(task_id)
        .status_change(Some(stop_reason.clone()))
        .with_db_persisted(event_id, seq);
    if let Some(sandbox_id) = outcome.sandbox_id {
        envelope = envelope.with_sandbox(sandbox_id);
    }
    event_bus.publish(envelope).await;
}

pub async fn publish_terminal_outcome(
    event_bus: &EventBus,
    task_id: TaskId,
    stop_reason: &Value,
    outcome: &TaskTerminalOutcome,
) {
    let Some(session_id) = outcome.session_id else {
        return;
    };

    for committed in &outcome.session_events {
        let mut envelope = EventEnvelope::new(
            session_id,
            committed.event_type.clone(),
            committed.payload.clone(),
        )
        .with_task(task_id)
        .with_db_persisted(committed.event_id, committed.seq);
        if committed.event_type.starts_with("session.status_") {
            let committed_stop_reason = committed
                .payload
                .get("stop_reason")
                .cloned()
                .unwrap_or_else(|| stop_reason.clone());
            envelope = envelope.status_change(Some(committed_stop_reason));
        } else {
            envelope = envelope.flush_immediately();
        }
        if let Some(sandbox_id) = outcome.sandbox_id {
            envelope = envelope.with_sandbox(sandbox_id);
        }
        event_bus.publish(envelope).await;
    }
}

pub async fn publish_reset_sandbox_task_events(
    event_bus: &EventBus,
    sandbox_id: SandboxId,
    stop_reason: &Value,
    tasks: &[ResetSandboxTask],
) {
    for task in tasks {
        let (Some(session_id), Some((event_id, seq))) = (task.session_id, task.session_event)
        else {
            continue;
        };
        let payload = json!({
            "task_id": task.id.to_string(),
            "stop_reason": stop_reason,
        });
        let envelope = EventEnvelope::new(session_id, "session.status_rescheduling", payload)
            .with_task(task.id)
            .with_sandbox(sandbox_id)
            .status_change(Some(stop_reason.clone()))
            .with_db_persisted(event_id, seq);
        event_bus.publish(envelope).await;
    }
}

pub async fn publish_failed_sandbox_task_events(
    event_bus: &EventBus,
    sandbox_id: SandboxId,
    stop_reason: &Value,
    tasks: &[FailedSandboxTask],
) {
    for task in tasks {
        let (Some(session_id), Some((event_id, seq))) = (task.session_id, task.session_event)
        else {
            continue;
        };
        let payload = json!({
            "task_id": task.id.to_string(),
            "stop_reason": stop_reason,
        });
        let envelope = EventEnvelope::new(session_id, "session.status_idle", payload)
            .with_task(task.id)
            .with_sandbox(sandbox_id)
            .status_change(Some(stop_reason.clone()))
            .with_db_persisted(event_id, seq);
        event_bus.publish(envelope).await;
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;
    use sqlx::postgres::PgPoolOptions;

    use crate::config::JoySafeterConfig;
    use crate::db::queries::{
        CommittedSessionEvent, FailedSandboxTask, ResetSandboxTask, TaskRetryOutcome,
        TaskTerminalOutcome,
    };
    use crate::events::bus::EventBus;
    use crate::ids::{EventId, SandboxId, SessionId, TaskId};
    use crate::runtime_config::RuntimeConfig;

    #[tokio::test]
    async fn committed_retry_event_is_broadcast_with_canonical_identity() {
        let pool = PgPoolOptions::new()
            .connect_lazy("postgres://postgres:postgres@127.0.0.1/unused")
            .expect("construct lazy test pool");
        let redis_client =
            redis::Client::open("redis://127.0.0.1:1/").expect("construct redis client");
        let config = JoySafeterConfig::from_env();
        let runtime_config = std::sync::Arc::new(RuntimeConfig::from_config(&config));
        let event_bus = EventBus::new(pool, &config, runtime_config, redis_client);
        let mut receiver = event_bus.subscribe();
        let task_id = TaskId::new();
        let sandbox_id = SandboxId::new();
        let session_id = SessionId::new();
        let event_id = EventId::new();
        let stop_reason = json!({"type": "sandbox_failed"});
        let outcome = TaskRetryOutcome {
            session_id: Some(session_id),
            sandbox_id: Some(sandbox_id),
            sandbox_released: true,
            session_event: Some((event_id, 17)),
        };

        super::publish_retry_outcome(&event_bus, task_id, &stop_reason, &outcome).await;

        let envelope = receiver
            .recv()
            .await
            .expect("receive committed retry event");
        assert_eq!(envelope.session_id, session_id);
        assert_eq!(envelope.event_type, "session.status_rescheduling");
        assert_eq!(envelope.event_id, Some(event_id));
        assert_eq!(envelope.session_seq, Some(17));
        assert_eq!(envelope.task_id, Some(task_id));
        assert_eq!(envelope.sandbox_id, Some(sandbox_id));
        assert!(envelope.db_persisted);
        assert_eq!(envelope.stop_reason, Some(stop_reason.clone()));
        assert_eq!(
            envelope.payload,
            json!({"task_id": task_id.to_string(), "stop_reason": stop_reason})
        );
    }

    #[tokio::test]
    async fn committed_terminal_event_is_broadcast_with_canonical_identity() {
        let pool = PgPoolOptions::new()
            .connect_lazy("postgres://postgres:postgres@127.0.0.1/unused")
            .expect("construct lazy test pool");
        let redis_client =
            redis::Client::open("redis://127.0.0.1:1/").expect("construct redis client");
        let config = JoySafeterConfig::from_env();
        let runtime_config = std::sync::Arc::new(RuntimeConfig::from_config(&config));
        let event_bus = EventBus::new(pool, &config, runtime_config, redis_client);
        let mut receiver = event_bus.subscribe();
        let task_id = TaskId::new();
        let sandbox_id = SandboxId::new();
        let session_id = SessionId::new();
        let agent_event_id = EventId::new();
        let idle_event_id = EventId::new();
        let stop_reason = json!({"type": "end_turn"});
        let outcome = TaskTerminalOutcome {
            session_id: Some(session_id),
            sandbox_id: Some(sandbox_id),
            sandbox_released: true,
            session_events: vec![
                CommittedSessionEvent {
                    event_id: agent_event_id,
                    seq: 17,
                    event_type: "agent.message".to_string(),
                    payload: json!({"content": [{"type": "text", "text": "done"}]}),
                },
                CommittedSessionEvent {
                    event_id: idle_event_id,
                    seq: 18,
                    event_type: "session.status_idle".to_string(),
                    payload: json!({
                        "task_id": task_id.to_string(),
                        "stop_reason": stop_reason.clone(),
                    }),
                },
            ],
        };

        super::publish_terminal_outcome(&event_bus, task_id, &stop_reason, &outcome).await;

        let agent_envelope = receiver
            .recv()
            .await
            .expect("receive committed fallback agent event");
        assert_eq!(agent_envelope.event_type, "agent.message");
        assert_eq!(agent_envelope.event_id, Some(agent_event_id));
        assert_eq!(agent_envelope.session_seq, Some(17));
        assert!(agent_envelope.db_persisted);

        let idle_envelope = receiver
            .recv()
            .await
            .expect("receive committed terminal event");
        assert_eq!(idle_envelope.event_type, "session.status_idle");
        assert_eq!(idle_envelope.event_id, Some(idle_event_id));
        assert_eq!(idle_envelope.session_seq, Some(18));
        assert_eq!(idle_envelope.task_id, Some(task_id));
        assert_eq!(idle_envelope.sandbox_id, Some(sandbox_id));
        assert!(idle_envelope.db_persisted);
    }

    #[tokio::test]
    async fn committed_batch_recovery_events_are_broadcast_with_canonical_identity() {
        let pool = PgPoolOptions::new()
            .connect_lazy("postgres://postgres:postgres@127.0.0.1/unused")
            .expect("construct lazy test pool");
        let redis_client =
            redis::Client::open("redis://127.0.0.1:1/").expect("construct redis client");
        let config = JoySafeterConfig::from_env();
        let runtime_config = std::sync::Arc::new(RuntimeConfig::from_config(&config));
        let event_bus = EventBus::new(pool, &config, runtime_config, redis_client);
        let mut receiver = event_bus.subscribe();
        let sandbox_id = SandboxId::new();
        let reset_task_id = TaskId::new();
        let reset_session_id = SessionId::new();
        let reset_event_id = EventId::new();
        let failed_task_id = TaskId::new();
        let failed_session_id = SessionId::new();
        let failed_event_id = EventId::new();
        let reset_stop_reason = json!({"type": "sandbox_failed"});
        let failed_stop_reason = json!({"type": "error", "message": "runtime missing"});

        super::publish_reset_sandbox_task_events(
            &event_bus,
            sandbox_id,
            &reset_stop_reason,
            &[ResetSandboxTask {
                id: reset_task_id,
                session_id: Some(reset_session_id),
                previous_retry_count: 0,
                session_event: Some((reset_event_id, 7)),
            }],
        )
        .await;
        super::publish_failed_sandbox_task_events(
            &event_bus,
            sandbox_id,
            &failed_stop_reason,
            &[FailedSandboxTask {
                id: failed_task_id,
                session_id: Some(failed_session_id),
                session_event: Some((failed_event_id, 11)),
            }],
        )
        .await;

        let reset = receiver.recv().await.expect("receive reset event");
        assert_eq!(reset.event_type, "session.status_rescheduling");
        assert_eq!(reset.session_id, reset_session_id);
        assert_eq!(reset.task_id, Some(reset_task_id));
        assert_eq!(reset.sandbox_id, Some(sandbox_id));
        assert_eq!(reset.event_id, Some(reset_event_id));
        assert_eq!(reset.session_seq, Some(7));
        assert!(reset.db_persisted);

        let failed = receiver.recv().await.expect("receive failed event");
        assert_eq!(failed.event_type, "session.status_idle");
        assert_eq!(failed.session_id, failed_session_id);
        assert_eq!(failed.task_id, Some(failed_task_id));
        assert_eq!(failed.sandbox_id, Some(sandbox_id));
        assert_eq!(failed.event_id, Some(failed_event_id));
        assert_eq!(failed.session_seq, Some(11));
        assert!(failed.db_persisted);
    }
}
