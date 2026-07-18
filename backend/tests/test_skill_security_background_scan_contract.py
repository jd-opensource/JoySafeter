import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_skill import JoySafeterSkill, JoySafeterSkillSecurityScan
from app.joysafeter_domain.services.joysafeter_skill_security import SkillSecurityService, run_scan_in_background


@pytest.mark.asyncio
async def test_background_skill_scan_failure_records_structured_failed_scan(
    postgres_url,
    db_session,
    monkeypatch,
):
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)

    async def fail_before_scanner_record(self, **kwargs):
        raise RuntimeError("background task crashed")

    monkeypatch.setattr(SkillSecurityService, "scan_for_write", fail_before_scanner_record)

    user = AuthUser(name="Skill Scanner", email=f"skill-scanner-{uuid.uuid4()}@example.com")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    user_id = user.id

    org_id = f"org-{uuid.uuid4()}"
    project_id = f"proj-{uuid.uuid4()}"
    org = Organization(id=org_id, name="Skill Scan Org", slug=f"skill-scan-{uuid.uuid4()}")
    project = Project(id=project_id, org_id=org_id, name="Skill Scan", slug=f"skill-scan-{uuid.uuid4()}")
    db_session.add_all([org, project])
    await db_session.commit()

    skill = JoySafeterSkill(
        name=f"async-scan-skill-{uuid.uuid4()}",
        description="test skill",
        content="# Skill",
        tags=[],
        created_by_id=user_id,
        owner_id=user_id,
        project_id=project_id,
        security_status="scanning",
    )
    db_session.add(skill)
    await db_session.commit()
    await db_session.refresh(skill)
    skill_id = skill.id

    try:
        await run_scan_in_background(
            skill_id=skill_id,
            trigger="create",
            created_by_id=user_id,
            owner_id=user_id,
            project_id=None,
            name=skill.name,
            description=skill.description,
            content=skill.content,
            tags=skill.tags,
            license=skill.license,
            files=[],
        )
    finally:
        await engine.dispose()

    db_session.expire_all()
    skill_row = (await db_session.execute(select(JoySafeterSkill).where(JoySafeterSkill.id == skill_id))).scalar_one()
    scan = (
        await db_session.execute(
            select(JoySafeterSkillSecurityScan).where(JoySafeterSkillSecurityScan.skill_id == skill_id)
        )
    ).scalar_one()

    assert skill_row.security_status == "failed"
    assert skill_row.security_scan_id == scan.id
    assert scan.status == "failed"
    assert scan.error_message == "Background skill security scan failed"
    assert scan.report == {
        "error": {
            "type": "error",
            "code": "SKILL_SECURITY_BACKGROUND_SCAN_FAILED",
            "message": "Background skill security scan failed",
            "data": {
                "boundary": "skill_security",
                "operation": "run_background_scan",
                "skill_id": str(skill_id),
                "trigger": "create",
                "project_id": None,
                "owner_id": user_id,
            },
            "source": "runtime",
            "retryable": True,
            "user_action": "retry",
            "detail": "RuntimeError",
        }
    }
