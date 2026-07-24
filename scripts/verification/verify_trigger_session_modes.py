#!/usr/bin/env python3
"""Real DB verification for trigger session_mode behavior.

This is intentionally not a unit test. It connects to the configured JoySafeter
PostgreSQL database, creates temporary agent/session/task records, runs the real
AgentTriggerExecutor path for fresh/reuse/pinned, and cleans up afterwards.

Only the final Redis enqueue call is intercepted so this verification does not
start a real sandbox task.

Run from repo root:
    cd backend && POSTGRES_HOST=localhost POSTGRES_PORT=5432 \
      POSTGRES_USER=conductor POSTGRES_PASSWORD=conductor POSTGRES_DB=joysafeter \
      .venv/bin/python ../scripts/verification/verify_trigger_session_modes.py
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_project import Project, ProjectMember
from app.joysafeter_domain.models.joysafeter_session import (
    JoySafeterSession,
    JoySafeterSessionEvent,
    SessionStatus,
)
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.services.agent_trigger_execution import (
    AgentTriggerExecutor,
    AgentTriggerRunConfig,
)
from app.joysafeter_shared.database import AsyncSessionLocal
import app.joysafeter_domain.services.task_submission_service as task_submission_service

STAMP = f"real-session-mode-{uuid.uuid4().hex[:10]}"


async def fake_enqueue(task_id: uuid.UUID) -> None:
    print(f"enqueue intercepted task={task_id}")


async def choose_real_scope(db: AsyncSession) -> tuple[str, str, str]:
    result = await db.execute(
        select(
            Project.id,
            Project.org_id,
            ProjectMember.user_id,
        )
        .select_from(Project)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(Project.archived_at.is_(None))
        .limit(1)
    )
    row = result.first()
    if row is None:
        raise RuntimeError("No active project/member found in real database")
    project_id, org_id, user_id = row
    return str(project_id), str(org_id), str(user_id)


async def finish_task(db: AsyncSession, task_id: uuid.UUID, session_id: uuid.UUID) -> None:
    now = datetime.now(timezone.utc)
    await db.execute(
        update(JoySafeterTask)
        .where(JoySafeterTask.id == task_id)
        .values(status=JoySafeterTaskStatus.COMPLETED.value, completed_at=now)
    )
    await db.execute(
        update(JoySafeterSession)
        .where(JoySafeterSession.id == session_id)
        .values(status=SessionStatus.IDLE.value)
    )
    await db.commit()


async def cleanup(db: AsyncSession, agent_id: uuid.UUID) -> None:
    session_ids = [
        row[0]
        for row in (
            await db.execute(select(JoySafeterSession.id).where(JoySafeterSession.agent_id == agent_id))
        ).all()
    ]
    task_ids = [
        row[0]
        for row in (
            await db.execute(select(JoySafeterTask.id).where(JoySafeterTask.agent_id == agent_id))
        ).all()
    ]
    if session_ids:
        await db.execute(delete(JoySafeterSessionEvent).where(JoySafeterSessionEvent.session_id.in_(session_ids)))
    if task_ids:
        await db.execute(delete(JoySafeterTask).where(JoySafeterTask.id.in_(task_ids)))
    if session_ids:
        await db.execute(delete(JoySafeterSession).where(JoySafeterSession.id.in_(session_ids)))
    await db.execute(delete(JoySafeterAgent).where(JoySafeterAgent.id == agent_id))
    await db.commit()


async def verify_remaining_clean(db: AsyncSession, agent_id: uuid.UUID) -> None:
    remaining_tasks = (await db.execute(select(JoySafeterTask.id).where(JoySafeterTask.agent_id == agent_id))).all()
    remaining_sessions = (
        await db.execute(select(JoySafeterSession.id).where(JoySafeterSession.agent_id == agent_id))
    ).all()
    remaining_agents = (await db.execute(select(JoySafeterAgent.id).where(JoySafeterAgent.id == agent_id))).all()
    print(
        f"cleanup remaining agents={len(remaining_agents)} "
        f"sessions={len(remaining_sessions)} tasks={len(remaining_tasks)}"
    )


async def main() -> None:
    task_submission_service.enqueue_joysafeter_task = fake_enqueue

    async with AsyncSessionLocal() as db:
        project_id, org_id, user_id = await choose_real_scope(db)
        print(f"using real scope project={project_id} org={org_id} user={user_id}")

        agent = JoySafeterAgent(
            project_id=project_id,
            name=STAMP,
            engine_kind="claude",
            model={"name": "verify"},
            system_prompt="verify system",
            description="temporary real DB session_mode verification",
            env={},
            mcp_configs=[],
            skills=[],
            tools=[],
            agents=[],
            commands=[],
            permission_mode="bypassPermissions",
            metadata_={"verify": STAMP},
            version=1,
        )
        db.add(agent)
        await db.flush()

        reusable = JoySafeterSession(
            project_id=project_id,
            agent_id=agent.id,
            title=f"{STAMP} reusable",
            status=SessionStatus.IDLE.value,
            usage={},
            metadata_={"verify": STAMP, "role": "reusable"},
            vault_ids=[],
            agent_version=1,
            agent_snapshot={"id": str(agent.id), "name": agent.name},
        )
        pinned = JoySafeterSession(
            project_id=project_id,
            agent_id=agent.id,
            title=f"{STAMP} pinned",
            status=SessionStatus.IDLE.value,
            usage={},
            metadata_={"verify": STAMP, "role": "pinned"},
            vault_ids=[],
            agent_version=1,
            agent_snapshot={"id": str(agent.id), "name": agent.name},
        )
        db.add_all([reusable, pinned])
        await db.commit()
        await db.refresh(agent)
        await db.refresh(reusable)
        await db.refresh(pinned)

        executor = AgentTriggerExecutor(db)
        try:
            base = dict(
                agent=agent,
                name=STAMP,
                source="real-verification",
                system_prompt=None,
                environment_ref=None,
                timeout_sec=60,
                max_retries=0,
                project_id=project_id,
                user_id=user_id,
                org_id=org_id,
                schedule_id=None,
                metadata={"verify": STAMP},
            )

            fresh = await executor.run(
                AgentTriggerRunConfig(
                    **base,
                    prompt="fresh mode real verification",
                    idempotency_key=f"{STAMP}:fresh",
                    session_mode="fresh",
                    reusable_session_id=reusable.id,
                    pinned_session_id=pinned.id,
                ),
                enforce_user_quota=False,
            )
            assert fresh.session.id not in {reusable.id, pinned.id}, "fresh should create a new session"
            assert fresh.created is True
            print(f"fresh  ok session={fresh.session.id} task={fresh.task.id} created={fresh.created}")
            await finish_task(db, fresh.task.id, fresh.session.id)

            reuse = await executor.run(
                AgentTriggerRunConfig(
                    **base,
                    prompt="reuse mode real verification",
                    idempotency_key=f"{STAMP}:reuse",
                    session_mode="reuse",
                    reusable_session_id=reusable.id,
                ),
                enforce_user_quota=False,
            )
            assert reuse.session.id == reusable.id, "reuse should use reusable_session_id when idle"
            assert reuse.created is True
            print(f"reuse  ok session={reuse.session.id} task={reuse.task.id} created={reuse.created}")
            await finish_task(db, reuse.task.id, reuse.session.id)

            pinned_result = await executor.run(
                AgentTriggerRunConfig(
                    **base,
                    prompt="pinned mode real verification",
                    idempotency_key=f"{STAMP}:pinned",
                    session_mode="pinned",
                    pinned_session_id=pinned.id,
                ),
                enforce_user_quota=False,
            )
            assert pinned_result.session.id == pinned.id, "pinned should use pinned_session_id"
            assert pinned_result.created is True
            print(
                f"pinned ok session={pinned_result.session.id} "
                f"task={pinned_result.task.id} created={pinned_result.created}"
            )
            await finish_task(db, pinned_result.task.id, pinned_result.session.id)

            print("PASS real DB AgentTriggerExecutor session_mode fresh/reuse/pinned")
        finally:
            await cleanup(db, agent.id)
            await verify_remaining_clean(db, agent.id)


if __name__ == "__main__":
    asyncio.run(main())
