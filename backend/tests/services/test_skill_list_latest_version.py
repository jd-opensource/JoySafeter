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


@pytest.mark.asyncio
async def test_list_skills_annotates_latest_published_version(monkeypatch):
    skill = SimpleNamespace(
        id="skill-a",
        project_id="project-a",
        org_version_id=None,
        public_version_id=None,
    )
    svc = SkillService.__new__(SkillService)
    svc.db = object()
    svc.repo = _Repo([skill])
    svc._caller_org_role = None
    svc._active_org_id = "org-a"

    monkeypatch.setattr(skill_service_mod, "SkillVersionRepository", _VersionRepo)

    skills, has_more = await svc.list_skills(
        current_user_id="user-a",
        project_id="project-a",
        limit=20,
    )

    assert has_more is False
    assert skills == [skill]
    assert skill.latest_version == "1.0.0"
