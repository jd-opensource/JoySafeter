from __future__ import annotations

import uuid

import pytest

from app.joysafeter_domain.models.joysafeter_skill import JoySafeterSkillUsageLog
from app.joysafeter_domain.services.joysafeter_skill_security import SkillPacker


pytestmark = pytest.mark.no_db


class _Db:
    def __init__(self):
        self.added = None
        self.flushed = False

    def add(self, row):
        self.added = row

    async def flush(self):
        self.flushed = True


async def test_skill_usage_log_records_version_scan_target_and_artifact_hash():
    db = _Db()
    packer = SkillPacker(
        db,  # type: ignore[arg-type]
        project_id="project-a",
        session_id="session-a",
        agent_id="agent-a",
        user_id="user-a",
    )
    skill_id = uuid.uuid4()
    version_id = uuid.uuid4()
    scan_id = uuid.uuid4()

    await packer._record_usage(
        skill_id=skill_id,
        skill_version="1.2.3",
        skill_name="audit-skill",
        skill_source_type="manual",
        skill_version_id=version_id,
        security_scan_id=scan_id,
        target_hash="a" * 64,
        artifact_hash="b" * 64,
        target="/skills/audit-skill",
    )

    assert db.flushed is True
    assert isinstance(db.added, JoySafeterSkillUsageLog)
    assert db.added.skill_id == skill_id
    assert db.added.skill_version == "1.2.3"
    assert db.added.skill_name == "audit-skill"
    assert db.added.skill_source_type == "manual"
    assert db.added.skill_version_id == version_id
    assert db.added.security_scan_id == scan_id
    assert db.added.target_hash == "a" * 64
    assert db.added.artifact_hash == "b" * 64
    assert db.added.target == "/skills/audit-skill"
    assert db.added.session_id == "session-a"
    assert db.added.agent_id == "agent-a"
    assert db.added.project_id == "project-a"
    assert db.added.user_id == "user-a"
