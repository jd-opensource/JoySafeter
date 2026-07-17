import uuid
from types import SimpleNamespace

import pytest

from app.joysafeter_domain.services.joysafeter_sandbox_service import SandboxService

pytestmark = pytest.mark.no_db


def _svc(*, sandbox, cas_result):
    svc = SandboxService(db=None)  # type: ignore[arg-type]
    calls: dict[str, object] = {}

    async def fake_get_sandbox(sandbox_id, project_id=None):
        calls["get_sandbox"] = (sandbox_id, project_id)
        return sandbox

    async def fake_update_status_cas(sandbox_id, expected_status, new_status):
        calls["cas"] = (sandbox_id, expected_status, new_status)
        return cas_result

    svc.get_sandbox = fake_get_sandbox  # type: ignore[assignment]
    svc.update_status_cas = fake_update_status_cas  # type: ignore[assignment]
    return svc, calls


@pytest.mark.asyncio
async def test_scoped_stop_reports_cas_failure_for_non_idle_sandbox():
    # A sandbox that exists and is owned but is NOT idle: the idle->stopping CAS
    # returns False. stop_sandbox must surface that False (the DELETE route then
    # 404s) rather than claiming success on a sandbox it did not actually stop.
    sandbox_id = uuid.uuid4()
    svc, calls = _svc(sandbox=SimpleNamespace(id=sandbox_id, status="running"), cas_result=False)

    result = await svc.stop_sandbox(sandbox_id, project_id="project-a")

    assert result is False
    assert calls["cas"] == (sandbox_id, "idle", "stopping")


@pytest.mark.asyncio
async def test_scoped_stop_reports_success_when_cas_succeeds():
    sandbox_id = uuid.uuid4()
    svc, _ = _svc(sandbox=SimpleNamespace(id=sandbox_id, status="idle"), cas_result=True)

    result = await svc.stop_sandbox(sandbox_id, project_id="project-a")

    assert result is True


@pytest.mark.asyncio
async def test_scoped_stop_returns_false_and_skips_cas_when_not_owned():
    sandbox_id = uuid.uuid4()
    svc, calls = _svc(sandbox=None, cas_result=True)

    result = await svc.stop_sandbox(sandbox_id, project_id="other-project")

    assert result is False
    assert "cas" not in calls
