import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = _ROOT / "backend/alembic/versions/20260825_000005_validate_mcp_transport_auth_contract.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("validate_mcp_transport_auth_contract", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mcp_transport_auth_migration_accepts_supported_matrix() -> None:
    migration = _load_migration()

    migration.validate_mcp_servers(
        [
            {
                "type": "streamable_http",
                "name": "tools",
                "url": "https://example.com/mcp",
                "auth_requirement": "required",
            },
            {
                "type": "sse",
                "name": "events",
                "url": "https://example.com/sse",
                "auth_requirement": "none",
            },
            {"type": "local_stdio", "name": "local", "command": "node"},
        ],
        location="joysafeter_agents.agent-a.mcp_servers",
    )


@pytest.mark.parametrize("auth_requirement", ["required", "optional"])
def test_mcp_transport_auth_migration_rejects_sse_managed_auth(auth_requirement: str) -> None:
    migration = _load_migration()

    with pytest.raises(
        RuntimeError,
        match=r"joysafeter_agents\.agent-a\.mcp_servers\[0\].*SSE.*auth_requirement.*none",
    ):
        migration.validate_mcp_servers(
            [
                {
                    "type": "sse",
                    "name": "events",
                    "url": "https://example.com/sse",
                    "auth_requirement": auth_requirement,
                }
            ],
            location="joysafeter_agents.agent-a.mcp_servers",
        )
