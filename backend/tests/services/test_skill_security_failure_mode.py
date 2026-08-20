"""Unit tests for informational ``SkillSecurityService.scan_for_write``."""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.joysafeter_domain.services.joysafeter_skill_security import SkillSecurityScannerClient, SkillSecurityService
from app.joysafeter_shared.security.ssrf_guard import SSRFError

pytestmark = pytest.mark.no_db


def _make_service(*, scanner_raises=True):
    """Construct a service with mocked deps for the failure path.

    Scanner is the only seam we need; the DB is a no-op, and we set the
    settings flag inside each test so global state doesn't leak between
    tests.
    """
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    svc = SkillSecurityService.__new__(SkillSecurityService)
    svc.db = db
    svc.repo = None
    svc.skill_repo = None
    svc.client = MagicMock()
    svc.client.scan = AsyncMock(side_effect=Exception("scanner unreachable") if scanner_raises else None)
    return svc


_COMMON = dict(
    trigger="create",
    created_by_id="user-1",
    owner_id="user-1",
    project_id="proj-1",
    skill_id=None,
    name="t",
    description="d",
    content="c",
    tags=[],
    license=None,
    files=[],
)


def test_scan_for_write_has_no_gate_controls():
    parameters = inspect.signature(SkillSecurityService.scan_for_write).parameters

    assert "enforce_write_policy" not in parameters
    assert "failure_mode" not in parameters


@pytest.fixture
def settings_mock():
    """Patch the settings singleton the service reads inside the call."""
    with patch("app.joysafeter_domain.services.joysafeter_skill_security.settings") as ms:
        ms.skill_security_scan_enabled = True
        ms.skill_security_no_llm = True
        yield ms


async def test_scanner_failure_is_recorded_without_blocking(settings_mock):
    svc = _make_service()
    scan = await svc.scan_for_write(**_COMMON)
    assert scan is not None
    assert scan.status == "failed"


async def test_scan_disabled_short_circuits(settings_mock):
    """When the deployment turns scanning off, the service returns
    ``None`` before touching the client or the DB."""
    settings_mock.skill_security_scan_enabled = False
    svc = _make_service()
    result = await svc.scan_for_write(**_COMMON)
    assert result is None
    svc.client.scan.assert_not_called()


async def test_scanner_client_rejects_metadata_base_url_before_http(monkeypatch):
    class AsyncClientShouldNotBeConstructed:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("unsafe scanner URL reached httpx")

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_skill_security.httpx.AsyncClient",
        AsyncClientShouldNotBeConstructed,
    )

    client = SkillSecurityScannerClient("http://169.254.169.254/latest", timeout_seconds=1)
    with pytest.raises(SSRFError):
        await client.scan([])
