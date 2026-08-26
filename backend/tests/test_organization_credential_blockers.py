"""Service-level tests for the 9e consumer sweep: OrganizationService's
project/org deletion blockers now count unified credentials + credential groups
(the old ``secrets`` / ``vaults`` blockers were removed with those tables).
"""

import uuid

import pytest
import pytest_asyncio

from app.joysafeter_application.credentials.application_service import CredentialService
from app.joysafeter_application.credentials.ports import CredentialAuditActor
from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_credential import (
    JoySafeterCredential,
    JoySafeterCredentialGroup,
)
from app.joysafeter_domain.models.joysafeter_organization import Member, Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.schemas.joysafeter_credential import CreateCredentialRequest
from app.joysafeter_domain.services.joysafeter_organization_service import (
    PROJECT_RESOURCE_BLOCKERS,
    OrganizationService,
)
from app.joysafeter_shared.common.app_errors import ResourceConflictError
from app.joysafeter_shared.ids import (
    CredentialGroupId,
    CredentialId,
    OrganizationId,
    OrganizationMemberId,
    ProjectId,
    UserId,
)
from app.joysafeter_shared.utils.datetime import utc_now


def test_blocker_list_replaces_secrets_and_vaults_with_credentials():
    labels = [label for label, _ in PROJECT_RESOURCE_BLOCKERS]
    assert "credentials" in labels
    assert "credential_groups" in labels
    assert "secrets" not in labels
    assert "vaults" not in labels


async def _make_org_and_project(db_session) -> tuple[OrganizationId, ProjectId, UserId]:
    user = AuthUser(id=UserId.new(), name="Owner", email=f"owner-{uuid.uuid4()}@example.com")
    db_session.add(user)
    await db_session.flush()
    org = Organization(id=OrganizationId.new(), name=f"org-{uuid.uuid4()}", slug=f"org-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.flush()
    db_session.add(Member(id=OrganizationMemberId.new(), user_id=user.id, organization_id=org.id, role="owner"))
    project = Project(
        id=ProjectId.new(),
        org_id=org.id,
        name=f"proj-{uuid.uuid4()}",
        slug=f"proj-{uuid.uuid4()}",
    )
    db_session.add(project)
    await db_session.commit()
    return org.id, project.id, user.id


@pytest_asyncio.fixture
async def org_project(db_session) -> tuple[OrganizationId, ProjectId, UserId]:
    return await _make_org_and_project(db_session)


@pytest.mark.asyncio
async def test_delete_org_blocked_by_live_credential(db_session, org_project):
    org_id, project_id, user_id = org_project
    await CredentialService(db_session, audit_actor=CredentialAuditActor.system("test")).create(
        CreateCredentialRequest(kind="service", name=f"s-{uuid.uuid4()}", data={"TOKEN": "t"}),
        project_id=project_id,
    )

    with pytest.raises(ResourceConflictError) as exc:
        await OrganizationService(db_session).delete_organization(organization_id=org_id, actor_user_id=user_id)

    assert exc.value.code == "ORGANIZATION_PROJECT_RESOURCES_EXIST"
    assert "credentials" in exc.value.data["resources"]


@pytest.mark.asyncio
async def test_delete_org_blocked_by_credential_group(db_session, org_project):
    org_id, project_id, user_id = org_project
    group = JoySafeterCredentialGroup(id=CredentialGroupId.new(), project_id=project_id, name=f"g-{uuid.uuid4()}")
    db_session.add(group)
    await db_session.commit()

    with pytest.raises(ResourceConflictError) as exc:
        await OrganizationService(db_session).delete_organization(organization_id=org_id, actor_user_id=user_id)

    assert exc.value.code == "ORGANIZATION_PROJECT_RESOURCES_EXIST"
    assert "credential_groups" in exc.value.data["resources"]


@pytest.mark.asyncio
async def test_soft_deleted_credential_remains_physical_deletion_blocker(db_session, org_project):
    _org_id, project_id, _user_id = org_project
    cred = JoySafeterCredential(
        id=CredentialId.new(),
        project_id=project_id,
        kind="service",
        name=f"s-{uuid.uuid4()}",
        data={},
        deleted_at=utc_now(),
        material_erased_at=utc_now(),
    )
    db_session.add(cred)
    await db_session.commit()

    blockers = await OrganizationService(db_session)._project_resource_blockers([project_id])
    assert "credentials" in blockers


@pytest.mark.asyncio
async def test_soft_deleted_credential_group_remains_physical_deletion_blocker(db_session, org_project):
    _org_id, project_id, _user_id = org_project
    group = JoySafeterCredentialGroup(
        id=CredentialGroupId.new(),
        project_id=project_id,
        name=f"g-{uuid.uuid4()}",
        deleted_at=utc_now(),
    )
    db_session.add(group)
    await db_session.commit()

    blockers = await OrganizationService(db_session)._project_resource_blockers([project_id])

    assert "credential_groups" in blockers
