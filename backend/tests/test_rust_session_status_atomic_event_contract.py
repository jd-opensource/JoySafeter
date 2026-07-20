from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_rust_has_atomic_session_status_event_helper():
    queries = _read("backend/app/joysafeter_orchestrator_rs/src/db/queries.rs")

    body = queries.split("pub async fn update_session_status_and_insert_event", 1)[1].split(
        "/// Accumulate token usage", 1
    )[0]

    assert "let mut tx = pool.begin().await?" in body
    assert "pg_advisory_xact_lock" in body
    assert "UPDATE joysafeter_sessions" in body
    assert "INSERT INTO joysafeter_session_events" in body
    assert "tx.commit().await?" in body


def test_rust_runner_idle_paths_use_atomic_session_status_event_helper():
    server = _read("backend/app/joysafeter_orchestrator_rs/src/grpc/server.rs")

    assert "update_session_status_and_insert_event" in server
    assert server.count("update_session_status_and_insert_event(") >= 5
    assert "E4 fix: also update session status directly via DB" not in server


def test_rust_cancel_and_timeout_paths_write_replayable_idle_status():
    server = _read("backend/app/joysafeter_orchestrator_rs/src/grpc/server.rs")

    cancel_branch = server.split("_ = task_cancel.cancelled()", 1)[1].split("// HITL confirmation", 1)[0]
    timeout_branch = server.split("// Task deadline", 1)[1].split("// #18: Heartbeat timeout", 1)[0]

    for branch, reason in ((cancel_branch, "cancelled"), (timeout_branch, "timeout")):
        assert f'let stop_reason = json!({{"type": "{reason}"}})' in branch
        assert "update_session_status_and_insert_event" in branch
        assert '"session.status_idle"' in branch
        assert "event_bus.publish(envelope).await;" in branch


def test_rust_idle_status_publish_requires_inserted_status_event():
    server = _read("backend/app/joysafeter_orchestrator_rs/src/grpc/server.rs")

    fallback = server.split("if task_done && !got_idle", 1)[1].split("\n    if cancel_sent", 1)[0]
    result = server.split("runner_message::Payload::Result", 1)[1].split(
        'info!(task_id = %task_id, status = status, "Task result received");', 1
    )[0]
    idle = server.split("runner_message::Payload::Idle", 1)[1].split("runner_message::Payload::Heartbeat", 1)[0]

    for body in (fallback, result, idle):
        assert "let inserted = queries::update_session_status_and_insert_event" in body
        assert "if let Some((event_id, seq)) = inserted {" in body
        guarded = body.split("if let Some((event_id, seq)) = inserted {", 1)[1]
        assert "event_bus.publish(envelope).await;" in guarded
