"""Schedules API — CRUD + enable/disable/trigger for cron schedules.

A schedule is a cron-driven trigger that submits an agent task at each fire time
through the shared ``TaskSubmissionService`` (the same path ``POST /tasks``
uses). Execution history is the task table itself, filtered by ``schedule_id``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_api.api.v1.id_helpers import parse_schedule_id
from app.joysafeter_domain.schemas.joysafeter_schedule import (
    ScheduleCreateRequest,
    ScheduleResponse,
    ScheduleRunResponse,
    ScheduleUpdateRequest,
    TriggerResponse,
)
from app.joysafeter_domain.services.agent_trigger_execution import AgentTriggerExecutor, AgentTriggerRunConfig, render_prompt_template
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.services.joysafeter_schedule_service import JoySafeterScheduleService
from app.joysafeter_domain.services.joysafeter_trigger_service import JoySafeterTriggerService
from app.joysafeter_shared.common.app_errors import NotFoundError, ResourceConflictError
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    get_joysafeter_auth_context,
    require_joysafeter_write,
)
from app.joysafeter_shared.database import get_db

router = APIRouter(tags=["joysafeter-schedules"])


def _schedule_response(trigger: JoySafeterTrigger) -> ScheduleResponse:
    return ScheduleResponse.model_validate(
        {
            "id": trigger.id,
            "name": trigger.name,
            "description": trigger.description,
            "agent_id": trigger.agent_id,
            "prompt": trigger.prompt_template,
            "system_prompt": trigger.system_prompt,
            "environment_ref": trigger.environment_ref,
            "cron_expr": trigger.cron_expr or "",
            "timezone": trigger.timezone or "UTC",
            "enabled": trigger.enabled,
            "concurrency_policy": trigger.concurrency_policy,
            "session_mode": trigger.session_mode,
            "pinned_session_id": trigger.pinned_session_id,
            "reusable_session_id": trigger.reusable_session_id,
            "timeout_sec": trigger.timeout_sec,
            "max_retries": trigger.max_retries,
            "next_run_at": trigger.next_run_at,
            "last_fired_slot": trigger.last_fired_slot,
            "last_attempt_at": trigger.last_attempt_at,
            "last_success_at": trigger.last_success_at,
            "last_error": trigger.last_error,
            "consecutive_failures": trigger.consecutive_failures,
            "last_task_id": trigger.last_task_id,
            "last_session_id": trigger.last_session_id,
            "last_payload": trigger.last_payload or {},
            "project_id": trigger.project_id,
            "created_at": trigger.created_at,
            "updated_at": trigger.updated_at,
        }
    )


def _trigger_update_fields(fields: dict) -> dict:
    mapped = dict(fields)
    if "prompt" in mapped:
        mapped["prompt_template"] = mapped.pop("prompt")
    return mapped


@router.post("", status_code=201, response_model=ScheduleResponse)
async def create_schedule(
    body: ScheduleCreateRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> ScheduleResponse:
    svc = JoySafeterTriggerService(db)
    if await svc.get_by_name(body.name, auth_ctx.project_id, type="cron") is not None:
        raise ResourceConflictError(
            code="SCHEDULE_NAME_EXISTS",
            message=f"A schedule named '{body.name}' already exists in this project",
            data={"name": body.name},
            user_action="fix_input",
        )

    schedule = await svc.create(
        name=body.name,
        type="cron",
        agent_id=body.agent_id,
        prompt_template=body.prompt,
        cron_expr=body.cron_expr,
        timezone=body.timezone,
        system_prompt=body.system_prompt,
        environment_ref=body.environment_ref,
        description=body.description,
        timeout_sec=body.timeout_sec,
        max_retries=body.max_retries,
        concurrency_policy=body.concurrency_policy,
        session_mode=body.session_mode,
        pinned_session_id=body.pinned_session_id,
        enabled=body.enabled,
        project_id=auth_ctx.project_id,
        user_id=auth_ctx.user_id,
        org_id=auth_ctx.org_id,
    )
    return _schedule_response(schedule)


@router.get("", response_model=List[ScheduleResponse])
async def list_schedules(
    enabled: bool | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> List[ScheduleResponse]:
    schedules = await JoySafeterTriggerService(db).list(
        project_id=auth_ctx.project_id, enabled=enabled, type="cron", limit=limit, offset=offset
    )
    return [_schedule_response(s) for s in schedules]


async def _get_or_404(db: AsyncSession, schedule_id: uuid.UUID, project_id):
    schedule = await JoySafeterTriggerService(db).get(schedule_id, project_id=project_id)
    if schedule is not None and schedule.type != "cron":
        schedule = None
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
    schedule_id: uuid.UUID = Depends(parse_schedule_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> ScheduleResponse:
    return _schedule_response(await _get_or_404(db, schedule_id, auth_ctx.project_id))


@router.patch("/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    schedule_id: uuid.UUID = Depends(parse_schedule_id),
    body: ScheduleUpdateRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> ScheduleResponse:
    svc = JoySafeterTriggerService(db)
    schedule = await _get_or_404(db, schedule_id, auth_ctx.project_id)
    fields = body.model_dump(exclude_unset=True)
    if "name" in fields and fields["name"] != schedule.name:
        existing = await svc.get_by_name(fields["name"], auth_ctx.project_id, type="cron")
        if existing is not None and existing.id != schedule_id:
            raise ResourceConflictError(
                code="SCHEDULE_NAME_EXISTS",
                message=f"A schedule named '{fields['name']}' already exists in this project",
                data={"name": fields["name"]},
                user_action="fix_input",
            )
    updated = await svc.update(schedule_id, auth_ctx.project_id, **_trigger_update_fields(fields))
    return _schedule_response(updated)


@router.delete("/{schedule_id}", status_code=204)
async def delete_schedule(
    schedule_id: uuid.UUID = Depends(parse_schedule_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> None:
    await _get_or_404(db, schedule_id, auth_ctx.project_id)
    await JoySafeterTriggerService(db).delete(schedule_id, project_id=auth_ctx.project_id)


@router.post("/{schedule_id}/enable", response_model=ScheduleResponse)
async def enable_schedule(
    schedule_id: uuid.UUID = Depends(parse_schedule_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> ScheduleResponse:
    await _get_or_404(db, schedule_id, auth_ctx.project_id)
    updated = await JoySafeterTriggerService(db).update(schedule_id, auth_ctx.project_id, enabled=True)
    return _schedule_response(updated)


@router.post("/{schedule_id}/disable", response_model=ScheduleResponse)
async def disable_schedule(
    schedule_id: uuid.UUID = Depends(parse_schedule_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> ScheduleResponse:
    await _get_or_404(db, schedule_id, auth_ctx.project_id)
    updated = await JoySafeterTriggerService(db).update(schedule_id, auth_ctx.project_id, enabled=False)
    return _schedule_response(updated)


@router.post("/{schedule_id}/trigger", status_code=202, response_model=TriggerResponse)
async def trigger_schedule(
    schedule_id: uuid.UUID = Depends(parse_schedule_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> TriggerResponse:
    """Fire a schedule once, immediately, regardless of its cron cadence.

    Concurrency policy is not applied (the caller explicitly asked to run). A
    unique manual idempotency key is used so each manual trigger is its own run.
    """
    schedule = await _get_or_404(db, schedule_id, auth_ctx.project_id)
    agent, environment_ref = await JoySafeterScheduleService(db).resolve_runnable_target(
        agent_id=schedule.agent_id,
        project_id=schedule.project_id,
        environment_ref=schedule.environment_ref,
    )
    now = datetime.now(timezone.utc)
    payload = {
        "schedule": {
            "id": str(schedule.id),
            "name": schedule.name,
            "cron_expr": schedule.cron_expr,
            "timezone": schedule.timezone,
            "fired_at": now.isoformat(),
            "last_fired_slot": schedule.last_fired_slot.isoformat() if schedule.last_fired_slot else None,
        },
        "trigger": {"type": "manual", "source": "schedule"},
    }
    result = await AgentTriggerExecutor(db).run(
        AgentTriggerRunConfig(
            agent=agent,
            name=schedule.name,
            source=f"schedule:{schedule.id}",
            prompt=render_prompt_template(schedule.prompt_template, payload),
            system_prompt=schedule.system_prompt,
            environment_ref=environment_ref,
            timeout_sec=schedule.timeout_sec,
            max_retries=schedule.max_retries,
            project_id=schedule.project_id,
            user_id=schedule.user_id,
            org_id=schedule.org_id,
            idempotency_key=f"sched:{schedule.id}:manual:{uuid.uuid4().hex}",
            session_mode=schedule.session_mode,
            pinned_session_id=schedule.pinned_session_id,
            reusable_session_id=schedule.reusable_session_id,
            schedule_id=schedule.id,
            metadata={"schedule_id": str(schedule.id), "trigger_type": "manual"},
        ),
        enforce_user_quota=True,
    )
    await JoySafeterTriggerService(db).mark_attempt(
        schedule,
        success=True,
        task_id=result.task.id,
        session_id=result.session.id,
        payload=payload,
    )
    return TriggerResponse(task_id=result.task.id, session_id=result.session.id, status=result.task.status)


@router.get("/{schedule_id}/runs", response_model=List[ScheduleRunResponse])
async def list_schedule_runs(
    schedule_id: uuid.UUID = Depends(parse_schedule_id),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> List[ScheduleRunResponse]:
    runs = await JoySafeterTriggerService(db).list_runs(
        schedule_id,
        project_id=auth_ctx.project_id,
        limit=limit,
        offset=offset,
    )
    if runs is None:
        raise NotFoundError(
            code="SCHEDULE_NOT_FOUND",
            message="Schedule not found",
            data={"schedule_id": str(schedule_id)},
            user_action="refresh",
        )
    return [ScheduleRunResponse.model_validate(t) for t in runs]
