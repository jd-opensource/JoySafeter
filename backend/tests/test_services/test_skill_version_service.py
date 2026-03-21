"""Unit tests for SkillVersionService."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.skill_version_service import SkillVersionService


def _mock_skill(owner_id="user-1", name="test-skill", content="body"):
    s = MagicMock()
    s.id = uuid.uuid4()
    s.owner_id = owner_id
    s.name = name
    s.description = "desc"
    s.content = content
    s.tags = ["a"]
    s.meta_data = {}
    s.allowed_tools = []
    s.compatibility = None
    s.license = None
    s.is_public = False
    s.files = []
    return s


def _mock_db():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


class TestSkillVersionServicePublish:
    """Test version publishing logic."""

    @pytest.mark.asyncio
    async def test_publish_validates_semver_format(self):
        """Invalid semver should raise BadRequestException."""
        from app.common.exceptions import BadRequestException

        db = _mock_db()
        skill = _mock_skill()
        with patch.object(SkillVersionService, "__init__", lambda self, db: None):
            service = SkillVersionService.__new__(SkillVersionService)
            service.db = db
            service.skill_repo = MagicMock()
            service.skill_repo.get_with_files = AsyncMock(return_value=skill)
            service.repo = MagicMock()
            service.file_repo = MagicMock()
            service.skill_file_repo = MagicMock()

            with patch("app.services.skill_version_service.check_skill_access", new_callable=AsyncMock):
                with pytest.raises(BadRequestException, match="Invalid version"):
                    await service.publish_version(
                        skill_id=skill.id,
                        current_user_id="user-1",
                        version_str="invalid",
                        release_notes="",
                    )

    @pytest.mark.asyncio
    async def test_publish_rejects_lower_version(self):
        """New version must be greater than existing highest."""
        from app.common.exceptions import BadRequestException

        db = _mock_db()
        skill = _mock_skill()

        with patch.object(SkillVersionService, "__init__", lambda self, db: None):
            service = SkillVersionService.__new__(SkillVersionService)
            service.db = db
            service.skill_repo = MagicMock()
            service.skill_repo.get_with_files = AsyncMock(return_value=skill)
            service.repo = MagicMock()
            service.repo.get_highest_version_str = AsyncMock(return_value="2.0.0")
            service.file_repo = MagicMock()
            service.skill_file_repo = MagicMock()

            with patch("app.services.skill_version_service.check_skill_access", new_callable=AsyncMock):
                with pytest.raises(BadRequestException, match="greater"):
                    await service.publish_version(
                        skill_id=skill.id,
                        current_user_id="user-1",
                        version_str="1.0.0",
                        release_notes="",
                    )
