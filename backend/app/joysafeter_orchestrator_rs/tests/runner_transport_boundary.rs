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
        "struct TonicRunnerInbound",
        "impl RunnerInbound for TonicRunnerInbound",
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
    let session_production = session
        .split("#[cfg(test)]\nmod tests")
        .next()
        .expect("session production source");
    assert!(session.contains("pub(crate) struct RunnerSessionCoordinator"));
    assert!(session.contains("wait_for_ready"));
    assert!(session.contains("register"));
    assert!(!session.contains("impl AgentBridge for"));
    assert!(!session_production.contains("RunnerExecutionService::new"));
    assert!(!session_production.contains("RunnerRecoveryService::new"));
    assert!(!session_production.contains("RunnerCleanupService::new"));

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

    for (owner, source) in [("execution", execution), ("recovery", recovery)] {
        for forbidden in ["super::session", "runner::session"] {
            assert!(
                !source.contains(forbidden),
                "{owner} reverses the runner dependency direction through {forbidden}"
            );
        }
    }

    for path in [
        "src/kernel/runner/session.rs",
        "src/kernel/runner/setup.rs",
        "src/kernel/runner/execution.rs",
        "src/kernel/runner/recovery.rs",
    ] {
        let source = source(path);
        assert!(
            !source.contains("tonic::Streaming"),
            "application Runner flow depends on tonic transport: {path}"
        );
    }

    let inbound = source("src/kernel/runner/inbound.rs");
    assert!(inbound.contains("trait RunnerInbound"));
    assert!(!inbound.contains("tonic::"));
}

#[test]
fn bootstrap_factory_assembles_runner_subflows() {
    let factories = source("src/bootstrap/runtime_factories.rs");

    for required in [
        "build_runner_flows",
        "RunnerExecutionService::new",
        "RunnerRecoveryService::new",
        "RunnerCleanupService::new",
        "RunnerFlowSet::new",
    ] {
        assert!(
            factories.contains(required),
            "runner bootstrap factory misses {required}"
        );
    }
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

#[test]
fn runner_authentication_uses_a_kernel_port_and_postgres_adapter() {
    let auth = source("src/kernel/runtime_auth.rs");
    let adapter = source("src/db/runner_auth_store.rs");
    let session = source("src/kernel/runner/session.rs");
    let factories = source("src/bootstrap/runtime_factories.rs");

    for required in [
        "trait RunnerAuthStore",
        "struct RunnerAuthenticator",
        "async fn verify",
        "async fn record_connection",
        "mark_connected_if_current",
    ] {
        assert!(auth.contains(required), "runner auth misses {required}");
    }
    for forbidden in ["sqlx::", "PgPool", "crate::db::queries"] {
        assert!(
            !auth.contains(forbidden),
            "runner auth port depends on database detail {forbidden}"
        );
    }

    assert!(adapter.contains("struct PostgresRunnerAuthStore"));
    assert!(adapter.contains("impl RunnerAuthStore for PostgresRunnerAuthStore"));
    assert!(adapter.contains("UPDATE joysafeter_sandboxes"));
    assert!(adapter.contains("runner_token_digest IS NOT DISTINCT FROM $"));

    for forbidden in [
        "queries::get_sandbox",
        "queries::touch_sandbox",
        "queries::mark_bridge_connected",
        "RunnerAuthRecord",
        "authenticate_runner(",
    ] {
        assert!(
            !session.contains(forbidden),
            "runner coordinator owns authentication detail {forbidden}"
        );
    }
    assert!(session.contains("let admission_service = self.flows.admission()"));
    assert!(
        factories.contains("PostgresRunnerAuthStore"),
        "composition root must choose the runner auth adapter"
    );
}

#[test]
fn grpc_owns_harness_setup_and_start_task_projection() {
    let builder = source("src/kernel/harness_input_builder.rs");
    let contract = source("src/kernel/harness_contract.rs");
    let mcp_plan = source("src/kernel/mcp_runtime_plan.rs");
    let projection = source("src/grpc/harness_projection.rs");

    for forbidden in [
        "pub fn build_setup_sandbox",
        "pub fn build_start_task",
        "proto::SetupSandbox",
        "proto::StartTask",
        "crate::grpc::tool_policy::encode",
    ] {
        assert!(
            !builder.contains(forbidden),
            "kernel harness builder owns transport projection detail {forbidden}"
        );
    }

    for required in [
        "pub(crate) fn setup_sandbox",
        "pub(crate) fn start_task",
        "proto::SetupSandbox",
        "proto::StartTask",
        "tool_policy::encode",
        "encode_mcp_server",
    ] {
        assert!(
            projection.contains(required),
            "gRPC harness projection misses {required}"
        );
    }

    for (owner, source) in [("builder", builder), ("MCP plan", mcp_plan)] {
        for forbidden in ["use crate::grpc::proto", "proto::"] {
            assert!(
                !source.contains(forbidden),
                "kernel {owner} depends on transport detail {forbidden}"
            );
        }
    }

    for required in [
        "pub struct HarnessInput",
        "pub struct HarnessMcpServer",
        "pub struct HarnessSkillArchive",
        "pub struct HarnessRepository",
    ] {
        assert!(
            contract.contains(required),
            "harness contract misses {required}"
        );
    }
    assert!(
        !contract.contains("grpc::"),
        "harness contract must remain transport neutral"
    );
    assert!(
        !contract.contains("authorization_token"),
        "harness repository contract must not expose clone credentials"
    );
    assert!(
        projection.contains("authorization_token: String::new()"),
        "wire projection must leave the legacy clone-token field empty"
    );
}

#[test]
fn conversation_history_is_an_isolated_harness_subflow() {
    let builder = source("src/kernel/harness_input_builder.rs");
    let builder_production = builder
        .split("\n#[cfg(test)]\nmod tests {")
        .next()
        .expect("harness builder production source");
    let history = source("src/kernel/harness_input_builder/conversation_history.rs");

    assert!(builder_production.contains("conversation_history::load"));
    for forbidden in [
        "FROM joysafeter_session_events",
        "CONVERSATION_HISTORY_EVENT_LIMIT",
        "fn extract_content_text",
        "fn trim_history_lines_to_budget",
    ] {
        assert!(
            !builder_production.contains(forbidden),
            "main harness builder owns conversation-history detail {forbidden}"
        );
    }

    for required in [
        "pub(super) async fn load",
        "FROM joysafeter_session_events",
        "fn extract_content_text",
        "fn trim_history_lines_to_budget",
    ] {
        assert!(
            history.contains(required),
            "conversation-history subflow misses {required}"
        );
    }
}

#[test]
fn harness_builder_delegates_owned_resource_subflows() {
    let builder = source("src/kernel/harness_input_builder.rs");
    let generation = source("src/kernel/harness_input_builder/generation_fence.rs");
    let skills = source("src/kernel/harness_input_builder/skill_archives.rs");
    let resources = source("src/kernel/harness_input_builder/session_resources.rs");
    let setup = source("src/kernel/runner/setup.rs");
    let execution = source("src/kernel/runner/execution.rs");
    let skill_usage = source("src/kernel/runner/skill_usage.rs");
    let skill_usage_store = source("src/db/queries/skill_usage.rs");

    for module in [
        "mod generation_fence;",
        "mod skill_archives;",
        "mod session_resources;",
    ] {
        assert!(builder.contains(module), "harness builder misses {module}");
    }
    for delegated_call in [
        "generation_fence::load",
        "skill_archives::resolve",
        "session_resources::load_memory_stores",
        "session_resources::load_session_files",
        "session_resources::load_session_repos",
    ] {
        assert!(
            builder.contains(delegated_call),
            "harness builder does not delegate through {delegated_call}"
        );
    }
    for forbidden in [
        "fn load_generation_fence",
        "fn resolve_skill_archives",
        "fn load_memory_stores",
        "fn load_session_files",
        "fn load_session_repos",
        "struct HarnessGenerationFence",
        "struct SkillForArchive",
        "struct SessionFileRow",
    ] {
        assert!(
            !builder.contains(forbidden),
            "harness builder still owns delegated detail {forbidden}"
        );
    }

    assert!(generation.contains("struct HarnessGenerationFence"));
    assert!(generation.contains("pub(super) async fn load"));
    assert!(skills.contains("pub(super) async fn resolve"));
    assert!(!skills.contains("record_skill_usage"));
    assert!(setup.contains("persist_skill_materialization_receipts"));
    assert!(setup.contains("record_correlated_setup_result"));
    for forbidden in [
        "SkillLoadManifest",
        "persist_skill_materialization_receipts",
        "SkillLoadReceiptState",
        "SkillLoadReport",
    ] {
        assert!(
            !execution.contains(forbidden),
            "task execution owns forbidden Skill materialization concern {forbidden}"
        );
    }
    assert!(skill_usage.contains("persist_skill_materialization_receipts"));
    assert!(!skill_usage.contains("SkillLoadReceiptState"));
    assert!(skill_usage_store.contains("record_loaded_skill_usage"));
    assert!(skill_usage_store.contains("ON CONFLICT"));
    assert!(resources.contains("pub(super) async fn load_memory_stores"));
    assert!(resources.contains("RepositoryAccessMaterial"));
}

#[test]
fn bootstrap_injects_harness_credential_access_capability() {
    let builder = source("src/kernel/harness_input_builder.rs");
    let setup = source("src/kernel/runner/setup.rs");
    let flows = source("src/kernel/runner/flows.rs");
    let context = source("src/kernel/sandbox_resolver/context.rs");
    let recovery_adapter = source("src/bootstrap/network_policy_material.rs");
    let factories = source("src/bootstrap/runtime_factories.rs");

    for source in [&setup, &context] {
        assert!(
            !source.contains("CredentialMaterialAccessService::new"),
            "application flow hard-codes the PostgreSQL credential capability"
        );
    }

    assert!(builder.contains("credential_access: CredentialMaterialAccessService"));
    assert!(builder.contains("pub(crate) fn with_services"));
    assert!(context.contains("credential_access: CredentialMaterialAccessService"));
    assert!(flows.contains("harness_input_builder: HarnessInputBuilder"));
    assert!(recovery_adapter.contains("credential_access: CredentialMaterialAccessService"));
    assert!(factories.contains("build_credential_access"));
    assert!(factories.contains("CredentialMaterialAccessService::new"));
}
