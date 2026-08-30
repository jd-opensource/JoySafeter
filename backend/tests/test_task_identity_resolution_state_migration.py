from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "alembic/versions/20260830_000002_task_identity_resolution_state.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("task_identity_resolution_state_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OperationRecorder:
    def __init__(self) -> None:
        self.operations: list[tuple[str, object]] = []

    def add_column(self, table_name: str, column) -> None:
        self.operations.append(("add_column", (table_name, column.name)))

    def execute(self, statement) -> None:
        self.operations.append(("execute", str(statement)))

    def create_check_constraint(self, name: str, table_name: str, condition: str) -> None:
        self.operations.append(("create_check_constraint", (name, table_name, condition)))

    def create_index(self, name: str, table_name: str, columns, **kwargs) -> None:
        self.operations.append(("create_index", (name, table_name, tuple(columns), kwargs)))

    def drop_index(self, name: str, *, table_name: str) -> None:
        self.operations.append(("drop_index", (name, table_name)))

    def drop_constraint(self, name: str, table_name: str, *, type_: str) -> None:
        self.operations.append(("drop_constraint", (name, table_name, type_)))

    def drop_column(self, table_name: str, column_name: str) -> None:
        self.operations.append(("drop_column", (table_name, column_name)))


def test_upgrade_adds_fenced_resolution_state_and_backfills_existing_rows() -> None:
    migration = _load_migration()
    recorder = OperationRecorder()
    migration.op = recorder

    migration.upgrade()

    assert migration.revision == "20260830_000002"
    assert migration.down_revision == "20260830_000001"
    assert recorder.operations[:3] == [
        ("add_column", ("joysafeter_task_identity_contexts", "state")),
        ("add_column", ("joysafeter_task_identity_contexts", "resolution_id")),
        (
            "add_column",
            ("joysafeter_task_identity_contexts", "resolution_expires_at"),
        ),
    ]
    sql = "\n".join(value for operation, value in recorder.operations if operation == "execute")
    assert "WHEN consumed_at IS NOT NULL THEN 'issued'" in sql
    assert "WHEN encrypted_credential IS NULL OR expires_at <= now() THEN 'expired'" in sql
    constraints = [value for operation, value in recorder.operations if operation == "create_check_constraint"]
    assert any(value[0] == "ck_task_identity_resolution_state" for value in constraints)
    assert any(value[0] == "ck_task_identity_resolution_claim" for value in constraints)
    assert any(value[0] == "ck_task_identity_resolution_material" for value in constraints)


def test_downgrade_refuses_active_resolution_claims_before_dropping_state() -> None:
    migration = _load_migration()
    recorder = OperationRecorder()
    migration.op = recorder

    migration.downgrade()

    assert recorder.operations[0][0] == "execute"
    guard = recorder.operations[0][1]
    assert "state = 'resolving'" in guard
    assert "cannot downgrade task identity resolution state" in guard
