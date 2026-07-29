"""Session stop must be idempotent under the task-completion TOCTOU race.

``POST /sessions/{id}/stop`` snapshots the active tasks, then cancels each one.
A task can reach a terminal state *between* that snapshot and the per-task
cancel — it finishes on its own, or a previous (retried) stop already cancelled
it. The task state machine raises ``ValueError("Task already in terminal
state: ...")`` for an already-terminal task; if stop_session lets that escape it
becomes an HTTP 500, even though the operator's intent (the task is stopped) is
already satisfied. Stopping a session is idempotent, so this benign race must
end with the session idle, not a 500.
"""

import uuid

import pytest
from sqlalchemy import select

from app.joysafeter_api.api.v1.sessions import stop_session
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.services.joysafeter_task_service import JoySafeterTaskService
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.MEMBER,
    )


@pytest.mark.asyncio
async def test_stop_session_is_idempotent_when_task_becomes_terminal_during_stop(db_session, monkeypatch):
    monkeypatch.setattr("app.joysafeter_shared.orchestrator_bridge.get_session_broadcaster", lambda: None)

    agent = JoySafeterAgent(name=f"stop-race-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, status="running")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    # The task is ALREADY terminal in the DB (it just finished), with no sandbox
    # (nothing to relay to). The stop's first active-task snapshot still reports it
    # as active — modelling the TOCTOU window.
    task = JoySafeterTask(
        agent_id=agent.id,
        chat_session_id=session_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.CANCELLED.value,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    task_id = task.id

    real_list = JoySafeterTaskService.list_active_tasks_by_session
    calls = {"n": 0}

    async def stale_then_real(self, sid, project_id=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return [task]  # stale snapshot: the task still looked active here
        return await real_list(self, sid, project_id=project_id)

    monkeypatch.setattr(JoySafeterTaskService, "list_active_tasks_by_session", stale_then_real)

    # Must not raise a bare ValueError (which would surface as a 500).
    result = await stop_session(session_id, db_session, _auth_ctx())
    assert result["status"] == "idle"

    db_session.expire_all()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
    task_row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    assert session_row.status == "idle"
    assert task_row.status == JoySafeterTaskStatus.CANCELLED.value
