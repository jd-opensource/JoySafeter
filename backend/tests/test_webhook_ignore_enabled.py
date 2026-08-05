"""Webhook test-fire bypasses the disabled gate (ignore_enabled).

Proven without invoking the executor: with a filter that the payload does not
match, ``fire_webhook`` returns at the filter check — which is AFTER the enabled
gate. So a disabled trigger returning "delivery did not match filter" (instead of
"trigger disabled") proves ignore_enabled let it past the enabled gate.
"""

import uuid

import pytest

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.services.joysafeter_trigger_service import JoySafeterTriggerService


async def _seed_disabled_webhook(db_session):
    org = Organization(name=f"wh-org-{uuid.uuid4()}", slug=f"wh-org-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name="P", slug=f"wh-p-{uuid.uuid4()}")
    db_session.add(project)
    await db_session.flush()
    agent = JoySafeterAgent(name=f"wh-agent-{uuid.uuid4()}", project_id=project.id)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    await db_session.refresh(project)
    trigger = JoySafeterTrigger(
        name="hook",
        type="webhook",
        agent_id=agent.id,
        prompt_template="p",
        enabled=False,
        filter={"body.kind": "wanted"},  # payload below will NOT match
        config={},
        last_payload={},
        project_id=project.id,
        user_id="owner",
        org_id=org.id,
    )
    db_session.add(trigger)
    await db_session.commit()
    await db_session.refresh(trigger)
    return trigger


@pytest.mark.asyncio
async def test_disabled_returns_disabled_without_ignore(db_session):
    trigger = await _seed_disabled_webhook(db_session)
    status, task, session_id, deduped, reason = await JoySafeterTriggerService(db_session).fire_webhook(
        trigger,
        raw_body=b"{}",
        payload={"body": {"kind": "other"}},
        delivery_id="d1",
        auth_fingerprint="x",
    )
    assert status == "skipped"
    assert reason == "trigger disabled"


@pytest.mark.asyncio
async def test_ignore_enabled_passes_the_enabled_gate(db_session):
    trigger = await _seed_disabled_webhook(db_session)
    status, task, session_id, deduped, reason = await JoySafeterTriggerService(db_session).fire_webhook(
        trigger,
        raw_body=b"{}",
        payload={"body": {"kind": "other"}},  # does not match the filter
        delivery_id="d2",
        auth_fingerprint="x",
        ignore_enabled=True,
    )
    # Reached the filter check (past the enabled gate) → filter mismatch, not "disabled".
    assert status == "skipped"
    assert reason == "delivery did not match filter"
