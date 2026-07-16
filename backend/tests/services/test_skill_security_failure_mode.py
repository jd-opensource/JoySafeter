"""Unit tests for ``SkillSecurityService.scan_for_write`` ``failure_mode``.

The scanner-outage path has three independent knobs the caller can mix
to reach the right behavior:

  ``enforce_write_policy``  True  -> raise on any failure or block
                            False -> always record + return, never raise
  ``failure_mode``          default     -> follow global settings
                            fail_open   -> never raise on scanner outage
                            fail_closed -> always raise on scanner outage

This file pins the matrix so a refactor that "simplifies" one knob into
the other gets caught.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.joysafeter_domain.services.joysafeter_skill_security import SkillSecurityScannerClient, SkillSecurityService
from app.joysafeter_shared.common.app_errors import InvalidRequestError
from app.joysafeter_shared.security.ssrf_guard import SSRFError


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
    svc.client.scan = AsyncMock(
        side_effect=Exception("scanner unreachable") if scanner_raises else None
    )
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


@pytest.fixture
def settings_mock():
    """Patch the settings singleton the service reads inside the call."""
    with patch(
        "app.joysafeter_domain.services.joysafeter_skill_security.settings"
    ) as ms:
        ms.skill_security_scan_enabled = True
        ms.skill_security_no_llm = True
        ms.skill_security_fail_closed = True  # default; tests override
        yield ms


async def test_fail_open_overrides_global_fail_closed(settings_mock):
    """A draft-save caller passes ``fail_open`` to keep the editor
    unblocked even when the deployment-wide default is fail_closed."""
    svc = _make_service()
    scan = await svc.scan_for_write(failure_mode="fail_open", **_COMMON)
    assert scan is not None
    assert scan.status == "failed"


async def test_fail_closed_raises_invalid_request(settings_mock):
    """A publish caller passes ``fail_closed`` to demand a verdict, and
    a scanner outage should produce ``SKILL_SECURITY_SCAN_FAILED``."""
    svc = _make_service()
    with pytest.raises(InvalidRequestError) as ei:
        await svc.scan_for_write(failure_mode="fail_closed", **_COMMON)
    assert ei.value.code == "SKILL_SECURITY_SCAN_FAILED"


async def test_default_with_global_fail_closed_raises(settings_mock):
    settings_mock.skill_security_fail_closed = True
    svc = _make_service()
    with pytest.raises(InvalidRequestError):
        await svc.scan_for_write(failure_mode="default", **_COMMON)


async def test_default_with_global_fail_open_returns_scan(settings_mock):
    settings_mock.skill_security_fail_closed = False
    svc = _make_service()
    scan = await svc.scan_for_write(failure_mode="default", **_COMMON)
    assert scan is not None
    assert scan.status == "failed"


async def test_enforce_write_policy_false_always_returns(settings_mock):
    """Rescan paths set ``enforce_write_policy=False`` to refresh the
    cached verdict without throwing — that override beats every
    failure_mode."""
    settings_mock.skill_security_fail_closed = True
    svc = _make_service()
    scan = await svc.scan_for_write(
        failure_mode="fail_closed",
        enforce_write_policy=False,
        **_COMMON,
    )
    assert scan is not None
    assert scan.status == "failed"


async def test_scan_disabled_short_circuits(settings_mock):
    """When the deployment turns scanning off, the service returns
    ``None`` before touching the client or the DB."""
    settings_mock.skill_security_scan_enabled = False
    svc = _make_service()
    result = await svc.scan_for_write(failure_mode="fail_closed", **_COMMON)
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
