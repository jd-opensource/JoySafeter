from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.joysafeter_domain.services import joysafeter_skill_service as skill_service_mod
from app.joysafeter_domain.services.joysafeter_skill_service import SkillService

pytestmark = pytest.mark.no_db


class _Repo:
    def __init__(self, skills):
        self.skills = skills

    async def list_by_user(self, **kwargs):
        return self.skills, False


class _VersionRepo:
    def __init__(self, db):
        self.db = db

    async def latest_version_map(self, skill_ids):
        return {skill_ids[0]: "1.0.0"}


def _skill():
    return SimpleNamespace(
        id="skill-a",
        name="skill-a",
        description="d",
        content="c",
        tags=[],
        license=None,
        files=[],
        lifecycle_status="draft",
        security_status="not_scanned",
        security_scan_hash=None,
    )


@pytest.mark.asyncio
async def test_list_skills_includes_runtime_eligibility(monkeypatch):
    skill = _skill()
    svc = SkillService.__new__(SkillService)
    svc.db = object()
    svc.repo = _Repo([skill])
    svc._caller_org_role = None

    monkeypatch.setattr(skill_service_mod, "SkillVersionRepository", _VersionRepo)

    skills, has_more = await svc.list_skills(current_user_id="user-a", limit=20)

    assert has_more is False
    assert skills == [skill]
    assert skill.latest_version == "1.0.0"
    assert skill.runtime_eligibility["usable"] is False
    assert skill.runtime_eligibility["reason"] == "skill_not_approved"
    assert skill.runtime_eligibility["next_action"] == "submit_or_approve"
