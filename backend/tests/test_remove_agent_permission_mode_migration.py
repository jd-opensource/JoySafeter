from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "alembic/versions/20260830_000001_remove_agent_permission_mode.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("remove_agent_permission_mode_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OperationRecorder:
    def __init__(self) -> None:
        self.operations: list[tuple[str, object]] = []

    def execute(self, statement) -> None:
        self.operations.append(("execute", str(statement)))

    def drop_column(self, table_name: str, column_name: str) -> None:
        self.operations.append(("drop_column", (table_name, column_name)))

    def add_column(self, table_name: str, column) -> None:
        self.operations.append(("add_column", (table_name, column.name)))


def test_upgrade_scrubs_snapshot_copies_before_dropping_live_column() -> None:
    migration = _load_migration()
    recorder = OperationRecorder()
    migration.op = recorder

    migration.upgrade()

    assert recorder.operations[-1] == (
        "drop_column",
        ("joysafeter_agents", "permission_mode"),
    )
    sql = "\n".join(value for operation, value in recorder.operations if operation == "execute")
    assert "UPDATE joysafeter_sessions" in sql
    assert "agent_snapshot - 'permission_mode'" in sql
    assert "UPDATE joysafeter_agent_versions" in sql
    assert "snapshot - 'permission_mode'" in sql


def test_downgrade_reconstructs_legacy_projection_from_tools() -> None:
    migration = _load_migration()
    recorder = OperationRecorder()
    migration.op = recorder

    migration.downgrade()

    assert recorder.operations[0] == (
        "add_column",
        ("joysafeter_agents", "permission_mode"),
    )
    sql = "\n".join(value for operation, value in recorder.operations if operation == "execute")
    assert "jsonb_array_elements" in sql
    assert "always_ask" in sql
    assert "jsonb_set(agent_snapshot" in sql
    assert "jsonb_set(snapshot" in sql
