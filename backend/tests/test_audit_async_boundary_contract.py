import uuid
from types import SimpleNamespace

import pytest

from app.joysafeter_api.api.v1 import audit as audit_module
from app.joysafeter_api.api.v1.audit import audit_joysafeter_event
from app.joysafeter_domain.services.joysafeter_security_audit_service import SecurityAuditService
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.ids import OrganizationId, ProjectId, UserId

pytestmark = pytest.mark.no_db


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
    user_id = UserId.new()
    organization_id = OrganizationId.new()
    project_id = ProjectId.new()
    auth_ctx = JoySafeterAuthContext(
        user_id=user_id,
        org_id=organization_id,
        project_id=project_id,
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
                "user_id": user_id,
                "org_id": organization_id,
                "project_id": project_id,
            },
            "source": "api",
            "retryable": True,
            "user_action": "retry",
            "detail": "RuntimeError",
        }
    }


@pytest.mark.asyncio
async def test_audit_serializes_typed_ids_at_json_boundary(monkeypatch):
    captured: dict[str, object] = {}

    async def capture_log_event(self, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(SecurityAuditService, "log_event", capture_log_event)
    user_id = UserId.new()
    organization_id = OrganizationId.new()
    project_id = ProjectId.new()

    await audit_joysafeter_event(
        db=object(),
        request=SimpleNamespace(client=None, headers={}),
        auth_ctx=JoySafeterAuthContext(
            user_id=user_id,
            org_id=organization_id,
            project_id=project_id,
            role=JoySafeterRole.ADMIN,
        ),
        event_type="project.updated",
        target_type="project",
        target_id=project_id,
        details={"organization_id": organization_id},
    )

    assert captured["user_id"] == user_id
    assert captured["details"] == {
        "org_id": str(organization_id),
        "project_id": str(project_id),
        "role": "admin",
        "principal_type": "user",
        "principal_id": str(user_id),
        "target_type": "project",
        "target_id": str(project_id),
        "organization_id": str(organization_id),
    }
