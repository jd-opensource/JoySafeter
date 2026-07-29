"""Project-scoped skill-name uniqueness (Bucket 2).

Skill identity moved from ``(owner_id, name)`` to ``(project_id, name)``. These
tests pin both enforcement layers against a real (testcontainers) Postgres so
the alembic migration's UNIQUE constraint is actually exercised:

  * the service pre-check (``get_by_name_and_project``) raises a friendly 409;
  * the DB constraint is the backstop for races / frontmatter-overridden names;
  * the SAME name in DIFFERENT projects is allowed (the whole point of the
    move — two projects are independent namespaces, matching agents/env/secrets).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from unittest.mock import AsyncMock

from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_skill import JoySafeterSkill
from app.joysafeter_domain.services.joysafeter_skill_service import SkillService
from app.joysafeter_shared.common.app_errors import InvalidRequestError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterRole

pytestmark = pytest.mark.asyncio


async def _user(db, *, name: str = "U") -> AuthUser:
    user = AuthUser(id=f"user-{uuid.uuid4()}", name=name, email=f"{uuid.uuid4()}@example.com")
    db.add(user)
    await db.flush()
    return user


async def _org(db) -> Organization:
    org = Organization(id=f"org-{uuid.uuid4()}", name="Org", slug=f"org-{uuid.uuid4()}")
    db.add(org)
    await db.flush()
    return org


async def _project(db, *, org_id: str) -> Project:
    proj = Project(id=f"proj-{uuid.uuid4()}", org_id=org_id, name="P", slug=f"p-{uuid.uuid4()}")
    db.add(proj)
    await db.flush()
    return proj


def _svc(db) -> SkillService:
    """A SkillService whose security scan is stubbed out — creation is gated at
    the API layer, so the scan is orthogonal to the uniqueness contract."""
    svc = SkillService(db, active_org_id=None, caller_org_role=JoySafeterRole.MEMBER)
    svc.security_service.scan_for_write = AsyncMock(return_value=None)
    return svc


async def test_same_name_same_project_conflicts_at_service_layer(db_session):
    """Second create of the same name in the SAME project is rejected by the
    service pre-check — regardless of owner (bob is not alice)."""
    org = await _org(db_session)
    proj = await _project(db_session, org_id=org.id)
    alice = await _user(db_session, name="Alice")
    bob = await _user(db_session, name="Bob")
    svc = _svc(db_session)

    await svc.create_skill(
        created_by_id=alice.id,
        name="shared-name",
        description="first",
        content="# Skill\nbody",
        project_id=proj.id,
    )

    with pytest.raises(InvalidRequestError) as ei:
        await svc.create_skill(
            created_by_id=bob.id,  # different owner — used to be allowed
            name="shared-name",
            description="second",
            content="# Skill\nbody",
            project_id=proj.id,
        )
    assert ei.value.code == "SKILL_NAME_ALREADY_EXISTS"


async def test_same_name_different_projects_allowed(db_session):
    """The core new behavior: the same name lives happily in two projects."""
    org = await _org(db_session)
    proj_a = await _project(db_session, org_id=org.id)
    proj_b = await _project(db_session, org_id=org.id)
    alice = await _user(db_session, name="Alice")
    svc = _svc(db_session)

    s_a = await svc.create_skill(
        created_by_id=alice.id,
        name="shared-name",
        description="in A",
        content="# Skill\nbody",
        project_id=proj_a.id,
    )
    s_b = await svc.create_skill(
        created_by_id=alice.id,
        name="shared-name",
        description="in B",
        content="# Skill\nbody",
        project_id=proj_b.id,
    )
    assert s_a.project_id == proj_a.id
    assert s_b.project_id == proj_b.id
    assert s_a.id != s_b.id


async def test_db_constraint_backstops_duplicate_in_project(db_session):
    """Defense-in-depth: even bypassing the service pre-check, the migration's
    ``skills_project_name_unique`` constraint rejects a duplicate (project, name)
    at flush time. This is what catches a race two saves in flight."""
    org = await _org(db_session)
    proj = await _project(db_session, org_id=org.id)
    alice = await _user(db_session, name="Alice")
    bob = await _user(db_session, name="Bob")

    db_session.add(
        JoySafeterSkill(
            name="dup",
            description="a",
            content="x",
            tags=[],
            created_by_id=alice.id,
            owner_id=alice.id,
            project_id=proj.id,
        )
    )
    await db_session.flush()

    db_session.add(
        JoySafeterSkill(
            name="dup",
            description="b",
            content="x",
            tags=[],
            created_by_id=bob.id,
            owner_id=bob.id,  # different owner, same (project, name)
            project_id=proj.id,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
