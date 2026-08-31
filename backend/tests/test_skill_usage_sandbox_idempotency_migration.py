from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "alembic/versions/20260830_000004_skill_usage_sandbox_idempotency.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("skill_usage_sandbox_idempotency_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OperationRecorder:
    def __init__(self) -> None:
        self.operations: list[tuple[str, object]] = []

    def add_column(self, table_name: str, column) -> None:
        self.operations.append(("add_column", (table_name, column.name, column.nullable)))

    def create_index(self, name: str, table_name: str, columns, **kwargs) -> None:
        self.operations.append(("create_index", (name, table_name, tuple(columns), kwargs)))

    def drop_index(self, name: str, table_name: str) -> None:
        self.operations.append(("drop_index", (name, table_name)))

    def drop_column(self, table_name: str, column_name: str) -> None:
        self.operations.append(("drop_column", (table_name, column_name)))


def test_upgrade_adds_nullable_sandbox_identity_and_partial_unique_index() -> None:
    migration = _load_migration()
    recorder = OperationRecorder()
    migration.op = recorder

    migration.upgrade()

    assert migration.revision == "20260830_000004"
    assert migration.down_revision == "20260830_000003"
    assert recorder.operations[0] == (
        "add_column",
        ("joysafeter_skill_usage_log", "sandbox_id", True),
    )
    operation, payload = recorder.operations[1]
    assert operation == "create_index"
    name, table_name, columns, kwargs = payload
    assert name == "uq_skill_usage_log_sandbox_artifact"
    assert table_name == "joysafeter_skill_usage_log"
    assert columns == (
        "sandbox_id",
        "skill_id",
        "skill_version",
        "target",
        "artifact_hash",
    )
    assert kwargs["unique"] is True
    assert str(kwargs["postgresql_where"]) == "sandbox_id IS NOT NULL"


def test_downgrade_removes_index_before_column() -> None:
    migration = _load_migration()
    recorder = OperationRecorder()
    migration.op = recorder

    migration.downgrade()

    assert recorder.operations == [
        (
            "drop_index",
            (
                "uq_skill_usage_log_sandbox_artifact",
                "joysafeter_skill_usage_log",
            ),
        ),
        ("drop_column", ("joysafeter_skill_usage_log", "sandbox_id")),
    ]
