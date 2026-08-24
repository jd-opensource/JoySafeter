from pathlib import Path
from re import DOTALL, findall

KERNEL_ROOT = Path(__file__).parents[1] / "app" / "joysafeter_orchestrator_rs" / "src" / "kernel"
RUNTIME_CONSUMERS = ("harness_input_builder.rs", "sandbox_resolver.rs")
CREDENTIAL_STORE = KERNEL_ROOT / "credentials" / "store.rs"
MCP_RUNTIME_PLAN = KERNEL_ROOT / "mcp_runtime_plan.rs"


def _select_statements(source: str) -> list[str]:
    return [
        statement
        for statement in findall(r'r#"(.*?)"#', source, flags=DOTALL)
        if "SELECT" in statement and "joysafeter_credentials" in statement
    ]


def test_runtime_consumers_delegate_credential_reads_to_the_central_store() -> None:
    harness_source = (KERNEL_ROOT / "harness_input_builder.rs").read_text()
    sandbox_source = (KERNEL_ROOT / "sandbox_resolver.rs").read_text()

    for relative_path, source in (
        ("harness_input_builder.rs", harness_source),
        ("sandbox_resolver.rs", sandbox_source),
    ):
        assert _select_statements(source) == [], relative_path
        assert "CredentialMaterialAccessService" in source, relative_path

    assert ".resolve_model_runtime_config(" in harness_source
    assert "resolve_mcp_runtime_plan_from_metadata(" in harness_source
    runtime_plan_source = MCP_RUNTIME_PLAN.read_text()
    assert ".load_mcp_member_metadata(" in runtime_plan_source
    assert ".resolve_mcp_member(" in runtime_plan_source
    assert ".resolve_model(" in sandbox_source
    assert "resolve_mcp_runtime_plan_with_access(" in sandbox_source
    assert ".resolve_http_egress_field(" in sandbox_source


def test_central_store_queries_load_lifecycle_state_for_fail_closed_validation() -> None:
    source = CREDENTIAL_STORE.read_text()
    credential_queries = _select_statements(source)

    assert credential_queries
    assert all("archived_at" in statement for statement in credential_queries)
    assert all("deleted_at" in statement for statement in credential_queries)
    assert "validate_credential_metadata_row(&row)?" in source
    assert "validate_mcp_metadata_row(&row, group_id)" in source
    assert "CredentialRuntimeError::Archived" in source
    assert "CredentialRuntimeError::NotFound" in source


def test_mcp_member_query_joins_only_active_credentials() -> None:
    source = CREDENTIAL_STORE.read_text()
    credential_queries = _select_statements(source)
    mcp_query = next(
        statement for statement in credential_queries if "joysafeter_session_credential_groups" in statement
    )

    credential_join = mcp_query.split("LEFT JOIN joysafeter_credentials AS credentials", maxsplit=1)[1].split(
        "WHERE sessions.id", maxsplit=1
    )[0]

    assert "credentials.archived_at IS NULL" in credential_join
    assert "credentials.deleted_at IS NULL" in credential_join
