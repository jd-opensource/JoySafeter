from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.joysafeter_domain.services.joysafeter_skill_service import SkillService
from app.joysafeter_shared.common.app_errors import ResourceConflictError
from app.joysafeter_shared.ids import OrganizationId, SkillFileId, SkillId, UserId

pytestmark = pytest.mark.no_db


def _make_service(monkeypatch: pytest.MonkeyPatch, *, lifecycle_status: str = "draft"):
    service = SkillService.__new__(SkillService)
    service._active_org_id = OrganizationId.new()

    skill = SimpleNamespace(
        id=SkillId.new(),
        owner_id=UserId.new(),
        project_id=None,
        name="skill",
        description="description",
        content="content",
        tags=[],
        license=None,
        files=[],
        security_status="passed",
        lifecycle_status=lifecycle_status,
    )

    class DatabaseStub:
        def add(self, _value):
            return None

        async def commit(self):
            return None

        async def refresh(self, _value):
            return None

    service.db = DatabaseStub()
    service.repo = MagicMock(get_with_files=AsyncMock(return_value=skill))
    service.security_service = MagicMock()
    service.security_service.files_from_skill.return_value = []

    async def allow_access(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_skill_service.check_skill_access",
        allow_access,
    )
    dispatch = AsyncMock(return_value=None)
    monkeypatch.setattr(service, "_dispatch_security_scan", dispatch)
    return service, dispatch


async def test_adding_empty_file_does_not_dispatch_security_scan(monkeypatch: pytest.MonkeyPatch):
    service, dispatch = _make_service(monkeypatch)

    await service.add_file(
        skill_id=SkillId.new(),
        current_user_id=UserId.new(),
        path="references/",
        file_name="notes.md",
        file_type="markdown",
        content="",
    )

    dispatch.assert_not_called()


async def test_adding_nonempty_file_dispatches_security_scan(monkeypatch: pytest.MonkeyPatch):
    service, dispatch = _make_service(monkeypatch)

    await service.add_file(
        skill_id=SkillId.new(),
        current_user_id=UserId.new(),
        path="references/",
        file_name="check.py",
        file_type="python",
        content="print('checked')",
    )

    dispatch.assert_awaited_once()


async def test_archived_skill_rejects_file_add_before_scan(monkeypatch: pytest.MonkeyPatch):
    service, dispatch = _make_service(monkeypatch, lifecycle_status="archived")

    with pytest.raises(ResourceConflictError, match="archived") as error:
        await service.add_file(
            skill_id=SkillId.new(),
            current_user_id=UserId.new(),
            path="references/",
            file_name="notes.md",
            file_type="markdown",
            content="new content",
        )

    assert error.value.code == "SKILL_ARCHIVED"
    dispatch.assert_not_called()


def _make_delete_service(monkeypatch: pytest.MonkeyPatch, *, deleted_content: str):
    service = SkillService.__new__(SkillService)
    service._active_org_id = OrganizationId.new()

    file_id = SkillFileId.new()
    skill_id = SkillId.new()
    file_record = SimpleNamespace(
        id=file_id,
        skill_id=skill_id,
        path="references/",
        file_name="notes.md",
        file_type="markdown",
        content=deleted_content,
        storage_type="database",
        storage_key=None,
        size=len(deleted_content),
    )
    skill = SimpleNamespace(
        id=skill_id,
        owner_id=UserId.new(),
        project_id=None,
        name="skill",
        description="description",
        content="content",
        tags=[],
        license=None,
        files=[file_record],
        security_status="passed",
        lifecycle_status="draft",
    )

    class DatabaseStub:
        async def commit(self):
            return None

    service.db = DatabaseStub()
    service.file_repo = MagicMock(
        get=AsyncMock(return_value=file_record),
        delete=AsyncMock(return_value=None),
    )
    service.repo = MagicMock(get_with_files=AsyncMock(return_value=skill))
    service.security_service = MagicMock()

    async def allow_access(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_skill_service.check_skill_access",
        allow_access,
    )
    dispatch = AsyncMock(return_value=None)
    monkeypatch.setattr(service, "_dispatch_security_scan", dispatch)
    return service, dispatch, file_record


async def test_deleting_empty_file_does_not_dispatch_security_scan(monkeypatch: pytest.MonkeyPatch):
    service, dispatch, file_record = _make_delete_service(monkeypatch, deleted_content="")

    await service.delete_file(file_id=file_record.id, current_user_id=UserId.new())

    dispatch.assert_not_called()


async def test_deleting_nonempty_file_dispatches_security_scan(monkeypatch: pytest.MonkeyPatch):
    service, dispatch, file_record = _make_delete_service(
        monkeypatch,
        deleted_content="rm -rf /",
    )

    await service.delete_file(file_id=file_record.id, current_user_id=UserId.new())

    dispatch.assert_awaited_once()
