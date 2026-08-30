from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db


MIGRATION_PATH = Path(__file__).resolve().parents[1] / "alembic/versions/20260829_000001_runner_auth_state.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("runner_auth_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OperationRecorder:
    def __init__(self) -> None:
        self.executed: list[str] = []
        self.dropped_indexes: list[tuple[str, str | None]] = []
        self.created_indexes: list[tuple[str, str, bool, str]] = []

    def add_column(self, *_args, **_kwargs) -> None:
        pass

    def create_check_constraint(self, *_args, **_kwargs) -> None:
        pass

    def execute(self, statement) -> None:
        self.executed.append(str(statement))

    def drop_index(self, name: str, *, table_name: str | None = None) -> None:
        self.dropped_indexes.append((name, table_name))

    def create_index(
        self,
        name: str,
        table_name: str,
        _columns,
        *,
        unique: bool,
        postgresql_where,
    ) -> None:
        self.created_indexes.append((name, table_name, unique, str(postgresql_where)))

    def drop_constraint(self, *_args, **_kwargs) -> None:
        pass

    def drop_column(self, *_args, **_kwargs) -> None:
        pass


def test_upgrade_scrubs_legacy_token_and_excludes_revoked_rows_from_active_index() -> None:
    migration = _load_migration()
    recorder = OperationRecorder()
    migration.op = recorder

    migration.upgrade()

    sql = "\n".join(recorder.executed)
    assert "'runner_token'" in sql
    assert "JOYSAFETER_RUNNER_TOKEN" in sql
    assert recorder.dropped_indexes == [("idx_csb_active_session_unique", "joysafeter_sandboxes")]
    assert recorder.created_indexes == [
        (
            "idx_csb_active_session_unique",
            "joysafeter_sandboxes",
            True,
            "chat_session_id IS NOT NULL AND destroyed_at IS NULL AND "
            "runner_auth_state <> 'revoked' AND status IN "
            "('creating', 'provisioning', 'idle', 'running', 'stopped', 'error')",
        )
    ]


def test_downgrade_refuses_live_digest_only_runner_credentials() -> None:
    migration = _load_migration()
    recorder = OperationRecorder()
    migration.op = recorder

    migration.downgrade()

    assert recorder.executed
    guard = recorder.executed[0]
    assert "runner_auth_state IN ('admission', 'active')" in guard
    assert "destroyed_at IS NULL" in guard
    assert "cannot downgrade runner auth state" in guard
