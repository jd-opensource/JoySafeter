from pathlib import Path
from re import DOTALL, findall

RUST_ROOT = Path(__file__).parents[1] / "app" / "joysafeter_orchestrator_rs" / "src" / "kernel"


def test_mcp_runtime_queries_exclude_archived_credentials() -> None:
    for relative_path in ("harness_input_builder.rs", "sandbox_resolver.rs"):
        source = (RUST_ROOT / relative_path).read_text()
        matching_queries = [
            statement
            for statement in findall(r'r#"(.*?)"#', source, flags=DOTALL)
            if "FROM joysafeter_credentials" in statement
            and "kind = 'mcp'" in statement
            and "group_id = ANY($1)" in statement
        ]
        assert matching_queries, relative_path
        assert all("archived_at IS NULL" in statement for statement in matching_queries), relative_path


def test_all_runtime_credential_queries_exclude_archived_credentials() -> None:
    for relative_path in ("harness_input_builder.rs", "sandbox_resolver.rs"):
        source = (RUST_ROOT / relative_path).read_text()
        credential_queries = [
            statement
            for statement in findall(r'r#"(.*?)"#', source, flags=DOTALL)
            if "SELECT" in statement and "FROM joysafeter_credentials" in statement
        ]
        assert credential_queries, relative_path
        assert all("archived_at IS NULL" in statement for statement in credential_queries), relative_path
