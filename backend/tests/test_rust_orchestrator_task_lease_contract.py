from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_rust_running_claim_stamps_owner_epoch_and_lease():
    queries = _read("backend/app/joysafeter_orchestrator_rs/src/db/queries.rs")

    assert "pub async fn claim_next_sandbox_task" in queries
    claim_body = queries.split("pub async fn claim_next_sandbox_task", 1)[1].split("/// Attach", 1)[0]

    assert "owner_instance_id: &str" in claim_body
    assert "lease_ttl_sec: i64" in claim_body
    assert "status = 'running'" in claim_body
    assert "owner_instance_id = $2" in claim_body
    assert "owner_epoch = nextval('joysafeter_task_owner_epoch_seq')" in claim_body
    assert "lease_expires_at = NOW() + ($3 * INTERVAL '1 second')" in claim_body


def test_rust_task_terminal_writes_are_epoch_fenced_and_clear_lease():
    queries = _read("backend/app/joysafeter_orchestrator_rs/src/db/queries.rs")
    server = _read("backend/app/joysafeter_orchestrator_rs/src/grpc/server.rs")

    cas_body = queries.split("pub async fn transition_task_cas", 1)[1].split("/// Create a new session", 1)[0]

    assert "expected_owner_epoch: Option<i64>" in cas_body
    assert "($5::bigint IS NULL OR owner_epoch = $5)" in cas_body
    assert "owner_instance_id = CASE" in cas_body
    assert "owner_epoch = CASE" in cas_body
    assert "lease_expires_at = CASE" in cas_body
    assert "if cas_ok" in server
    assert 'let stop_reason = json!({"type": "timeout"})' in server
    assert "update_session_status_and_insert_event" in server


def test_rust_task_controller_renews_and_reclaims_running_leases():
    controller = _read("backend/app/joysafeter_orchestrator_rs/src/kernel/task_controller.rs")
    queries = _read("backend/app/joysafeter_orchestrator_rs/src/db/queries.rs")

    assert "task_lease_renew_interval_sec" in controller
    assert "renew_running_task_leases" in controller
    assert "active_task_ids().await" in controller
    assert "bridge_registry.all_bridges()" in controller
    assert "check_lease_expired_tasks" in controller
    assert "find_lease_expired_running_tasks" in controller
    assert "retry_lease_expired_task" in controller
    assert "fail_lease_expired_task" in controller
    assert "push_to_global(*task_id)" in controller

    retry_body = queries.split("pub async fn retry_lease_expired_task", 1)[1].split(
        "pub async fn fail_lease_expired_task", 1
    )[0]
    assert "status = 'running'" in retry_body
    assert "lease_expires_at < NOW()" in retry_body


def test_rust_task_lease_renewal_only_extends_process_active_tasks():
    controller = _read("backend/app/joysafeter_orchestrator_rs/src/kernel/task_controller.rs")
    queries = _read("backend/app/joysafeter_orchestrator_rs/src/db/queries.rs")
    main = _read("backend/app/joysafeter_orchestrator_rs/src/main.rs")

    renew_body = queries.split("pub async fn renew_running_task_leases", 1)[1].split(
        "/// Running tasks whose ownership lease expired", 1
    )[0]
    assert "active_task_ids: &[Uuid]" in renew_body
    assert "if active_task_ids.is_empty()" in renew_body
    assert "AND id = ANY($3)" in renew_body
    assert ".bind(active_task_ids)" in renew_body

    assert "bridge_registry: BridgeRegistry" in controller
    assert "async fn active_task_ids(&self) -> Vec<Uuid>" in controller
    assert "bridge.current_task_id.lock().await" in controller
    assert "check_lease_expired_tasks().await" in controller

    constructor_call = main.split("TaskController::new(", 1)[1].split(");", 1)[0]
    assert "bridge_registry.clone()" in constructor_call
