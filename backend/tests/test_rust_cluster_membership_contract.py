from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_cluster_membership_migration_creates_durable_pg_registry():
    migration = _read("backend/alembic/versions/20260703_000009_add_cluster_members.py")

    assert 'revision: str = "20260703_000009"' in migration
    assert 'down_revision: Union[str, None] = "20260703_000008"' in migration
    assert '"joysafeter_cluster_members"' in migration
    assert '"instance_id"' in migration
    assert '"heartbeat_at"' in migration
    assert '"expires_at"' in migration
    assert '"idx_joysafeter_cluster_members_role_expires_at"' in migration


def test_rust_orchestrator_registers_and_heartbeats_pg_cluster_member():
    queries = _read("backend/app/joysafeter_orchestrator_rs/src/db/queries.rs")
    main = _read("backend/app/joysafeter_orchestrator_rs/src/main.rs")

    assert "pub async fn register_cluster_member" in queries
    assert "pub async fn heartbeat_cluster_member" in queries
    assert "ON CONFLICT (instance_id) DO UPDATE" in queries
    assert "started_at = EXCLUDED.started_at" in queries
    assert "heartbeat_at = EXCLUDED.heartbeat_at" in queries
    assert "expires_at = EXCLUDED.expires_at" in queries

    assert "register_cluster_member(" in main
    assert "heartbeat_cluster_member(" in main
    assert '"orchestrator"' in main
    assert "Postgres cluster member heartbeat registered" in main

