from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "alembic/versions/20260830_000003_remove_cluster_membership_registry.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("remove_cluster_membership_registry_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OperationRecorder:
    def __init__(self) -> None:
        self.operations: list[tuple[str, object]] = []

    def drop_table(self, table_name: str) -> None:
        self.operations.append(("drop_table", table_name))

    def f(self, name: str) -> str:
        return name

    def create_table(self, table_name: str, *columns) -> None:
        self.operations.append(
            (
                "create_table",
                (
                    table_name,
                    tuple(column.name for column in columns if column.__class__.__name__ == "Column"),
                ),
            )
        )

    def create_index(self, name: str, table_name: str, columns, **kwargs) -> None:
        self.operations.append(("create_index", (name, table_name, tuple(columns), kwargs)))


def test_upgrade_removes_legacy_postgres_cluster_registry() -> None:
    migration = _load_migration()
    recorder = OperationRecorder()
    migration.op = recorder

    migration.upgrade()

    assert migration.revision == "20260830_000003"
    assert migration.down_revision == "20260830_000002"
    assert recorder.operations == [("drop_table", "joysafeter_cluster_members")]


def test_downgrade_restores_registry_shape_without_claiming_runtime_ownership() -> None:
    migration = _load_migration()
    recorder = OperationRecorder()
    migration.op = recorder

    migration.downgrade()

    assert recorder.operations[0][0] == "create_table"
    table_name, columns = recorder.operations[0][1]
    assert table_name == "joysafeter_cluster_members"
    assert columns == (
        "instance_id",
        "role",
        "started_at",
        "heartbeat_at",
        "expires_at",
        "metadata",
        "created_at",
        "updated_at",
    )
    assert recorder.operations[1][0] == "create_index"
