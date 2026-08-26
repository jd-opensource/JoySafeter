import json
import uuid

import pytest
from error_contract_helpers import handled_app_error_payload
from sqlalchemy import select, text

from app.joysafeter_api.api.v1.auth import (
    CreateProjectRequest,
    UpdateProjectRequest,
    archive_project,
    create_project,
    restore_project,
    set_default_project,
    update_project,
)
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Member, Organization
from app.joysafeter_domain.models.joysafeter_project import Project, ProjectMember
from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.ids import (
    AgentId,
    OrganizationId,
    OrganizationMemberId,
    ProjectId,
    ProjectMemberId,
    SandboxId,
    SessionId,
    TaskId,
    UserId,
    as_uuid,
)
from app.joysafeter_shared.utils.datetime import utc_now


def _admin_ctx(
    project_id: ProjectId,
    org_id: OrganizationId,
    *,
    user_id: UserId | None = None,
) -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id=user_id or UserId.new(),
        org_id=org_id,
        project_id=project_id,
        role=JoySafeterRole.ADMIN,
    )


def _member_ctx(project_id: ProjectId, org_id: OrganizationId, user_id: UserId) -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id=user_id,
        org_id=org_id,
        project_id=project_id,
        role=JoySafeterRole.MEMBER,
    )


class _FakeCommandRedis:
    def __init__(self, *, receivers: int = 1, owner: str | None = "owner-1"):
        self.receivers = receivers
        self.owner = owner
        self.published: list[tuple[str, dict]] = []
        self.acks: dict[str, str] = {}
        self.blpop_timeouts: list[int] = []

    async def get(self, key: str) -> str | None:
        if key.startswith("joysafeter:sandbox_owner:"):
            return self.owner
        return None

    async def publish(self, channel: str, command: str) -> int:
        payload = json.loads(command)
        self.published.append((channel, payload))
        ack_key = payload.get("ack_key")
        if self.receivers > 0 and ack_key:
            self.acks[ack_key] = json.dumps({"command_id": payload.get("command_id"), "ok": True})
        return self.receivers

    async def blpop(self, key: str, timeout: int = 0):
        self.blpop_timeouts.append(timeout)
        payload = self.acks.pop(key, None)
        if payload is None:
            return None
        return key, payload


class _ExternalIdChangingDestroyAckRedis(_FakeCommandRedis):
    def __init__(self, db_session, sandbox_id: SandboxId, new_external_id: str, *, owner: str | None = "owner-1"):
        super().__init__(owner=owner)
        self.db_session = db_session
        self.sandbox_id = sandbox_id
        self.new_external_id = new_external_id
        self.changed = False

    async def blpop(self, key: str, timeout: int = 0):
        if not self.changed:
            await self.db_session.execute(
                text(
                    "UPDATE joysafeter_sandboxes "
                    "SET external_id = :external_id, updated_at = NOW() "
                    "WHERE id = :sandbox_id"
                ),
                {"external_id": self.new_external_id, "sandbox_id": as_uuid(self.sandbox_id)},
            )
            await self.db_session.commit()
            self.changed = True
        return await super().blpop(key, timeout=timeout)


@pytest.mark.asyncio
async def test_archive_project_rejects_active_tasks(db_session):
    org_id = OrganizationId.new()
    org = Organization(id=org_id, name="Launch Org", slug=f"launch-org-{uuid.uuid4()}")
    project = Project(id=ProjectId.new(), org_id=org_id, name="Launch", slug=f"launch-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.commit()

    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    agent = JoySafeterAgent(id=AgentId.new(), name=f"project-agent-{uuid.uuid4()}", project_id=project.id)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    project_id = project.id

    task = JoySafeterTask(
        id=TaskId.new(),
        agent_id=agent.id,
        project_id=project_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.PENDING.value,
    )
    db_session.add(task)
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await archive_project(project_id, db_session, _admin_ctx(project_id, org_id))

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "PROJECT_ACTIVE_TASKS",
        "message": "Project has active tasks. Stop or wait for them before archiving.",
        "data": {"project_id": str(project_id), "active": 1},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }

    db_session.expire_all()
    project_row = (await db_session.execute(select(Project).where(Project.id == project_id))).scalar_one()
    assert project_row.archived_at is None


@pytest.mark.asyncio
async def test_archive_project_fails_closed_when_task_appears_after_active_check(db_session, monkeypatch):
    org_id = OrganizationId.new()
    org = Organization(id=org_id, name="Race Org", slug=f"race-org-{uuid.uuid4()}")
    project = Project(id=ProjectId.new(), org_id=org_id, name="Race", slug=f"race-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.commit()

    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    agent = JoySafeterAgent(id=AgentId.new(), name=f"project-race-agent-{uuid.uuid4()}", project_id=project.id)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(id=SessionId.new(), agent_id=agent.id, project_id=project.id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    project_id = project.id
    agent_id = agent.id
    session_id = session.id

    async def active_task_appears_after_check(self, project_id):
        task = JoySafeterTask(
            id=TaskId.new(),
            agent_id=agent_id,
            project_id=project_id,
            chat_session_id=session_id,
            prompt="late project task",
            status=JoySafeterTaskStatus.PENDING.value,
        )
        self.db.add(task)
        await self.db.commit()
        return 0

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_task_service.JoySafeterTaskService.count_active_tasks_for_project",
        active_task_appears_after_check,
    )

    with pytest.raises(AppError) as exc_info:
        await archive_project(project_id, db_session, _admin_ctx(project_id, org_id))

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "PROJECT_ACTIVE_TASKS",
        "message": "Project has active tasks. Stop or wait for them before archiving.",
        "data": {"project_id": str(project_id), "active": 1},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }

    db_session.expire_all()
    project_row = (await db_session.execute(select(Project).where(Project.id == project_id))).scalar_one()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
    task_rows = (
        (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.chat_session_id == session_id)))
        .scalars()
        .all()
    )
    assert project_row.archived_at is None
    assert session_row.archived_at is None
    assert session_row.status == "idle"
    assert len(task_rows) == 1


@pytest.mark.asyncio
async def test_set_default_project_rejects_archived_project(db_session):
    org_id = OrganizationId.new()
    org = Organization(id=org_id, name="Default Org", slug=f"default-org-{uuid.uuid4()}")
    active_project = Project(
        id=ProjectId.new(),
        org_id=org_id,
        name="Active",
        slug=f"active-{uuid.uuid4()}",
        is_default=True,
    )
    archived_project = Project(
        id=ProjectId.new(),
        org_id=org_id,
        name="Archived",
        slug=f"archived-{uuid.uuid4()}",
        archived_at=utc_now(),
    )
    db_session.add_all([org, active_project, archived_project])
    await db_session.commit()
    active_project_id = active_project.id
    archived_project_id = archived_project.id

    with pytest.raises(AppError) as exc_info:
        await set_default_project(archived_project_id, db_session, _admin_ctx(active_project_id, org_id))

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "PROJECT_ARCHIVED",
        "message": "Cannot set an archived project as default",
        "data": {"project_id": str(archived_project_id), "organization_id": str(org_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }

    db_session.expire_all()
    active_row = (await db_session.execute(select(Project).where(Project.id == active_project_id))).scalar_one()
    archived_row = (await db_session.execute(select(Project).where(Project.id == archived_project_id))).scalar_one()
    assert active_row.is_default is True
    assert archived_row.is_default is False


@pytest.mark.asyncio
async def test_update_project_rejects_archived_project_without_mutating(db_session):
    org_id = OrganizationId.new()
    org = Organization(id=org_id, name="Archived Project Org", slug=f"archived-project-org-{uuid.uuid4()}")
    archived_project = Project(
        id=ProjectId.new(),
        org_id=org_id,
        name="Archived",
        slug=f"archived-{uuid.uuid4()}",
        archived_at=utc_now(),
    )
    db_session.add_all([org, archived_project])
    await db_session.commit()
    project_id = archived_project.id
    original_slug = archived_project.slug

    with pytest.raises(AppError) as exc_info:
        await update_project(
            project_id,
            UpdateProjectRequest(name="Renamed", slug="renamed"),
            db_session,
            _admin_ctx(project_id, org_id),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "PROJECT_ARCHIVED",
        "message": "Cannot update an archived project",
        "data": {"project_id": str(project_id), "organization_id": str(org_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }

    db_session.expire_all()
    project_row = (await db_session.execute(select(Project).where(Project.id == project_id))).scalar_one()
    assert project_row.name == "Archived"
    assert project_row.slug == original_slug


@pytest.mark.asyncio
async def test_create_project_rejects_blank_name_with_structured_error(db_session):
    org_id = OrganizationId.new()
    org = Organization(id=org_id, name="Project Validation Org", slug=f"project-validation-{uuid.uuid4()}")
    current_project = Project(
        id=ProjectId.new(),
        org_id=org_id,
        name="Current",
        slug=f"current-{uuid.uuid4()}",
        is_default=True,
    )
    db_session.add_all([org, current_project])
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await create_project(
            CreateProjectRequest(name="   ", slug="valid-project"),
            db_session,
            _admin_ctx(current_project.id, org_id),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "PROJECT_NAME_REQUIRED",
        "message": "Project name is required",
        "data": {"field": "name"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_create_project_rejects_duplicate_slug_without_db_integrity_leak(db_session):
    org_id = OrganizationId.new()
    org = Organization(id=org_id, name="Project Slug Org", slug=f"project-slug-{uuid.uuid4()}")
    current_project = Project(
        id=ProjectId.new(),
        org_id=org_id,
        name="Current",
        slug="current-project",
        is_default=True,
    )
    existing_project = Project(
        id=ProjectId.new(),
        org_id=org_id,
        name="Existing",
        slug="shared-slug",
    )
    db_session.add_all([org, current_project, existing_project])
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await create_project(
            CreateProjectRequest(name="Duplicate", slug="shared-slug"),
            db_session,
            _admin_ctx(current_project.id, org_id),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "PROJECT_SLUG_CONFLICT",
        "message": "Project slug already exists in this organization",
        "data": {"organization_id": str(org_id), "slug": "shared-slug"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }

    rows = (
        (await db_session.execute(select(Project).where(Project.org_id == org_id, Project.slug == "shared-slug")))
        .scalars()
        .all()
    )
    assert [row.id for row in rows] == [existing_project.id]


@pytest.mark.asyncio
async def test_update_project_rejects_duplicate_slug_without_mutating(db_session):
    org_id = OrganizationId.new()
    org = Organization(id=org_id, name="Project Update Slug Org", slug=f"project-update-slug-{uuid.uuid4()}")
    current_project = Project(
        id=ProjectId.new(),
        org_id=org_id,
        name="Current",
        slug="current-update-project",
        is_default=True,
    )
    target_project = Project(
        id=ProjectId.new(),
        org_id=org_id,
        name="Target",
        slug="target-project",
    )
    db_session.add_all([org, current_project, target_project])
    await db_session.commit()
    target_project_id = target_project.id

    with pytest.raises(AppError) as exc_info:
        await update_project(
            target_project_id,
            UpdateProjectRequest(slug="current-update-project"),
            db_session,
            _admin_ctx(current_project.id, org_id),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "PROJECT_SLUG_CONFLICT",
        "message": "Project slug already exists in this organization",
        "data": {"organization_id": str(org_id), "slug": "current-update-project"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }

    db_session.expire_all()
    project_row = (await db_session.execute(select(Project).where(Project.id == target_project_id))).scalar_one()
    assert project_row.name == "Target"
    assert project_row.slug == "target-project"


@pytest.mark.asyncio
async def test_project_create_and_update_normalize_slug_at_service_boundary(db_session):
    org_id = OrganizationId.new()
    user = AuthUser(id=UserId.new(), name="Admin User", email=f"admin-{uuid.uuid4()}@example.com")
    org = Organization(id=org_id, name="Project Normalize Org", slug=f"project-normalize-{uuid.uuid4()}")
    current_project = Project(
        id=ProjectId.new(),
        org_id=org_id,
        name="Current",
        slug="current-normalize-project",
        is_default=True,
    )
    db_session.add_all([user, org, current_project])
    await db_session.commit()

    created = await create_project(
        CreateProjectRequest(name="  Normalized  ", slug=" Normalized_Project! "),
        db_session,
        _admin_ctx(current_project.id, org_id, user_id=user.id),
    )

    assert created.name == "Normalized"
    assert created.slug == "normalized-project"
    project_member = (
        await db_session.execute(
            select(ProjectMember).where(ProjectMember.project_id == created.id, ProjectMember.user_id == user.id)
        )
    ).scalar_one_or_none()
    assert project_member is None
    assert created.created_by_user_id == user.id

    updated = await update_project(
        created.id,
        UpdateProjectRequest(name=" Renamed ", slug=" Renamed Project ", triggers_paused=True),
        db_session,
        _admin_ctx(current_project.id, org_id, user_id=user.id),
    )

    assert updated.name == "Renamed"
    assert updated.slug == "renamed-project"
    assert updated.triggers_paused is True

    db_session.expire_all()
    project_row = (await db_session.execute(select(Project).where(Project.id == created.id))).scalar_one()
    assert project_row.triggers_paused is True


@pytest.mark.asyncio
async def test_member_cannot_create_project_when_policy_is_admins_only(db_session):
    org_id = OrganizationId.new()
    user = AuthUser(id=UserId.new(), name="Member", email=f"member-{uuid.uuid4()}@example.com")
    org = Organization(
        id=org_id,
        name="Restricted Org",
        slug=f"restricted-{uuid.uuid4()}",
        project_creation_policy="admins_only",
    )
    current_project = Project(id=ProjectId.new(), org_id=org_id, name="Default", slug="default", is_default=True)
    db_session.add_all([user, org, current_project])
    await db_session.flush()
    db_session.add(Member(id=OrganizationMemberId.new(), user_id=user.id, organization_id=org_id, role="member"))
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await create_project(
            CreateProjectRequest(name="Blocked", slug="blocked"),
            db_session,
            _member_ctx(current_project.id, org_id, user.id),
        )

    assert exc_info.value.code == "PROJECT_CREATE_FORBIDDEN"


@pytest.mark.asyncio
async def test_member_creator_becomes_project_admin_when_policy_allows_creation(db_session):
    org_id = OrganizationId.new()
    user = AuthUser(id=UserId.new(), name="Member", email=f"member-{uuid.uuid4()}@example.com")
    org = Organization(
        id=org_id,
        name="Open Org",
        slug=f"open-{uuid.uuid4()}",
        project_creation_policy="all_members",
    )
    current_project = Project(id=ProjectId.new(), org_id=org_id, name="Default", slug="default", is_default=True)
    db_session.add_all([user, org, current_project])
    await db_session.flush()
    db_session.add(Member(id=OrganizationMemberId.new(), user_id=user.id, organization_id=org_id, role="member"))
    await db_session.commit()

    created = await create_project(
        CreateProjectRequest(name="Member Project", slug="member-project"),
        db_session,
        _member_ctx(current_project.id, org_id, user.id),
    )

    assert created.created_by_user_id == user.id
    assert created.project_role == "admin"
    assert created.capability == "admin"


@pytest.mark.asyncio
async def test_project_admin_can_rename_and_pause_but_cannot_change_slug(db_session):
    org_id = OrganizationId.new()
    user = AuthUser(id=UserId.new(), name="Project Admin", email=f"project-admin-{uuid.uuid4()}@example.com")
    org = Organization(id=org_id, name="Org", slug=f"org-{uuid.uuid4()}")
    project = Project(id=ProjectId.new(), org_id=org_id, name="Project", slug="project")
    db_session.add_all([user, org, project])
    await db_session.flush()
    db_session.add_all(
        [
            Member(id=OrganizationMemberId.new(), user_id=user.id, organization_id=org_id, role="member"),
            ProjectMember(id=ProjectMemberId.new(), project_id=project.id, user_id=user.id, role="admin"),
        ]
    )
    await db_session.commit()
    ctx = _member_ctx(project.id, org_id, user.id)

    renamed = await update_project(
        project.id,
        UpdateProjectRequest(name="Renamed", triggers_paused=True),
        db_session,
        ctx,
    )
    assert renamed.name == "Renamed"
    assert renamed.triggers_paused is True

    with pytest.raises(AppError) as exc_info:
        await update_project(
            project.id,
            UpdateProjectRequest(slug="renamed-slug"),
            db_session,
            ctx,
        )
    assert exc_info.value.code == "JOYSAFETER_ORGANIZATION_ADMIN_REQUIRED"


@pytest.mark.asyncio
async def test_restore_project_unarchives_archived_project_for_admin_context(db_session):
    org_id = OrganizationId.new()
    org = Organization(id=org_id, name="Restore Project Org", slug=f"restore-project-org-{uuid.uuid4()}")
    archived_project = Project(
        id=ProjectId.new(),
        org_id=org_id,
        name="Archived",
        slug=f"archived-{uuid.uuid4()}",
        archived_at=utc_now(),
    )
    db_session.add_all([org, archived_project])
    await db_session.commit()
    project_id = archived_project.id

    response = await restore_project(project_id, db_session, _admin_ctx(project_id, org_id))

    assert response.id == project_id
    assert response.archived_at is None
    db_session.expire_all()
    project_row = (await db_session.execute(select(Project).where(Project.id == project_id))).scalar_one()
    assert project_row.archived_at is None


@pytest.mark.asyncio
async def test_archive_project_destroys_session_sandbox_via_rust_owner(db_session, monkeypatch):
    org_id = OrganizationId.new()
    org = Organization(id=org_id, name="Project Archive Org", slug=f"archive-org-{uuid.uuid4()}")
    project = Project(id=ProjectId.new(), org_id=org_id, name="Archive", slug=f"archive-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.commit()

    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    project_id = project.id

    agent = JoySafeterAgent(id=AgentId.new(), name=f"project-archive-agent-{uuid.uuid4()}", project_id=project_id)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(id=SessionId.new(), agent_id=agent.id, project_id=project_id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    sandbox = JoySafeterSandbox(
        id=SandboxId.new(),
        project_id=project_id,
        chat_session_id=session_id,
        external_id=f"sandbox-{uuid.uuid4()}",
        image="test-image",
        status="idle",
    )
    db_session.add(sandbox)
    await db_session.commit()
    await db_session.refresh(sandbox)
    sandbox_id = sandbox.id

    redis = _FakeCommandRedis(owner=None)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    response = await archive_project(project_id, db_session, _admin_ctx(project_id, org_id))

    assert response.status == "archived"
    assert len(redis.published) == 1
    assert redis.published[0][0] == "joysafeter:cmd:destroy"
    assert redis.published[0][1]["type"] == "destroy"
    assert redis.published[0][1]["external_id"] == sandbox.external_id
    assert redis.blpop_timeouts == [30]

    db_session.expire_all()
    project_row = (await db_session.execute(select(Project).where(Project.id == project_id))).scalar_one()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
    sandbox_row = (
        await db_session.execute(select(JoySafeterSandbox).where(JoySafeterSandbox.id == sandbox_id))
    ).scalar_one()
    assert project_row.archived_at is not None
    assert session_row.archived_at is not None
    assert session_row.status == "terminated"
    assert sandbox_row.status == "destroyed"
    assert sandbox_row.destroyed_at is not None


@pytest.mark.asyncio
async def test_archive_project_rejects_destroy_ack_if_sandbox_external_id_changed(db_session, monkeypatch):
    org_id = OrganizationId.new()
    org = Organization(id=org_id, name="Project Stale Destroy Org", slug=f"stale-destroy-org-{uuid.uuid4()}")
    project = Project(id=ProjectId.new(), org_id=org_id, name="Stale Destroy", slug=f"stale-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.commit()

    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    project_id = project.id

    agent = JoySafeterAgent(id=AgentId.new(), name=f"project-stale-destroy-agent-{uuid.uuid4()}", project_id=project_id)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(id=SessionId.new(), agent_id=agent.id, project_id=project_id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    old_external_id = f"sandbox-old-{uuid.uuid4()}"
    new_external_id = f"sandbox-new-{uuid.uuid4()}"
    sandbox = JoySafeterSandbox(
        id=SandboxId.new(),
        project_id=project_id,
        chat_session_id=session_id,
        external_id=old_external_id,
        image="test-image",
        status="idle",
    )
    db_session.add(sandbox)
    await db_session.commit()
    await db_session.refresh(sandbox)
    sandbox_id = sandbox.id

    redis = _ExternalIdChangingDestroyAckRedis(db_session, sandbox_id, new_external_id, owner=None)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    with pytest.raises(AppError) as exc_info:
        await archive_project(project_id, db_session, _admin_ctx(project_id, org_id))

    assert await handled_app_error_payload(exc_info.value, status_code=503) == {
        "code": "PROJECT_SANDBOX_STATE_SYNC_FAILED",
        "message": "Project could not be archived because sandbox state sync failed.",
        "data": {"project_id": str(project_id), "session_id": str(session_id), "sandbox_id": str(sandbox_id)},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }
    assert redis.published[0][1]["external_id"] == old_external_id

    db_session.expire_all()
    project_row = (await db_session.execute(select(Project).where(Project.id == project_id))).scalar_one()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
    sandbox_row = (
        await db_session.execute(select(JoySafeterSandbox).where(JoySafeterSandbox.id == sandbox_id))
    ).scalar_one()
    assert project_row.archived_at is None
    assert session_row.archived_at is None
    assert session_row.status == "idle"
    assert sandbox_row.status == "idle"
    assert sandbox_row.external_id == new_external_id
    assert sandbox_row.destroyed_at is None


@pytest.mark.asyncio
async def test_archive_project_requires_session_sandbox_destroy_ack_without_provider(db_session, monkeypatch):
    org_id = OrganizationId.new()
    org = Organization(id=org_id, name="Project Shutdown Org", slug=f"shutdown-org-{uuid.uuid4()}")
    project = Project(id=ProjectId.new(), org_id=org_id, name="Shutdown", slug=f"shutdown-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.commit()

    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    project_id = project.id

    agent = JoySafeterAgent(id=AgentId.new(), name=f"project-shutdown-agent-{uuid.uuid4()}", project_id=project_id)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(id=SessionId.new(), agent_id=agent.id, project_id=project_id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    sandbox = JoySafeterSandbox(
        id=SandboxId.new(),
        project_id=project_id,
        chat_session_id=session_id,
        external_id=f"sandbox-{uuid.uuid4()}",
        image="test-image",
        status="idle",
    )
    db_session.add(sandbox)
    await db_session.commit()
    await db_session.refresh(sandbox)
    sandbox_id = sandbox.id

    redis = _FakeCommandRedis(receivers=0)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    with pytest.raises(AppError) as exc_info:
        await archive_project(project_id, db_session, _admin_ctx(project_id, org_id))

    assert await handled_app_error_payload(exc_info.value, status_code=503) == {
        "code": "PROJECT_ARCHIVE_REDIS_DESTROY_FAILED",
        "message": "Failed to destroy project session sandbox runtime.",
        "data": {"project_id": str(project_id), "session_id": str(session_id), "sandbox_id": str(sandbox_id)},
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
    }
    assert len(redis.published) == 1
    assert redis.published[0][1]["type"] == "destroy"

    db_session.expire_all()
    project_row = (await db_session.execute(select(Project).where(Project.id == project_id))).scalar_one()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
    sandbox_row = (
        await db_session.execute(select(JoySafeterSandbox).where(JoySafeterSandbox.id == sandbox_id))
    ).scalar_one()
    assert project_row.archived_at is None
    assert session_row.archived_at is None
    assert session_row.status == "idle"
    assert sandbox_row.status == "idle"
    assert sandbox_row.destroyed_at is None
