"""Alembic chain and policy tests plus current Skill schema checks."""

from __future__ import annotations

import uuid
from itertools import pairwise
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"


def _config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    # alembic.ini's script_location is relative to backend/, so we need to
    # anchor it explicitly when pytest invokes from anywhere.
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


@pytest.mark.no_db
def test_chain_is_linear_with_single_head():
    cfg = _config()
    script = ScriptDirectory.from_config(cfg)
    assert len(script.get_heads()) == 1
    revisions = list(script.walk_revisions(base="base", head="heads"))
    assert revisions
    assert revisions[-1].down_revision is None
    assert all(revision.down_revision == parent.revision for revision, parent in pairwise(revisions))


@pytest.mark.no_db
def test_upgrade_sql_rejects_the_online_only_unified_credential_migration():
    cfg = _config()
    with pytest.raises(RuntimeError, match="online-only"):
        command.upgrade(cfg, "base:head", sql=True)


@pytest.mark.no_db
def test_downgrade_sql_rejects_the_irreversible_unified_credential_migration():
    cfg = _config()
    with pytest.raises(RuntimeError, match="credential-reference alias removal is irreversible"):
        command.downgrade(cfg, "head:base", sql=True)


# ---------------------------------------------------------------------------
# Current Skill schema checks against the migrated Postgres fixture.
# ---------------------------------------------------------------------------


async def _columns(session: AsyncSession, table: str) -> set[str]:
    rows = await session.execute(
        text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"),
        {"t": table},
    )
    return {r[0] for r in rows}


@pytest.mark.asyncio
async def test_migration_adds_version_pointer_columns(db_session: AsyncSession):
    """org_version_id / public_version_id land on joysafeter_skills and
    review_target_visibility lands on joysafeter_skill_versions after
    upgrade head."""
    skill_cols = await _columns(db_session, "joysafeter_skills")
    assert "org_version_id" in skill_cols
    assert "public_version_id" in skill_cols

    version_cols = await _columns(db_session, "joysafeter_skill_versions")
    assert "review_target_visibility" in version_cols


@pytest.mark.asyncio
async def test_migration_drops_root_path(db_session: AsyncSession):
    """root_path was always NULL with no readers/writers; the migration
    removes it entirely."""
    skill_cols = await _columns(db_session, "joysafeter_skills")
    assert "root_path" not in skill_cols


@pytest.mark.asyncio
async def test_insert_skill_with_null_version_pointers(db_session: AsyncSession):
    """A skill row inserts fine with both version pointers left NULL — the
    columns are nullable FKs, not required."""
    user_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO joysafeter_users (id, name, email, hashed_password, is_active, email_verified, is_super_user, failed_login_attempts, created_at, updated_at) "
            "VALUES (:id, :name, :email, 'x', true, false, false, 0, now(), now())"
        ),
        {"id": user_id, "name": "migration-test-user", "email": f"{user_id}@example.com"},
    )
    # project_id is NOT NULL, so seed an org + project to satisfy the FK.
    org_id = uuid.uuid4()
    project_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO joysafeter_organizations (id, name, slug, storage_used_bytes, departed_member_usage, created_at, updated_at) "
            "VALUES (:id, 'mig-test-org', :slug, 0, 0, now(), now())"
        ),
        {"id": org_id, "slug": f"org-slug-{uuid.uuid4()}"},
    )
    await db_session.execute(
        text(
            "INSERT INTO joysafeter_organization_projects (id, org_id, name, slug, is_default, created_at, updated_at) "
            "VALUES (:id, :org_id, 'mig-test-project', :slug, false, now(), now())"
        ),
        {"id": project_id, "org_id": org_id, "slug": f"proj-slug-{uuid.uuid4()}"},
    )
    skill_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO joysafeter_skills "
            "(id, name, description, content, tags, source_type, created_by_id, project_id, "
            " visibility, metadata, allowed_tools, security_status, "
            " security_issues_count, security_critical_count, security_high_count, "
            " security_medium_count, security_low_count, lifecycle_status, "
            " org_version_id, public_version_id, created_at, updated_at) "
            "VALUES (:id, 'n', 'd', 'c', '[]'::jsonb, 'local', :uid, :project_id, "
            " 'project', '{}'::jsonb, '[]'::jsonb, 'not_scanned', "
            " 0, 0, 0, 0, 0, 'draft', NULL, NULL, now(), now())"
        ),
        {"id": skill_id, "uid": user_id, "project_id": project_id},
    )
    await db_session.commit()

    got = await db_session.execute(
        text("SELECT org_version_id, public_version_id FROM joysafeter_skills WHERE id = :id"),
        {"id": skill_id},
    )
    row = got.one()
    assert row[0] is None
    assert row[1] is None
