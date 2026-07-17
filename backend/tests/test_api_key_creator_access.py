import hashlib
import uuid
from datetime import datetime, timezone

import pytest

from app.joysafeter_domain.models.joysafeter_api_key import JoySafeterApiKey
from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Member, Organization
from app.joysafeter_domain.models.joysafeter_project import Project, ProjectMember
from app.joysafeter_shared.common.app_errors import AccessDeniedError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterRole
from app.joysafeter_shared.common.joysafeter_auth.dependencies import _auth_via_api_key


async def _key_setup(
    db_session,
    *,
    creator_org_role: str | None,
    creator_project_role: str | None,
    key_role: str = "editor",
) -> str:
    """Create an org, project, creator user and an API key. Returns the raw key.

    creator_org_role None => the creator has NO org Member row (removed).
    creator_project_role None => the creator has NO ProjectMember row.
    """
    org_id = f"org-{uuid.uuid4()}"
    creator = AuthUser(id=f"user-{uuid.uuid4()}", name="Creator", email=f"{uuid.uuid4()}@example.com")
    org = Organization(id=org_id, name="Org", slug=f"org-{uuid.uuid4()}")
    project = Project(id=f"proj-{uuid.uuid4()}", org_id=org_id, name="P", slug="default", is_default=True)
    db_session.add_all([creator, org, project])
    await db_session.flush()
    if creator_org_role is not None:
        db_session.add(Member(user_id=creator.id, organization_id=org_id, role=creator_org_role))
    if creator_project_role is not None:
        db_session.add(
            ProjectMember(project_id=project.id, user_id=creator.id, role=creator_project_role)
        )
    raw_key = f"sk-{uuid.uuid4()}"
    db_session.add(
        JoySafeterApiKey(
            project_id=project.id,
            org_id=org_id,
            name="k",
            key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
            key_prefix="sk-test",
            created_by=creator.id,
            role=key_role,
        )
    )
    await db_session.commit()
    return raw_key


@pytest.mark.asyncio
async def test_key_rejected_when_creator_removed_from_org(db_session):
    # CB-3 regression: a key whose creator was removed from the org must stop
    # authenticating — including on read paths that never re-verify context.
    raw_key = await _key_setup(db_session, creator_org_role=None, creator_project_role=None)
    with pytest.raises(AccessDeniedError) as exc_info:
        await _auth_via_api_key(raw_key, db_session)
    assert exc_info.value.code == "AUTH_API_KEY_ACCESS_REVOKED"


@pytest.mark.asyncio
async def test_key_rejected_when_creator_lost_project_access(db_session):
    # Creator is still an org member (developer) but has no ProjectMember row on
    # the key's project (grant revoked) → non-super-user has no access → rejected.
    raw_key = await _key_setup(
        db_session, creator_org_role="member", creator_project_role=None
    )
    with pytest.raises(AccessDeniedError) as exc_info:
        await _auth_via_api_key(raw_key, db_session)
    assert exc_info.value.code == "AUTH_API_KEY_ACCESS_REVOKED"


@pytest.mark.asyncio
async def test_key_valid_when_creator_has_project_row(db_session):
    # Happy path: creator retains an explicit ProjectMember row. The key
    # authenticates and keeps its own capped identity (not rebuilt from creator).
    raw_key = await _key_setup(
        db_session, creator_org_role="member", creator_project_role="editor", key_role="viewer"
    )
    ctx = await _auth_via_api_key(raw_key, db_session)
    assert ctx is not None
    assert ctx.principal_type == "api_key"
    assert ctx.role is JoySafeterRole.MEMBER
    assert ctx.project_role == "viewer"


@pytest.mark.asyncio
async def test_key_valid_when_creator_is_org_superuser_without_row(db_session):
    # An org admin/owner reaches every project org-wide, so their key stays valid
    # without a ProjectMember row.
    raw_key = await _key_setup(
        db_session, creator_org_role="admin", creator_project_role=None
    )
    ctx = await _auth_via_api_key(raw_key, db_session)
    assert ctx is not None
    assert ctx.principal_type == "api_key"


@pytest.mark.asyncio
async def test_revoked_key_returns_none_before_creator_check(db_session):
    # A revoked key must still short-circuit to None (not the creator-access
    # error), preserving the existing INVALID_API_KEY behavior.
    org_id = f"org-{uuid.uuid4()}"
    creator = AuthUser(id=f"user-{uuid.uuid4()}", name="C", email=f"{uuid.uuid4()}@example.com")
    org = Organization(id=org_id, name="Org", slug=f"org-{uuid.uuid4()}")
    project = Project(id=f"proj-{uuid.uuid4()}", org_id=org_id, name="P", slug="default", is_default=True)
    db_session.add_all([creator, org, project])
    await db_session.flush()
    raw_key = f"sk-{uuid.uuid4()}"
    db_session.add(
        JoySafeterApiKey(
            project_id=project.id,
            org_id=org_id,
            name="k",
            key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
            key_prefix="sk-test",
            created_by=creator.id,
            role="editor",
            revoked_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()
    assert await _auth_via_api_key(raw_key, db_session) is None
