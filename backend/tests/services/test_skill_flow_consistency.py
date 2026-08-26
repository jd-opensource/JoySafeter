from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.joysafeter_application.agents import compose_agent_application
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent, JoySafeterAgentVersion
from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Member, Organization
from app.joysafeter_domain.models.joysafeter_project import Project, ProjectMember
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_skill import JoySafeterSkill, JoySafeterSkillVersion
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask
from app.joysafeter_domain.services.joysafeter_skill_service import SkillService, SkillVersionService
from app.joysafeter_shared.common.app_errors import (
    AccessDeniedError,
    InvalidRequestError,
    NotFoundError,
    ResourceConflictError,
)
from app.joysafeter_shared.ids import (
    AgentId,
    AgentVersionId,
    OrganizationId,
    OrganizationMemberId,
    ProjectId,
    ProjectMemberId,
    SessionId,
    SkillId,
    SkillVersionId,
    TaskId,
    UserId,
)

pytestmark = pytest.mark.asyncio


async def _seed_org_project(db, *, suffix: str) -> tuple[Organization, Project]:
    org = Organization(
        id=OrganizationId.new(),
        name=f"Org {suffix}",
        slug=f"org-{suffix}-{uuid.uuid4()}",
    )
    db.add(org)
    await db.flush()
    project = Project(
        id=ProjectId.new(),
        org_id=org.id,
        name=f"Project {suffix}",
        slug=f"project-{suffix}-{uuid.uuid4()}",
    )
    db.add(project)
    await db.flush()
    return org, project


async def _seed_user(db) -> AuthUser:
    user = AuthUser(id=UserId.new(), name="Skill owner", email=f"{uuid.uuid4()}@example.com")
    db.add(user)
    await db.flush()
    return user


async def _seed_skill_with_versions(db, *, project: Project, owner: AuthUser):
    skill = JoySafeterSkill(
        id=SkillId.new(),
        name=f"skill-{uuid.uuid4()}",
        description="Skill",
        content="# Skill",
        tags=[],
        owner_id=owner.id,
        created_by_id=owner.id,
        project_id=project.id,
        visibility="public",
        lifecycle_status="approved",
    )
    db.add(skill)
    await db.flush()

    versions = {}
    for version in ("0.9.0", "1.0.0", "2.0.0"):
        row = JoySafeterSkillVersion(
            id=SkillVersionId.new(),
            skill_id=skill.id,
            version=version,
            skill_name=skill.name,
            skill_description=skill.description,
            content=f"# Version {version}",
            tags=[],
            meta_data={},
            allowed_tools=[],
            published_by_id=owner.id,
            published_at=datetime.now(timezone.utc),
            lifecycle_status="approved",
        )
        db.add(row)
        await db.flush()
        versions[version] = row

    skill.public_version_id = versions["0.9.0"].id
    skill.org_version_id = versions["1.0.0"].id
    skill.content = "# Private draft 2.0"
    await db.commit()
    return skill, versions


async def test_agent_skill_ref_same_org_latest_resolves_only_promoted_versions(db_session):
    source_org, source_project = await _seed_org_project(db_session, suffix="source")
    consumer_project = Project(
        id=ProjectId.new(),
        org_id=source_org.id,
        name="Consumer",
        slug=f"consumer-{uuid.uuid4()}",
    )
    db_session.add(consumer_project)
    owner = await _seed_user(db_session)
    skill, _versions = await _seed_skill_with_versions(db_session, project=source_project, owner=owner)
    await db_session.flush()

    normalized = await compose_agent_application(db_session).commands._validate_skill_refs(
        [{"skill_id": str(skill.id), "version": "latest"}],
        consumer_project.id,
    )

    assert normalized == [{"skill_id": str(skill.id), "version": "1.0.0"}]


async def test_agent_skill_ref_cross_org_latest_resolves_public_pointer(db_session):
    _source_org, source_project = await _seed_org_project(db_session, suffix="source")
    _consumer_org, consumer_project = await _seed_org_project(db_session, suffix="consumer")
    owner = await _seed_user(db_session)
    skill, _versions = await _seed_skill_with_versions(db_session, project=source_project, owner=owner)

    normalized = await compose_agent_application(db_session).commands._validate_skill_refs(
        [{"skill_id": str(skill.id), "version": "latest"}],
        consumer_project.id,
    )

    assert normalized == [{"skill_id": str(skill.id), "version": "0.9.0"}]


async def test_agent_skill_ref_cross_project_rejects_unpromoted_explicit_version(db_session):
    source_org, source_project = await _seed_org_project(db_session, suffix="source")
    consumer_project = Project(
        id=ProjectId.new(),
        org_id=source_org.id,
        name="Consumer",
        slug=f"consumer-{uuid.uuid4()}",
    )
    db_session.add(consumer_project)
    owner = await _seed_user(db_session)
    skill, _versions = await _seed_skill_with_versions(db_session, project=source_project, owner=owner)
    await db_session.flush()

    with pytest.raises(InvalidRequestError) as exc:
        await compose_agent_application(db_session).commands._validate_skill_refs(
            [{"skill_id": str(skill.id), "version": "2.0.0"}],
            consumer_project.id,
        )

    assert exc.value.code == "AGENT_SKILL_REF_NOT_PUBLISHED"
    assert exc.value.data["skills"] == [
        {"skill_id": str(skill.id), "version": "2.0.0", "reason": "version_not_exposed"}
    ]


async def test_cross_project_skill_list_and_detail_hide_unpromoted_latest(db_session):
    source_org, source_project = await _seed_org_project(db_session, suffix="source")
    consumer_project = Project(
        id=ProjectId.new(),
        org_id=source_org.id,
        name="Consumer",
        slug=f"consumer-{uuid.uuid4()}",
    )
    db_session.add(consumer_project)
    caller = await _seed_user(db_session)
    owner = await _seed_user(db_session)
    db_session.add(
        Member(
            id=OrganizationMemberId.new(),
            organization_id=source_org.id,
            user_id=caller.id,
            role="member",
        )
    )
    db_session.add(
        ProjectMember(
            id=ProjectMemberId.new(),
            project_id=consumer_project.id,
            user_id=caller.id,
            role="viewer",
        )
    )
    skill, _versions = await _seed_skill_with_versions(db_session, project=source_project, owner=owner)
    await db_session.commit()

    svc = SkillService(db_session, active_org_id=source_org.id)
    skills, _has_more = await svc.list_skills(
        current_user_id=caller.id,
        project_id=consumer_project.id,
        limit=20,
    )
    listed = next(item for item in skills if item.id == skill.id)
    assert listed.latest_version == "1.0.0"
    assert listed.content == "# Version 1.0.0"

    detail = await svc.get_skill(
        skill.id,
        current_user_id=caller.id,
        project_id=consumer_project.id,
    )
    assert detail.latest_version == "1.0.0"
    assert detail.content == "# Version 1.0.0"
    assert detail.files == []
    assert detail.impact is None

    version_svc = SkillVersionService(db_session, active_org_id=source_org.id)
    visible_versions, _has_more = await version_svc.list_versions(
        skill.id,
        current_user_id=caller.id,
        project_id=consumer_project.id,
        limit=20,
    )
    assert {version.version for version in visible_versions} == {"0.9.0", "1.0.0"}

    with pytest.raises(NotFoundError) as exc:
        await version_svc.get_version(
            skill.id,
            "2.0.0",
            current_user_id=caller.id,
            project_id=consumer_project.id,
        )
    assert exc.value.code == "SKILL_VERSION_NOT_FOUND"

    with pytest.raises(AccessDeniedError) as exc:
        await svc.list_security_scans(
            skill.id,
            current_user_id=caller.id,
            project_id=consumer_project.id,
        )
    assert exc.value.code == "SKILL_SECURITY_SCAN_ACCESS_DENIED"


async def test_delete_promoted_version_requires_force_and_reports_runtime_breakage(db_session, monkeypatch):
    org, project = await _seed_org_project(db_session, suffix="delete-version")
    owner = await _seed_user(db_session)
    skill, versions = await _seed_skill_with_versions(db_session, project=project, owner=owner)
    skill.public_version_id = None
    await db_session.commit()

    async def _allow_access(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_skill_service.check_skill_access",
        _allow_access,
    )
    svc = SkillVersionService(db_session, active_org_id=org.id)
    with pytest.raises(ResourceConflictError) as exc:
        await svc.delete_version(skill.id, "1.0.0", current_user_id=owner.id)

    assert exc.value.code == "SKILL_VERSION_IN_USE"
    assert {item["kind"] for item in exc.value.data["referrers"]} == {"promotion"}
    assert "fail to load" in exc.value.data["hint"]
    assert versions["1.0.0"].id == skill.org_version_id


async def test_skill_reference_gate_includes_frozen_agent_version(db_session):
    org, project = await _seed_org_project(db_session, suffix="refs")
    skill_id = SkillId.new()
    agent = JoySafeterAgent(id=AgentId.new(), name="Agent", engine_kind="claude", project_id=project.id, skills=[])
    db_session.add(agent)
    await db_session.flush()
    db_session.add(
        JoySafeterAgentVersion(
            id=AgentVersionId.new(),
            agent_id=agent.id,
            version=1,
            snapshot={"skills": [{"skill_id": str(skill_id), "version": "1.0.0"}]},
        )
    )
    await db_session.commit()

    svc = SkillService(db_session, active_org_id=org.id)
    skill = SimpleNamespace(id=skill_id, project_id=project.id)

    assert await svc._has_skill_references(skill) is True
    await svc._annotate_skill_impact(skill)
    assert skill.impact["counts"]["agent_versions"] == 1
    assert skill.impact["counts"]["total"] == 1


async def test_skill_reference_gate_includes_active_session_snapshot(db_session):
    org, project = await _seed_org_project(db_session, suffix="task")
    skill_id = SkillId.new()
    agent = JoySafeterAgent(id=AgentId.new(), name="Agent", engine_kind="claude", project_id=project.id, skills=[])
    db_session.add(agent)
    await db_session.flush()
    session = JoySafeterSession(
        id=SessionId.new(),
        agent_id=agent.id,
        project_id=project.id,
        agent_snapshot={"skills": [{"skill_id": str(skill_id), "version": "1.0.0"}]},
    )
    db_session.add(session)
    await db_session.flush()
    db_session.add(
        JoySafeterTask(
            id=TaskId.new(),
            agent_id=agent.id,
            chat_session_id=session.id,
            project_id=project.id,
            status="running",
            prompt="run",
        )
    )
    await db_session.commit()

    svc = SkillService(db_session, active_org_id=org.id)
    skill = SimpleNamespace(id=skill_id, project_id=project.id)

    assert await svc._has_skill_references(skill) is True
    await svc._annotate_skill_impact(skill)
    assert skill.impact["counts"]["active_tasks"] == 1
    assert skill.impact["counts"]["total"] == 1
