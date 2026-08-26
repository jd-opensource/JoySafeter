import uuid

import pytest
from error_contract_helpers import handled_app_error_payload

from app.joysafeter_api.api.v1.sessions import send_event
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.schemas.joysafeter_session import SendEventRequest, SingleEventRequest
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.ids import AgentId, OrganizationId, SessionId, UserId


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id=UserId.new(),
        org_id=OrganizationId.new(),
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.MEMBER,
    )


async def _session(db_session) -> JoySafeterSession:
    agent = JoySafeterAgent(id=AgentId.new(), name=f"session-input-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    session = JoySafeterSession(id=SessionId.new(), agent_id=agent.id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    return session


@pytest.mark.asyncio
async def test_send_event_empty_events_returns_structured_validation_error(db_session):
    session = await _session(db_session)

    with pytest.raises(AppError) as exc_info:
        await send_event(SendEventRequest(events=[]), session.id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "SESSION_EVENTS_EMPTY",
        "message": "No events provided",
        "data": {"field": "events"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_user_message_missing_content_returns_structured_validation_error(db_session):
    session = await _session(db_session)
    req = SendEventRequest(events=[SingleEventRequest(type="user.message")])

    with pytest.raises(AppError) as exc_info:
        await send_event(req, session.id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=422) == {
        "code": "SESSION_USER_MESSAGE_CONTENT_REQUIRED",
        "message": "user.message requires content",
        "data": {"field": "content", "event_type": "user.message"},
        "source": "validation",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_user_message_invalid_content_block_returns_structured_validation_error(db_session):
    session = await _session(db_session)
    req = SendEventRequest(events=[SingleEventRequest(type="user.message", content=[{"type": "image"}])])

    with pytest.raises(AppError) as exc_info:
        await send_event(req, session.id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=422) == {
        "code": "SESSION_CONTENT_BLOCK_INVALID",
        "message": "Content blocks must have type 'text' and a string 'text' field",
        "data": {"field": "content", "index": 0, "block_type": "image"},
        "source": "validation",
        "retryable": False,
        "user_action": "fix_input",
    }
