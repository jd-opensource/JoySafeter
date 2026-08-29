use std::fs;
use std::path::PathBuf;

fn source(path: &str) -> String {
    fs::read_to_string(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(path))
        .expect("read source file")
}

#[test]
fn bootstrap_uses_one_supervisor_as_the_runtime_lifecycle_owner() {
    let application = source("src/bootstrap/application.rs");

    assert!(application.contains("TaskSupervisor::new"));
    assert!(application.contains("seal_startup"));
    assert!(application.contains("wait_for_critical_exit"));
    assert!(application.contains("supervisor.shutdown().await"));
    assert!(!application.contains("readiness.mark_ready()"));
    assert!(!application.contains(".abort();"));
}

#[test]
fn health_server_binds_before_returning_its_managed_task() {
    let supervisor = source("src/bootstrap/supervisor.rs");
    let bind = supervisor
        .find("TcpListener::bind")
        .expect("health server binds a listener");
    let spawn = supervisor
        .find("Ok(tokio::spawn")
        .expect("health server returns a spawned task");

    assert!(bind < spawn, "health listener must bind before task spawn");
}

#[test]
fn runner_grpc_binds_tcp_and_control_socket_before_returning_its_managed_task() {
    let grpc_server = source("src/grpc/server.rs");
    let start = grpc_server
        .find("pub(crate) async fn start_grpc_server")
        .expect("runner gRPC startup function");
    let startup = &grpc_server[start..];
    let tcp_bind = startup
        .find("TcpListener::bind(addr).await?")
        .expect("runner TCP listener binds before spawn");
    let control_bind = startup
        .find("UnixListener::bind(&control_socket_path)")
        .expect("runner control socket binds before spawn");
    let spawn = startup
        .find("let handle = tokio::spawn")
        .expect("runner gRPC returns a spawned task");

    assert!(tcp_bind < spawn, "runner TCP bind must precede task spawn");
    assert!(
        control_bind < spawn,
        "runner control socket bind must precede task spawn"
    );
    assert!(!startup.contains("sleep(Duration::from_millis(100))"));
}

#[test]
fn supervisor_keeps_lifecycle_types_private_to_bootstrap() {
    let bootstrap = source("src/bootstrap/mod.rs");
    let managed_service = source("src/bootstrap/managed_service.rs");

    assert!(bootstrap.contains("mod managed_service;"));
    assert!(!bootstrap.contains("pub mod managed_service;"));
    assert!(managed_service.contains("pub(crate) struct TaskSupervisor"));
    assert!(managed_service.contains("pub(crate) struct ManagedServiceHandle"));
    assert!(managed_service.contains("pub(crate) enum ServiceHealth"));
}
