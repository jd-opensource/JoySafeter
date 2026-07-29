from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.no_db


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_input_command_ack_depends_on_bridge_queue_send_result():
    bridge = _read("backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_bridge.rs")
    listener = _read("backend/app/joysafeter_orchestrator_rs/src/kernel/command_listener.rs")
    grpc_server = _read("backend/app/joysafeter_orchestrator_rs/src/grpc/server.rs")

    assert "Result<(), mpsc::error::SendError<String>>" in bridge
    assert "self.control_tx.send(content).await?" in bridge
    assert "confirmation_tx.send(true)" in bridge
    assert "send_control_input_reports_closed_queue" in bridge

    assert "ack_ok = bridge.send_control_input(content.to_string()).await.is_ok();" in listener
    assert "publish_ack(&cmd, ack_ok)" in listener

    assert "_ = bridge.wait_confirmation(), if requires_action_pending" in grpc_server
    assert "while let Ok(content) = ctrl_rx.try_recv()" in grpc_server
    assert "proto::SendInput { content }" in grpc_server
    assert "bridge.reset_confirmation();" in grpc_server


def test_reconnect_control_replay_marks_processed_only_after_runner_send():
    grpc_server = _read("backend/app/joysafeter_orchestrator_rs/src/grpc/server.rs")

    helper = grpc_server.split("async fn replay_pending_control_inputs", 1)[1].split(
        "/// Full reconnect handler", 1
    )[0]

    assert "if let Err(e) = tx.send(input_msg).await" in helper
    assert "leaving event unprocessed for future reconnect" in helper
    send_failed_branch = helper.split("if let Err(e) = tx.send(input_msg).await", 1)[1].split(
        "sqlx::query", 1
    )[0]
    assert "processed_at" not in send_failed_branch
    assert "UPDATE joysafeter_session_events SET processed_at = NOW()" in helper
    assert "pending_control_replay_marks_processed_only_after_send_succeeds" in grpc_server


def test_cancel_signal_transitions_task_and_session_before_waiting_for_runner_idle():
    grpc_server = _read("backend/app/joysafeter_orchestrator_rs/src/grpc/server.rs")

    cancel_branch = grpc_server.split("_ = task_cancel.cancelled(), if !cancel_sent =>", 1)[1].split(
        "// HITL confirmation", 1
    )[0]
    assert "cancel_sent = true" in cancel_branch
    assert 'proto::CancelTask { reason: "Cancelled by user".to_string() }' in cancel_branch
    assert "transition_running_task_and_emit_idle(" in cancel_branch
    assert '"cancelled"' in cancel_branch
    assert 'json!({"type": "cancelled"})' in cancel_branch
    assert "load_terminal_task_result(pool, task_id).await" in cancel_branch
    assert "continue;" in cancel_branch


def test_reconnected_surviving_runner_task_keeps_input_control_channel():
    runner_main = _read("sandbox-runner/crates/joysafeter-runner/src/main.rs")

    surviving_task = runner_main.split("struct SurvivingTask", 1)[1].split("#[tokio::main]", 1)[0]
    reconnect_loop = runner_main.split('"Resuming surviving task on new connection"', 1)[1].split(
        "// Normal message loop", 1
    )[0]

    assert "control_tx: mpsc::Sender<runner::RunnerControl>" in surviving_task
    assert "Payload::Input(input)" in reconnect_loop
    assert ".control_tx" in reconnect_loop
    assert "RunnerControl::SendInput(input.content)" in reconnect_loop
