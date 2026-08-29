use std::fs;
use std::path::PathBuf;

fn source(path: &str) -> String {
    fs::read_to_string(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(path))
        .unwrap_or_else(|error| panic!("read {path}: {error}"))
}

#[test]
fn runner_transport_only_adapts_tonic_streams_and_limits_connections() {
    let transport = source("src/grpc/transport.rs");

    for required in [
        "impl AgentBridge for RunnerTransport",
        "connection_semaphore",
        "RunnerSessionCoordinator",
        "request.into_inner()",
    ] {
        assert!(transport.contains(required), "transport misses {required}");
    }

    for forbidden in [
        "sqlx::",
        "PgPool",
        "crate::db::queries",
        "RedisCoordinator",
        "archive_task_artifacts",
        "transition_task_cas",
        "rescue_orphaned_tasks",
        "handle_reconnect",
    ] {
        assert!(
            !transport.contains(forbidden),
            "transport owns forbidden application concern: {forbidden}"
        );
    }
}

#[test]
fn runner_application_services_own_disjoint_session_execution_and_recovery_flows() {
    let session = source("src/kernel/runner/session.rs");
    assert!(session.contains("pub(crate) struct RunnerSessionCoordinator"));
    assert!(session.contains("wait_for_ready"));
    assert!(session.contains("register"));
    assert!(!session.contains("impl AgentBridge for"));

    let execution = source("src/kernel/runner/execution.rs");
    assert!(execution.contains("pub(crate) struct RunnerExecutionService"));
    assert!(execution.contains("run_single_task"));
    assert!(execution.contains("archive_task_artifacts"));
    assert!(!execution.contains("impl AgentBridge for"));

    let recovery = source("src/kernel/runner/recovery.rs");
    assert!(recovery.contains("pub(crate) struct RunnerRecoveryService"));
    assert!(recovery.contains("handle_reconnect"));
    assert!(recovery.contains("rescue_orphaned_tasks"));
    assert!(!recovery.contains("impl AgentBridge for"));
}

#[test]
fn runner_server_owns_binding_but_not_runner_state_transitions() {
    let server = source("src/grpc/server.rs");
    assert!(server.contains("pub(crate) async fn start_grpc_server"));
    assert!(server.contains("TcpListener::bind(addr).await?"));
    assert!(server.contains("UnixListener::bind(&control_socket_path)"));
    assert!(server.contains("RunnerTransport"));

    for forbidden in [
        "sqlx::",
        "PgPool",
        "crate::db::queries",
        "transition_task_cas",
        "archive_task_artifacts",
        "rescue_orphaned_tasks",
    ] {
        assert!(
            !server.contains(forbidden),
            "server owns forbidden runner application concern: {forbidden}"
        );
    }
}

#[test]
fn runner_and_ads_servers_remain_separate_bootstrap_services() {
    let application = source("src/bootstrap/application.rs");
    assert!(application.contains("start_grpc_server"));
    assert!(application.contains("start_xds_server"));
    assert!(application.contains("runner-grpc"));
    assert!(application.contains("xds-ads"));
}
