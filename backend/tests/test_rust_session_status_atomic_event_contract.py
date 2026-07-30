from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.no_db


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_rust_has_atomic_session_status_event_helper():
    queries = _read("backend/app/joysafeter_orchestrator_rs/src/db/queries.rs")

    assert "pub async fn update_session_status(" not in queries
    assert "pub async fn insert_session_event(" not in queries

    body = queries.split("pub async fn update_session_status_and_insert_event", 1)[1].split(
        "pub async fn update_session_sandbox", 1
    )[0]

    assert "let mut tx = pool.begin().await?" in body
    assert "pg_advisory_xact_lock" in body
    assert "UPDATE joysafeter_sessions" in body
    assert "INSERT INTO joysafeter_session_events" in body
    assert "ON CONFLICT" not in body
    assert ".fetch_one(&mut *tx)" in body
    assert ".fetch_optional(&mut *tx)" not in body
    assert "tx.commit().await?" in body


def test_rust_runner_idle_paths_use_atomic_session_status_event_helper():
    server = _read("backend/app/joysafeter_orchestrator_rs/src/grpc/server.rs")

    assert "update_session_status_and_insert_event" in server
    assert server.count("update_session_status_and_insert_event(") >= 5
    assert "E4 fix: also update session status directly via DB" not in server


def test_rust_running_status_paths_use_atomic_helper_before_publish():
    server = _read("backend/app/joysafeter_orchestrator_rs/src/grpc/server.rs")

    helper = server.split("async fn emit_session_running_status", 1)[1].split("async fn emit_session_idle_status", 1)[0]
    reconnect = server.split("async fn handle_reconnect_with_event_loop", 1)[1].split(
        "// Run the full task event loop", 1
    )[0]

    assert "queries::update_session_status_and_insert_event(" in helper
    assert '"session.status_running"' in helper
    assert "with_db_persisted(event_id, seq)" in helper
    assert "event_bus.publish(envelope).await;" in helper

    assert "emit_session_running_status(" in reconnect
    assert '"reconnect"' in reconnect
    assert "EventEnvelope::new" not in reconnect
    assert ".status_change(None);" not in reconnect


def test_rust_grpc_server_does_not_split_session_status_row_and_event_writes():
    server = _read("backend/app/joysafeter_orchestrator_rs/src/grpc/server.rs")

    assert "queries::update_session_status(" not in server
    assert "queries::insert_session_event(" not in server


def test_rust_task_controller_does_not_split_session_status_row_and_event_writes():
    controller = _read("backend/app/joysafeter_orchestrator_rs/src/kernel/task_controller.rs")

    atomic_calls = controller.count("update_session_status_and_insert_event(") + controller.count(
        "update_session_status_if_no_active_tasks_and_insert_event("
    )
    assert atomic_calls >= 4
    assert "queries::update_session_status(" not in controller
    assert "queries::insert_session_event(" not in controller
    assert '"session.status_terminated"' in controller
    assert '"session.status_idle"' in controller


def test_rust_db_persisted_status_envelopes_do_not_reenter_persistence_pipeline():
    envelope = _read("backend/app/joysafeter_orchestrator_rs/src/events/envelope.rs")
    bus = _read("backend/app/joysafeter_orchestrator_rs/src/events/bus.rs")
    session_state = _read("backend/app/joysafeter_orchestrator_rs/src/events/session_state.rs")
    session_broadcast = _read("backend/app/joysafeter_orchestrator_rs/src/events/session_broadcast.rs")
    stream_publisher = _read("backend/app/joysafeter_orchestrator_rs/src/events/stream_publisher.rs")
    server = _read("backend/app/joysafeter_orchestrator_rs/src/grpc/server.rs")

    assert "pub db_persisted: bool" in envelope
    assert "pub session_seq: Option<i64>" in envelope
    assert "pub runner_seq: Option<i64>" in envelope
    assert "pub seq: Option<i64>" not in envelope
    assert "pub fn with_runner_seq" in envelope
    assert "pub fn with_seq" not in envelope
    assert "pub fn with_db_persisted" in envelope
    assert "self.session_seq = Some(seq)" in envelope
    assert "self.db_persisted = true" in envelope
    assert "self.persist_to_db && !shared.db_persisted && !shared.is_status_change" in bus
    assert "if envelope.db_persisted" in session_state
    assert "envelope.session_seq.is_none()" in session_broadcast
    assert "if envelope.db_persisted" in stream_publisher
    assert "if envelope.is_status_change" in stream_publisher
    idle_helper = server.split("async fn emit_session_idle_status", 1)[1].split(
        "async fn transition_running_task_and_emit_idle", 1
    )[0]
    assert server.count("with_db_persisted(event_id, seq)") >= 6
    assert "async fn emit_session_running_status" in server
    assert "with_db_persisted(event_id, seq)" in idle_helper


def test_rust_runner_seq_and_session_seq_are_separate_in_envelopes():
    server = _read("backend/app/joysafeter_orchestrator_rs/src/grpc/server.rs")
    bus = _read("backend/app/joysafeter_orchestrator_rs/src/events/bus.rs")
    stream_publisher = _read("backend/app/joysafeter_orchestrator_rs/src/events/stream_publisher.rs")

    assert "with_runner_seq(harness_event.seq as i64)" in server
    assert "with_seq(harness_event.seq as i64)" not in server
    assert "shared.session_seq" in bus
    assert "shared.seq" not in bus
    assert "envelope.session_seq.unwrap_or(0)" in stream_publisher
    assert "envelope.runner_seq.unwrap_or(0)" in stream_publisher
    assert "envelope.seq.unwrap_or(0)" not in stream_publisher


def test_rust_flush_immediate_events_are_persisted_before_publish_returns():
    bus = _read("backend/app/joysafeter_orchestrator_rs/src/events/bus.rs")
    stream_publisher = _read("backend/app/joysafeter_orchestrator_rs/src/events/stream_publisher.rs")

    flush_branch = bus.split("if flush {", 1)[1].split("} else {", 1)[0]

    assert "persister" in flush_branch
    assert ".push(event_id, session_id, &event_type, &payload, session_seq)" in flush_branch
    assert "persister.flush().await;" in flush_branch
    assert "tokio::spawn" not in flush_branch
    assert "if envelope.flush_immediately" in stream_publisher
    assert "persister.flush().await;" in stream_publisher


def test_rust_event_bus_has_single_primary_non_status_event_persistence_path():
    bus = _read("backend/app/joysafeter_orchestrator_rs/src/events/bus.rs")
    main = _read("backend/app/joysafeter_orchestrator_rs/src/main.rs")

    assert "stream_publisher: Option<Arc<EventStreamPublisher>>" in bus
    assert "persist_to_db: !config.event_stream_enabled" in bus
    assert "if let Some(stream_publisher)" in bus
    assert "} else if self.persist_to_db" in bus
    assert "stream_pub.spawn(event_bus.subscribe())" not in main
    assert "EventStreamPublisher enabled inside EventBus" in main


def test_rust_cancel_and_timeout_paths_write_replayable_idle_status():
    server = _read("backend/app/joysafeter_orchestrator_rs/src/grpc/server.rs")

    cancel_branch = server.split("_ = task_cancel.cancelled()", 1)[1].split("// HITL confirmation", 1)[0]
    timeout_branch = server.split("// Task deadline", 1)[1].split("// #18: Heartbeat timeout", 1)[0]
    transition_helper = server.split("async fn transition_running_task_and_emit_idle", 1)[1].split(
        "fn task_result_from_status", 1
    )[0]
    idle_helper = server.split("async fn emit_session_idle_status", 1)[1].split(
        "async fn transition_running_task_and_emit_idle", 1
    )[0]

    for branch, reason in ((cancel_branch, "cancelled"), (timeout_branch, "timeout")):
        assert "transition_running_task_and_emit_idle(" in branch
        assert f'"{reason}"' in branch
        assert f'json!({{"type": "{reason}"}})' in branch

    assert "queries::transition_task_cas(" in transition_helper
    assert "Ok(true) =>" in transition_helper
    assert "emit_session_idle_status(" in transition_helper
    assert "Ok(false) =>" in transition_helper
    assert (
        "update_session_status_if_no_active_tasks_and_insert_event" in idle_helper
        or "update_session_status_and_insert_event" in idle_helper
    )
    assert '"session.status_idle"' in idle_helper
    assert "event_bus.publish(envelope).await;" in idle_helper


def test_rust_idle_status_publish_requires_inserted_status_event():
    server = _read("backend/app/joysafeter_orchestrator_rs/src/grpc/server.rs")

    fallback = server.split("if task_done && !runner_idle_seen && !terminal_idle_handled", 1)[1].split(
        "\n    if let Some(result) = authoritative_result", 1
    )[0]
    result = server.split("runner_message::Payload::Result", 1)[1].split(
        'info!(task_id = %task_id, status = status, "Task result received");', 1
    )[0]
    idle = server.split("runner_message::Payload::Idle", 1)[1].split("runner_message::Payload::Heartbeat", 1)[0]
    helper = server.split("async fn emit_session_idle_status", 1)[1].split(
        "async fn transition_running_task_and_emit_idle", 1
    )[0]

    assert (
        "match queries::update_session_status_if_no_active_tasks_and_insert_event" in helper
        or "match queries::update_session_status_and_insert_event" in helper
    )
    assert "Ok(Some((event_id, seq)))" in helper
    guarded = helper.split("Ok(Some((event_id, seq)))", 1)[1].split("Ok(None)", 1)[0]
    assert "with_db_persisted(event_id, seq)" in guarded
    assert "event_bus.publish(envelope).await;" in guarded

    for body in (fallback, result, idle):
        assert "emit_session_idle_status(" in body
