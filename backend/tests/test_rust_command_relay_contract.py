from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


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

    assert "recv_bridge_control_input(bridge), if !requires_action_pending" in grpc_server
    assert "proto::SendInput { content }" in grpc_server
    assert "bridge.reset_confirmation();" in grpc_server


def test_cancelled_task_result_stays_cancelled_even_if_runner_returns_error():
    grpc_server = _read("backend/app/joysafeter_orchestrator_rs/src/grpc/server.rs")

    idle_fallback = grpc_server.split("if task_done && !got_idle", 1)[1].split("async fn recv_bridge_control_input", 1)[
        0
    ]
    assert "if cancel_sent" in idle_fallback
    assert 'json!({"type": "cancelled"})' in idle_fallback
    assert "if cancel_sent {\n        TaskResult::Cancelled" in idle_fallback


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
