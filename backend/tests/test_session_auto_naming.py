from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.joysafeter_api.api.v1.sessions import create_session
from app.joysafeter_application.credentials.ports import CredentialAuditActor
from app.joysafeter_application.credentials.snapshot_service import CreateCredentialAwareSession
from app.joysafeter_application.sessions.creation_service import SessionCreationService
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_security_audit_log import SecurityAuditLog
from app.joysafeter_domain.schemas.joysafeter_session import CreateSessionRequest
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.MEMBER,
    )


@pytest.fixture
async def named_agent(db_session) -> JoySafeterAgent:
    agent = JoySafeterAgent(name="Research Agent")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent


@pytest.mark.asyncio
@pytest.mark.parametrize("requested_title", [None, "   "])
async def test_create_session_generates_title_when_missing(
    db_session,
    named_agent,
    monkeypatch,
    requested_title,
):
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    monkeypatch.setattr(
        "app.joysafeter_application.credentials.snapshot_service.platform_now",
        lambda: datetime(2026, 8, 10, 16, 5, tzinfo=timezone.utc),
    )

    session = await SessionCreationService(
        db_session, audit_actor=CredentialAuditActor.system("test")
    ).create_from_source(
        CreateCredentialAwareSession(
            project_id=None,
            agent_id=named_agent.id,
            title=requested_title,
        )
    )

    assert session.title == "Research Agent · 08-10 16:05"


@pytest.mark.asyncio
async def test_create_session_preserves_trimmed_custom_title(db_session, named_agent):
    session = await SessionCreationService(
        db_session, audit_actor=CredentialAuditActor.system("test")
    ).create_from_source(
        CreateCredentialAwareSession(
            project_id=None,
            agent_id=named_agent.id,
            title="  Quarterly audit  ",
        )
    )

    assert session.title == "Quarterly audit"


@pytest.mark.asyncio
async def test_create_session_uses_stable_fallback_for_blank_agent_name(
    db_session,
    named_agent,
    monkeypatch,
):
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    monkeypatch.setattr(
        "app.joysafeter_application.credentials.snapshot_service.platform_now",
        lambda: datetime(2026, 8, 10, 16, 5, tzinfo=timezone.utc),
    )
    named_agent.name = "   "
    await db_session.commit()

    session = await SessionCreationService(
        db_session, audit_actor=CredentialAuditActor.system("test")
    ).create_from_source(
        CreateCredentialAwareSession(
            project_id=None,
            agent_id=named_agent.id,
        )
    )

    assert session.title == "Session · 08-10 16:05"


@pytest.mark.asyncio
async def test_create_session_api_auto_names_agent_shortcut(
    db_session,
    named_agent,
    monkeypatch,
):
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    monkeypatch.setattr(
        "app.joysafeter_application.credentials.snapshot_service.platform_now",
        lambda: datetime(2026, 8, 10, 16, 5, tzinfo=timezone.utc),
    )

    response = await create_session(
        CreateSessionRequest(agent_id=named_agent.id),
        db_session,
        _auth_ctx(),
    )

    assert response.title == "Research Agent · 08-10 16:05"
    audit = await db_session.scalar(
        select(SecurityAuditLog).where(
            SecurityAuditLog.event_type == "session.snapshot.created",
            SecurityAuditLog.details["target_id"].astext == str(response.id),
        )
    )
    assert audit is not None
    assert audit.user_id == "test-user"
    assert audit.ip_address == "unknown"
    assert audit.details["principal_type"] == "user"
    assert audit.details["principal_id"] == "test-user"
