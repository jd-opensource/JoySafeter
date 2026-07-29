import uuid
from types import SimpleNamespace

import pytest

from app.joysafeter_api.api.v1 import audit as audit_module
from app.joysafeter_api.api.v1.audit import audit_joysafeter_event
from app.joysafeter_domain.services.joysafeter_security_audit_service import SecurityAuditService
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole


class _FakeLogger:
    def __init__(self):
        self.bound: dict | None = None
        self.messages: list[str] = []

    def bind(self, **kwargs):
        self.bound = kwargs
        return self

    def exception(self, message: str):
        self.messages.append(message)


@pytest.mark.asyncio
async def test_audit_failure_logs_structured_async_boundary_error(monkeypatch):
    async def fail_log_event(self, **kwargs):
        raise RuntimeError("audit db unavailable")

    fake_logger = _FakeLogger()
    monkeypatch.setattr(SecurityAuditService, "log_event", fail_log_event)
    monkeypatch.setattr(audit_module, "logger", fake_logger)

    target_id = str(uuid.uuid4())
    request = SimpleNamespace(
        client=SimpleNamespace(host="127.0.0.1"),
        headers={"user-agent": "pytest"},
    )
    auth_ctx = JoySafeterAuthContext(
        user_id="user-1",
        org_id="org-1",
        project_id="project-1",
        role=JoySafeterRole.ADMIN,
    )

    await audit_joysafeter_event(
        db=object(),
        request=request,
        auth_ctx=auth_ctx,
        event_type="secret.created",
        target_type="secret",
        target_id=target_id,
    )

    assert fake_logger.messages == ["Failed to write JoySafeter audit event"]
    assert fake_logger.bound == {
        "error": {
            "type": "error",
            "code": "AUDIT_EVENT_WRITE_FAILED",
            "message": "Failed to write JoySafeter audit event",
            "data": {
                "boundary": "audit",
                "operation": "write_event",
                "event_type": "secret.created",
                "event_status": "success",
                "target_type": "secret",
                "target_id": target_id,
                "user_id": "user-1",
                "org_id": "org-1",
                "project_id": "project-1",
            },
            "source": "api",
            "retryable": True,
            "user_action": "retry",
            "detail": "RuntimeError",
        }
    }
