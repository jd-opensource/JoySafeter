"""Schedules API — CRUD + enable/disable/trigger for cron schedules.

A schedule is a cron-driven trigger that submits an agent task at each fire time
through the shared ``TaskSubmissionService`` (the same path ``POST /tasks``
uses). Execution history is the task table itself, filtered by ``schedule_id``.
"""

from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask
from app.joysafeter_domain.schemas.joysafeter_schedule import (
    ScheduleCreateRequest,
    ScheduleResponse,
    ScheduleRunResponse,
    ScheduleUpdateRequest,
    TriggerResponse,
)
from app.joysafeter_domain.services.joysafeter_agent_service import JoySafeterAgentService
from app.joysafeter_domain.services.joysafeter_schedule_service import JoySafeterScheduleService
from app.joysafeter_domain.services.joysafeter_session_service import SessionService
from app.joysafeter_domain.services.task_submission_service import TaskSubmissionService
from app.joysafeter_shared.common.app_errors import NotFoundError, ResourceConflictError
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    get_joysafeter_auth_context,
    require_joysafeter_write,
)
from app.joysafeter_shared.database import get_db

router = APIRouter(tags=["joysafeter-schedules"])


async def _resolve_agent_or_raise(db: AsyncSession, agent_id: uuid.UUID, project_id):
    agent = await JoySafeterAgentService(db).get_agent(agent_id, project_id=project_id)
    if agent is None:
        raise NotFoundError(
            code="SCHEDULE_AGENT_NOT_FOUND",
            message="Agent not found",
            data={"agent_id": str(agent_id)},
            user_action="refresh",
        )
    if agent.archived_at is not None:
        raise ResourceConflictError(
            code="AGENT_ARCHIVED",
            message="Agent is archived and cannot create new scheduled runs.",
            data={"agent_id": str(agent_id)},
            user_action="refresh",
        )
    return agent


@router.post("", status_code=201, response_model=ScheduleResponse)
async def create_schedule(
    body: ScheduleCreateRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> ScheduleResponse:
    svc = JoySafeterScheduleService(db)
    if await svc.get_by_name(body.name, auth_ctx.project_id) is not None:
        raise ResourceConflictError(
            code="SCHEDULE_NAME_EXISTS",
            message=f"A schedule named '{body.name}' already exists in this project",
            data={"name": body.name},
            user_action="fix_input",
        )
    await _resolve_agent_or_raise(db, body.agent_id, auth_ctx.project_id)

    schedule = await svc.create(
        name=body.name,
        agent_id=body.agent_id,
        prompt=body.prompt,
        cron_expr=body.cron_expr,
        timezone=body.timezone,
        system_prompt=body.system_prompt,
        environment_ref=body.environment_ref,
        description=body.description,
        timeout_sec=body.timeout_sec,
        max_retries=body.max_retries,
        concurrency_policy=body.concurrency_policy,
        enabled=body.enabled,
        project_id=auth_ctx.project_id,
        user_id=auth_ctx.user_id,
        org_id=auth_ctx.org_id,
    )
    return ScheduleResponse.model_validate(schedule)


@router.get("", response_model=List[ScheduleResponse])
async def list_schedules(
    enabled: bool | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> List[ScheduleResponse]:
    schedules = await JoySafeterScheduleService(db).list(
        project_id=auth_ctx.project_id, enabled=enabled, limit=limit, offset=offset
    )
    return [ScheduleResponse.model_validate(s) for s in schedules]


async def _get_or_404(db: AsyncSession, schedule_id: uuid.UUID, project_id):
    schedule = await JoySafeterScheduleService(db).get(schedule_id, project_id=project_id)
    if schedule is None:
        raise NotFoundError(
            code="SCHEDULE_NOT_FOUND",
            message="Schedule not found",
            data={"schedule_id": str(schedule_id)},
            user_action="refresh",
        )
    return schedule


@router.get("/{schedule_id}", response_model=ScheduleResponse)
async def get_schedule(
    schedule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> ScheduleResponse:
    return ScheduleResponse.model_validate(await _get_or_404(db, schedule_id, auth_ctx.project_id))


@router.patch("/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    schedule_id: uuid.UUID,
    body: ScheduleUpdateRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> ScheduleResponse:
    await _get_or_404(db, schedule_id, auth_ctx.project_id)
    fields = body.model_dump(exclude_unset=True)
    updated = await JoySafeterScheduleService(db).update(schedule_id, auth_ctx.project_id, **fields)
    return ScheduleResponse.model_validate(updated)


@router.delete("/{schedule_id}", status_code=204)
async def delete_schedule(
    schedule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> None:
    await _get_or_404(db, schedule_id, auth_ctx.project_id)
    await JoySafeterScheduleService(db).delete(schedule_id, project_id=auth_ctx.project_id)


@router.post("/{schedule_id}/enable", response_model=ScheduleResponse)
async def enable_schedule(
    schedule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> ScheduleResponse:
    await _get_or_404(db, schedule_id, auth_ctx.project_id)
    updated = await JoySafeterScheduleService(db).update(schedule_id, auth_ctx.project_id, enabled=True)
    return ScheduleResponse.model_validate(updated)


@router.post("/{schedule_id}/disable", response_model=ScheduleResponse)
async def disable_schedule(
    schedule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> ScheduleResponse:
    await _get_or_404(db, schedule_id, auth_ctx.project_id)
    updated = await JoySafeterScheduleService(db).update(schedule_id, auth_ctx.project_id, enabled=False)
    return ScheduleResponse.model_validate(updated)


@router.post("/{schedule_id}/trigger", status_code=202, response_model=TriggerResponse)
async def trigger_schedule(
    schedule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> TriggerResponse:
    """Fire a schedule once, immediately, regardless of its cron cadence.

    Concurrency policy is not applied (the caller explicitly asked to run). A
    unique manual idempotency key is used so each manual trigger is its own run.
    """
    schedule = await _get_or_404(db, schedule_id, auth_ctx.project_id)
    agent = await _resolve_agent_or_raise(db, schedule.agent_id, schedule.project_id)

    submission = TaskSubmissionService(db)
    await submission.enforce_admission(
        project_id=schedule.project_id,
        user_id=schedule.user_id,
        enforce_user_quota=False,
    )

    environment_ref = schedule.environment_ref or getattr(agent, "environment_ref", None)
    session_svc = SessionService(db)
    session = await session_svc.create_session(
        agent_id=agent.id,
        title=f"Scheduled (manual): {schedule.name}",
        environment_ref=environment_ref,
        agent_version=getattr(agent, "version", None),
        agent_snapshot={"name": agent.name, "model": getattr(agent, "model", None)},
        project_id=schedule.project_id,
    )
    task, _created = await submission.create_and_dispatch(
        agent_id=agent.id,
        prompt=schedule.prompt,
        system_prompt=schedule.system_prompt,
        chat_session_id=session.id,
        session_svc=session_svc,
        timeout_sec=schedule.timeout_sec,
        max_retries=schedule.max_retries,
        project_id=schedule.project_id,
        user_id=schedule.user_id,
        org_id=schedule.org_id,
        idempotency_key=f"sched:{schedule.id}:manual:{uuid.uuid4().hex}",
        schedule_id=schedule.id,
        auto_created_session_id=session.id,
    )
    return TriggerResponse(task_id=task.id, session_id=session.id, status=task.status)


@router.get("/{schedule_id}/runs", response_model=List[ScheduleRunResponse])
async def list_schedule_runs(
    schedule_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> List[ScheduleRunResponse]:
    await _get_or_404(db, schedule_id, auth_ctx.project_id)
    result = await db.execute(
        select(JoySafeterTask)
        .where(JoySafeterTask.schedule_id == schedule_id)
        .order_by(JoySafeterTask.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [ScheduleRunResponse.model_validate(t) for t in result.scalars().all()]
