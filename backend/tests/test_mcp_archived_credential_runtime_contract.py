from pathlib import Path
from re import DOTALL, findall

KERNEL_ROOT = Path(__file__).parents[1] / "app" / "joysafeter_orchestrator_rs" / "src" / "kernel"
RUNTIME_CONSUMERS = ("harness_input_builder.rs", "sandbox_resolver.rs")
CREDENTIAL_STORE = KERNEL_ROOT / "credentials" / "store.rs"


def _select_statements(source: str) -> list[str]:
    return [
        statement
        for statement in findall(r'r#"(.*?)"#', source, flags=DOTALL)
        if "SELECT" in statement and "joysafeter_credentials" in statement
    ]


def test_runtime_consumers_delegate_credential_reads_to_the_central_store() -> None:
    for relative_path in RUNTIME_CONSUMERS:
        source = (KERNEL_ROOT / relative_path).read_text()
        assert _select_statements(source) == [], relative_path
        assert "CredentialStore" in source, relative_path
        assert ".get_active(" in source, relative_path
        assert ".load_session_mcp_members(" in source, relative_path


def test_central_store_queries_load_lifecycle_state_for_fail_closed_validation() -> None:
    source = CREDENTIAL_STORE.read_text()
    credential_queries = _select_statements(source)

    assert len(credential_queries) == 3
    assert all("archived_at" in statement for statement in credential_queries)
    assert all("deleted_at" in statement for statement in credential_queries)
    assert "validate_resource_state(&row)?;" in source
    assert "CredentialRuntimeError::Archived" in source
    assert "CredentialRuntimeError::NotFound" in source
