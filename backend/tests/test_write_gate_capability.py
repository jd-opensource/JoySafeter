import uuid

import pytest

from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Member, Organization
from app.joysafeter_domain.models.joysafeter_project import Project, ProjectMember
from app.joysafeter_shared.common.app_errors import AccessDeniedError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.common.joysafeter_auth.dependencies import (
    _require_admin_context,
    _require_write_context,
)
from app.joysafeter_shared.ids import OrganizationId, OrganizationMemberId, ProjectId, ProjectMemberId, UserId


async def _setup(db_session, project_role: str) -> JoySafeterAuthContext:
    org_id = OrganizationId.new()
    user = AuthUser(id=UserId.new(), name="Dev", email=f"{uuid.uuid4()}@example.com")
    org = Organization(id=org_id, name="Org", slug=f"org-{uuid.uuid4()}")
    project = Project(id=ProjectId.new(), org_id=org_id, name="P", slug="default", is_default=True)
    db_session.add_all([user, org, project])
    await db_session.flush()
    db_session.add_all(
        [
            Member(id=OrganizationMemberId.new(), user_id=user.id, organization_id=org_id, role="member"),
            ProjectMember(id=ProjectMemberId.new(), project_id=project.id, user_id=user.id, role=project_role),
        ]
    )
    await db_session.commit()
    return JoySafeterAuthContext(user_id=user.id, org_id=org_id, project_id=project.id, role=JoySafeterRole.MEMBER)


@pytest.mark.asyncio
async def test_write_gate_denies_project_viewer(db_session):
    ctx = await _setup(db_session, project_role="viewer")
    with pytest.raises(AccessDeniedError) as exc_info:
        await _require_write_context(db_session, ctx)
    assert exc_info.value.code == "JOYSAFETER_WRITE_REQUIRED"


@pytest.mark.asyncio
async def test_write_gate_allows_project_editor(db_session):
    ctx = await _setup(db_session, project_role="editor")
    verified = await _require_write_context(db_session, ctx)
    assert verified.project_role == "editor"


async def _api_key_ctx(
    db_session, *, creator_org_role: str, creator_project_role: str | None, key_role: str
) -> JoySafeterAuthContext:
    """Build the context that _auth_via_api_key produces for a project-scoped key.

    The creator's live org/project standing is written to the DB; the returned
    context mirrors _auth_via_api_key: org role pinned to MEMBER (never a
    super-user) and the key's minted role carried as project_role.
    """
    org_id = OrganizationId.new()
    creator = AuthUser(id=UserId.new(), name="Creator", email=f"{uuid.uuid4()}@example.com")
    org = Organization(id=org_id, name="Org", slug=f"org-{uuid.uuid4()}")
    project = Project(id=ProjectId.new(), org_id=org_id, name="P", slug="default", is_default=True)
    db_session.add_all([creator, org, project])
    await db_session.flush()
    db_session.add(
        Member(id=OrganizationMemberId.new(), user_id=creator.id, organization_id=org_id, role=creator_org_role)
    )
    if creator_project_role is not None:
        db_session.add(
            ProjectMember(
                id=ProjectMemberId.new(), project_id=project.id, user_id=creator.id, role=creator_project_role
            )
        )
    await db_session.commit()
    return JoySafeterAuthContext(
        user_id=creator.id,
        org_id=org_id,
        project_id=project.id,
        role=JoySafeterRole.MEMBER,
        principal_type="api_key",
        project_role=key_role,
    )


@pytest.mark.asyncio
async def test_write_gate_caps_readonly_api_key_minted_by_org_owner(db_session):
    # CB-4 regression: a read-only ("viewer") key minted by an org OWNER
    # (super-user) MUST NOT write. The write gate must cap the key at its minted
    # capability, not re-derive the creator's live super-user capability.
    ctx = await _api_key_ctx(db_session, creator_org_role="owner", creator_project_role=None, key_role="viewer")
    with pytest.raises(AccessDeniedError) as exc_info:
        await _require_write_context(db_session, ctx)
    assert exc_info.value.code == "JOYSAFETER_WRITE_REQUIRED"


@pytest.mark.asyncio
async def test_write_gate_allows_editor_api_key_within_creator(db_session):
    # A key minted with WRITE (editor) by a still-capable creator keeps writing,
    # and the returned context stays an api_key principal (identity preserved).
    ctx = await _api_key_ctx(db_session, creator_org_role="owner", creator_project_role=None, key_role="editor")
    verified = await _require_write_context(db_session, ctx)
    assert verified.principal_type == "api_key"


@pytest.mark.asyncio
async def test_write_gate_caps_api_key_at_demoted_creator_capability(db_session):
    # An editor key whose creator has since been demoted to project viewer must
    # drop to the creator's current (lower) capability: min(key, creator).
    ctx = await _api_key_ctx(db_session, creator_org_role="member", creator_project_role="viewer", key_role="editor")
    with pytest.raises(AccessDeniedError) as exc_info:
        await _require_write_context(db_session, ctx)
    assert exc_info.value.code == "JOYSAFETER_WRITE_REQUIRED"


@pytest.mark.asyncio
async def test_admin_gate_rejects_api_key_principal(db_session):
    # Defense-in-depth (CB-4 same-class): an API key's org role is pinned to
    # MEMBER, so it can never pass the admin gate regardless of its creator's
    # org role — the pre-check fires before any creator re-derivation.
    ctx = await _api_key_ctx(db_session, creator_org_role="owner", creator_project_role=None, key_role="admin")
    with pytest.raises(AccessDeniedError) as exc_info:
        await _require_admin_context(db_session, ctx)
    assert exc_info.value.code == "JOYSAFETER_ADMIN_REQUIRED"


@pytest.mark.asyncio
async def test_write_gate_rejects_api_key_of_removed_creator(db_session):
    # A key whose creator was fully removed from the org must not write: the
    # re-verify raises MEMBERSHIP_EXPIRED before the capability cap is evaluated.
    org_id = OrganizationId.new()
    creator = AuthUser(id=UserId.new(), name="Gone", email=f"{uuid.uuid4()}@example.com")
    org = Organization(id=org_id, name="Org", slug=f"org-{uuid.uuid4()}")
    project = Project(id=ProjectId.new(), org_id=org_id, name="P", slug="default", is_default=True)
    db_session.add_all([creator, org, project])
    await db_session.commit()
    # Creator has NO Member row (removed), yet an editor key still references them.
    ctx = JoySafeterAuthContext(
        user_id=creator.id,
        org_id=org_id,
        project_id=project.id,
        role=JoySafeterRole.MEMBER,
        principal_type="api_key",
        project_role="editor",
    )
    with pytest.raises(Exception) as exc_info:
        await _require_write_context(db_session, ctx)
    assert getattr(exc_info.value, "code", None) == "MEMBERSHIP_EXPIRED"


@pytest.mark.asyncio
async def test_write_gate_denies_api_key_with_unrecognized_role(db_session):
    # A garbage/unknown key role must never resolve to WRITE (normalizes to the
    # least-privilege READ), so the write gate denies it.
    ctx = await _api_key_ctx(db_session, creator_org_role="owner", creator_project_role=None, key_role="wizard")
    with pytest.raises(AccessDeniedError) as exc_info:
        await _require_write_context(db_session, ctx)
    assert exc_info.value.code == "JOYSAFETER_WRITE_REQUIRED"
