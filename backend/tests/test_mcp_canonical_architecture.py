import importlib
import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = _ROOT / "backend/alembic/versions/20260824_000001_mcp_contract_cutover.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("mcp_contract_cutover", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mcp_cutover_migration_canonicalizes_persisted_servers() -> None:
    migration = _load_migration()

    assert migration.canonicalize_mcp_servers(
        [
            {"type": "url", "name": "docs", "url": "https://example.com/mcp"},
            {"type": "stdio", "name": "local", "command": "node"},
        ],
        location="agent",
    ) == [
        {
            "type": "streamable_http",
            "name": "docs",
            "url": "https://example.com/mcp",
            "auth_requirement": "optional",
        },
        {"type": "local_stdio", "name": "local", "command": "node"},
    ]


def test_mcp_cutover_migration_rejects_unknown_persisted_transport() -> None:
    migration = _load_migration()

    with pytest.raises(RuntimeError, match="unsupported MCP transport"):
        migration.canonicalize_mcp_servers(
            [{"type": "websocket", "name": "future", "url": "https://example.com/mcp"}],
            location="agent",
        )


@pytest.mark.parametrize(
    "server",
    [
        {
            "type": "streamable_http",
            "name": "remote",
            "url": "https://example.com/mcp",
            "auth_requirement": "required",
            "command": None,
        },
        {"type": "local_stdio", "name": "local", "command": "node", "args": "--stdio"},
        {"type": "local_stdio", "name": "local", "command": "node", "env": []},
    ],
)
def test_mcp_cutover_migration_rejects_noncanonical_server_shapes(
    server: dict[str, object],
) -> None:
    migration = _load_migration()

    with pytest.raises(RuntimeError, match="noncanonical MCP field|must be"):
        migration.canonicalize_mcp_servers([server], location="agent")


def test_mcp_cutover_migration_removes_obsolete_networking_fields() -> None:
    migration = _load_migration()

    assert migration.canonicalize_environment_config(
        {
            "networking": {
                "net_type": "limited",
                "allowed_hosts": ["example.com"],
                "allow_mcp_servers": True,
            }
        },
        location="environment",
    ) == {"networking": {"type": "limited", "allowed_hosts": ["example.com"]}}


@pytest.mark.parametrize("scheme", ["oauth", "mcp_oauth"])
def test_mcp_cutover_migration_preserves_disabled_oauth_tombstones(scheme: str) -> None:
    migration = _load_migration()

    assert migration.canonicalize_mcp_auth_scheme(scheme, location="credential") == scheme


def test_mcp_contract_has_no_legacy_runtime_or_networking_switches() -> None:
    proto = (_ROOT / "proto/joysafeter.proto").read_text()
    runtime_plan = (_ROOT / "backend/app/joysafeter_orchestrator_rs/src/kernel/mcp_runtime_plan.rs").read_text()
    runner = (_ROOT / "sandbox-runner/crates/joysafeter-runner/src/runner.rs").read_text()
    sessions = (_ROOT / "backend/app/joysafeter_api/api/v1/sessions.py").read_text()
    environment_schema = (_ROOT / "backend/app/joysafeter_domain/schemas/joysafeter_environment.py").read_text()

    assert "string server_type" not in proto
    assert '"url" | "http" | "streamable-http"' not in runtime_plan
    assert "server.server_type" not in runner
    assert "_networking_with_agent_mcp_hosts" not in sessions
    assert "allow_mcp_servers" not in environment_schema


def test_generated_grpc_module_imports_from_its_package() -> None:
    module = importlib.import_module("app.joysafeter_shared.orchestrator_bridge.proto.joysafeter_pb2_grpc")

    assert module.AgentBridgeStub.__name__ == "AgentBridgeStub"
