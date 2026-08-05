import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Member, Organization
from app.joysafeter_domain.services.joysafeter_organization_member_service import (
    OrganizationMemberService,
)
from app.joysafeter_shared.common.app_errors import ResourceConflictError


@pytest.mark.asyncio
async def test_duplicate_org_membership_is_rejected_by_db(db_session):
    # CB-1 regression: the DB must forbid two Member rows for the same
    # (organization_id, user_id). Without the unique constraint a race in
    # add_member could create duplicates, making the per-request org role
    # (resolved via .limit(1) with no ordering) nondeterministic.
    org = Organization(id=f"org-{uuid.uuid4()}", name="Org", slug=f"org-{uuid.uuid4()}")
    user = AuthUser(id=f"user-{uuid.uuid4()}", name="U", email=f"{uuid.uuid4()}@example.com")
    db_session.add_all([org, user])
    await db_session.flush()

    db_session.add(Member(user_id=user.id, organization_id=org.id, role="admin"))
    db_session.add(Member(user_id=user.id, organization_id=org.id, role="member"))

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_add_member_race_converts_integrity_error_to_conflict(db_session, monkeypatch):
    # Simulate the TOCTOU race: the up-front existence check misses a row that a
    # concurrent request already committed, so the insert reaches the DB and trips
    # the unique constraint. The service must surface a clean 409 conflict, not a
    # raw IntegrityError (500).
    org = Organization(id=f"org-{uuid.uuid4()}", name="Org", slug=f"org-{uuid.uuid4()}")
    actor = AuthUser(id=f"user-{uuid.uuid4()}", name="Actor", email=f"{uuid.uuid4()}@example.com")
    target = AuthUser(id=f"user-{uuid.uuid4()}", name="Target", email=f"{uuid.uuid4()}@example.com")
    db_session.add_all([org, actor, target])
    await db_session.flush()
    db_session.add(Member(user_id=actor.id, organization_id=org.id, role="owner"))
    # The row a concurrent request "just committed" for the target.
    db_session.add(Member(user_id=target.id, organization_id=org.id, role="member"))
    await db_session.commit()

    svc = OrganizationMemberService(db_session)
    real_lookup = svc.get_member_by_user_id

    async def _lookup_missing_target(organization_id: str, user_id: str):
        if user_id == target.id:
            return None  # the racing check does not see the existing row
        return await real_lookup(organization_id, user_id)

    monkeypatch.setattr(svc, "get_member_by_user_id", _lookup_missing_target)

    with pytest.raises(ResourceConflictError) as exc_info:
        await svc.add_member(
            organization_id=org.id,
            user_id=target.id,
            actor_user_id=actor.id,
            role="member",
        )
    assert exc_info.value.code == "ORGANIZATION_MEMBER_ALREADY_EXISTS"
