"""Unit tests for the Phase-3 correctness fixes on the version stack.

1. ``get_highest_version_str`` / the version auto-bump must not raise an
   unhandled 500 when a stored version string is not valid semver — it
   raises ``InvalidRequestError`` (400) with a clear code instead.
2. ``SkillVersionService.restore_draft`` must populate the request-scoped
   ``latest_version`` annotation on the returned skill so the route
   response matches ``get_skill`` (which attaches it).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.joysafeter_domain.services.joysafeter_skill_service import SkillVersionService
from app.joysafeter_shared.common.app_errors import InvalidRequestError

pytestmark = [pytest.mark.asyncio, pytest.mark.no_db]


# ── #1 non-semver stored version → 400, not 500 ─────────────────


async def test_publish_version_nonsemver_stored_highest_raises_400(monkeypatch):
    """A pre-existing non-semver row (e.g. ``"latest"``) previously blew up
    ``semver.Version.parse`` with an unhandled ValueError → 500. Now it maps
    to a clean 400."""
    skill = SimpleNamespace(
        id=uuid.uuid4(),
        owner_id="user-1",
        security_status="passed",
        name="x",
        description="x",
        content="x",
        tags=[],
        meta_data={},
        allowed_tools=[],
        compatibility=None,
        license=None,
        lifecycle_status="approved",
    )
    svc = SkillVersionService.__new__(SkillVersionService)
    svc.db = MagicMock()
    svc._active_org_id = None
    svc._caller_org_role = None
    svc.repo = MagicMock()
    svc.repo.get_highest_version_str = AsyncMock(return_value="not-a-semver")

    async def _get_skill(_skill_id):
        return skill

    async def _allow(*_a, **_kw):
        return None

    monkeypatch.setattr(svc, "_get_skill_with_files_or_404", _get_skill)
    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_skill_service.check_skill_access",
        _allow,
    )

    with pytest.raises(InvalidRequestError) as ei:
        await svc.publish_version(skill_id=skill.id, current_user_id="user-1", version_str="1.2.3")
    assert ei.value.code == "SKILL_VERSION_STORED_INVALID"


# ── #2 restore populates latest_version ─────────────────────────


async def test_restore_draft_populates_latest_version(monkeypatch):
    skill = SimpleNamespace(
        id=uuid.uuid4(),
        owner_id="user-1",
        lifecycle_status="approved",
        latest_version=None,
    )
    sv = SimpleNamespace(
        id=uuid.uuid4(),
        skill_name="restored",
        skill_description="d",
        content="c",
        tags=[],
        meta_data={},
        allowed_tools=[],
        compatibility=None,
        license=None,
    )

    svc = SkillVersionService.__new__(SkillVersionService)
    svc.db = MagicMock()
    svc.db.commit = AsyncMock()
    svc.db.refresh = AsyncMock()
    svc.db.add = MagicMock()
    svc._active_org_id = None
    svc._caller_org_role = None
    svc.repo = MagicMock()
    svc.repo.get_by_version = AsyncMock(return_value=sv)
    svc.repo.get_latest = AsyncMock(return_value=SimpleNamespace(version="3.1.4"))
    svc.file_repo = MagicMock()
    svc.file_repo.list_by_version = AsyncMock(return_value=[])
    svc.skill_file_repo = MagicMock()
    svc.skill_file_repo.delete_by_skill = AsyncMock()

    async def _get_skill(_skill_id):
        return skill

    async def _allow(*_a, **_kw):
        return None

    monkeypatch.setattr(svc, "_get_skill_with_files_or_404", _get_skill)
    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_skill_service.check_skill_access",
        _allow,
    )

    result = await svc.restore_draft(skill_id=skill.id, version_str="1.0.0", current_user_id="user-1")
    assert result.latest_version == "3.1.4"
