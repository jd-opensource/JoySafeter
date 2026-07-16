"""Unit tests for ``SkillService.add_file`` security-scan skipping.

A newly-created file starts empty — both the ``.gitkeep`` a folder-create adds
and any regular file the user creates before typing into it. Empty content has
nothing to scan, so ``add_file`` must NOT dispatch a security scan for it (a
scan is slow and flips the skill to ``scanning``). Files created WITH content
still scan; so does the later ``update_file`` when the user saves real content.

Strategy: build a bare ``SkillService`` with stubbed collaborators and patch
``_dispatch_security_scan`` with an ``AsyncMock`` so we can assert whether it
was called, staying fully in-process.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.joysafeter_domain.services.joysafeter_skill_service import SkillService
from app.joysafeter_shared.common.app_errors import ResourceConflictError


def _make_service(monkeypatch, *, lifecycle_status="draft"):
    svc = SkillService.__new__(SkillService)
    svc._active_org_id = None

    skill = SimpleNamespace(
        id=uuid.uuid4(),
        owner_id="user-1",
        project_id=None,
        name="s",
        description="d",
        content="c",
        tags=[],
        license=None,
        files=[],
        security_status="passed",
        lifecycle_status=lifecycle_status,
    )

    class _DB:
        def add(self, _):
            pass

        async def commit(self):
            pass

        async def refresh(self, _):
            pass

    svc.db = _DB()

    repo = MagicMock()
    repo.get_with_files = AsyncMock(return_value=skill)
    svc.repo = repo

    svc.security_service = MagicMock()
    svc.security_service.files_from_skill = MagicMock(return_value=[])
    svc.security_service.apply_latest_scan = MagicMock()

    # Bypass permission check.
    async def _allow(*_a, **_k):
        return None

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_skill_service.check_skill_access",
        _allow,
    )

    # Spy on the scan dispatch.
    dispatch = AsyncMock(return_value=None)
    monkeypatch.setattr(svc, "_dispatch_security_scan", dispatch)
    return svc, dispatch


async def test_empty_gitkeep_placeholder_skips_scan(monkeypatch):
    """Folder creation (empty .gitkeep) must not trigger a scan."""
    svc, dispatch = _make_service(monkeypatch)
    await svc.add_file(
        skill_id=uuid.uuid4(),
        current_user_id="user-1",
        path="refs/",
        file_name=".gitkeep",
        file_type="text",
        content="",
    )
    dispatch.assert_not_called()


async def test_empty_regular_file_skips_scan(monkeypatch):
    """A regular file created empty (before the user types) also skips."""
    svc, dispatch = _make_service(monkeypatch)
    await svc.add_file(
        skill_id=uuid.uuid4(),
        current_user_id="user-1",
        path="refs/",
        file_name="notes.md",
        file_type="markdown",
        content="",
    )
    dispatch.assert_not_called()


async def test_file_with_content_triggers_scan(monkeypatch):
    """A file created with actual content scans immediately."""
    svc, dispatch = _make_service(monkeypatch)
    await svc.add_file(
        skill_id=uuid.uuid4(),
        current_user_id="user-1",
        path="refs/",
        file_name="foo.py",
        file_type="python",
        content="print('x')",
    )
    dispatch.assert_awaited_once()


async def test_archived_skill_rejects_file_add_before_scan_or_commit(monkeypatch):
    svc, dispatch = _make_service(monkeypatch, lifecycle_status="archived")

    with pytest.raises(ResourceConflictError) as ei:
        await svc.add_file(
            skill_id=uuid.uuid4(),
            current_user_id="user-1",
            path="refs/",
            file_name="notes.md",
            file_type="markdown",
            content="new content",
        )

    assert ei.value.code == "SKILL_ARCHIVED"
    dispatch.assert_not_called()


# ── delete_file: skip scan when the deleted file was empty ──────────────


def _make_delete_service(monkeypatch, *, deleted_content):
    """Bare ``SkillService`` for exercising ``delete_file``'s scan gate.

    ``deleted_content`` is the content of the file being removed.
    """
    svc = SkillService.__new__(SkillService)
    svc._active_org_id = None

    file_id = uuid.uuid4()
    skill_id = uuid.uuid4()
    file_obj = SimpleNamespace(
        id=file_id,
        skill_id=skill_id,
        path="refs/",
        file_name="x.md",
        file_type="markdown",
        content=deleted_content,
        storage_type="database",
        storage_key=None,
        size=len(deleted_content or ""),
    )
    skill = SimpleNamespace(
        id=skill_id,
        owner_id="user-1",
        project_id=None,
        name="s",
        description="d",
        content="c",
        tags=[],
        license=None,
        files=[file_obj],
        security_status="passed",
    )

    class _DB:
        async def commit(self):
            pass

    svc.db = _DB()

    file_repo = MagicMock()
    file_repo.get = AsyncMock(return_value=file_obj)
    file_repo.delete = AsyncMock(return_value=None)
    svc.file_repo = file_repo

    repo = MagicMock()
    repo.get_with_files = AsyncMock(return_value=skill)
    svc.repo = repo

    svc.security_service = MagicMock()
    svc.security_service.apply_latest_scan = MagicMock()

    async def _allow(*_a, **_k):
        return None

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_skill_service.check_skill_access",
        _allow,
    )
    dispatch = AsyncMock(return_value=None)
    monkeypatch.setattr(svc, "_dispatch_security_scan", dispatch)
    return svc, dispatch, file_obj


async def test_delete_empty_file_skips_scan(monkeypatch):
    """Deleting an empty file/placeholder changes nothing scannable → no scan."""
    svc, dispatch, file_obj = _make_delete_service(monkeypatch, deleted_content="")
    await svc.delete_file(file_id=file_obj.id, current_user_id="user-1")
    dispatch.assert_not_called()


async def test_delete_nonempty_file_triggers_scan(monkeypatch):
    """Deleting a file that had content changes the surface → still scans."""
    svc, dispatch, file_obj = _make_delete_service(monkeypatch, deleted_content="rm -rf /")
    await svc.delete_file(file_id=file_obj.id, current_user_id="user-1")
    dispatch.assert_awaited_once()
