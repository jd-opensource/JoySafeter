from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Body, Depends, Header, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_api.api.v1.id_helpers import parse_trigger_id
from app.joysafeter_domain.schemas.joysafeter_trigger import TriggerCreateRequest, TriggerFireResponse, TriggerResponse, TriggerUpdateRequest
from app.joysafeter_domain.schemas.joysafeter_schedule import ScheduleRunResponse
from app.joysafeter_domain.services.agent_trigger_execution import AgentTriggerExecutor, AgentTriggerRunConfig, render_prompt_template
from app.joysafeter_domain.services.joysafeter_schedule_service import JoySafeterScheduleService
from app.joysafeter_domain.services.joysafeter_trigger_service import JoySafeterTriggerService
from app.joysafeter_shared.common.app_errors import NotFoundError, RequestValidationAppError, ResourceConflictError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, get_joysafeter_auth_context, require_joysafeter_write
from app.joysafeter_shared.database import get_db

router = APIRouter(tags=["joysafeter-triggers"])


def _webhook_url(request: Request, trigger_id: uuid.UUID) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/v1/triggers/trig_{trigger_id}/webhook"


def _response(trigger, request: Request) -> TriggerResponse:
    data = TriggerResponse.model_validate(trigger)
    data.webhook_url = _webhook_url(request, trigger.id)
    return data


@router.post("", status_code=201, response_model=TriggerResponse)
async def create_trigger(
    request: Request,
    body: TriggerCreateRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> TriggerResponse:
    svc = JoySafeterTriggerService(db)
    if await svc.get_by_name(body.name, auth_ctx.project_id) is not None:
        raise ResourceConflictError(
            code="TRIGGER_NAME_EXISTS",
            message=f"A trigger named '{body.name}' already exists in this project",
            data={"name": body.name},
            user_action="fix_input",
        )
    trigger = await svc.create(
        name=body.name,
        type=body.type,
        agent_id=body.agent_id,
        prompt_template=body.prompt_template,
        system_prompt=body.system_prompt,
        environment_ref=body.environment_ref,
        description=body.description,
        enabled=body.enabled,
        session_mode=body.session_mode,
        pinned_session_id=body.pinned_session_id,
        filter=body.filter,
        timeout_sec=body.timeout_sec,
        max_retries=body.max_retries,
        cron_expr=body.cron_expr,
        timezone=body.timezone,
        concurrency_policy=body.concurrency_policy,
        secret_ref=body.secret_ref,
        secret_key=body.secret_key,
        auth_methods=body.auth_methods,
        dedupe_header=body.dedupe_header,
        project_id=auth_ctx.project_id,
        user_id=auth_ctx.user_id,
        org_id=auth_ctx.org_id,
    )
    return _response(trigger, request)


@router.get("", response_model=List[TriggerResponse])
async def list_triggers(
    request: Request,
    enabled: bool | None = Query(None),
    type: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> List[TriggerResponse]:
    triggers = await JoySafeterTriggerService(db).list(project_id=auth_ctx.project_id, enabled=enabled, type=type, limit=limit, offset=offset)
    return [_response(trigger, request) for trigger in triggers]


async def _get_or_404(db: AsyncSession, trigger_id: uuid.UUID, project_id: Optional[str]):
    trigger = await JoySafeterTriggerService(db).get(trigger_id, project_id=project_id)
    if trigger is None:
        raise NotFoundError(
            code="TRIGGER_NOT_FOUND",
            message="Trigger not found",
            data={"trigger_id": str(trigger_id)},
            user_action="refresh",
        )
    return trigger


@router.get("/{trigger_id}", response_model=TriggerResponse)
async def get_trigger(
    request: Request,
    trigger_id: uuid.UUID = Depends(parse_trigger_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> TriggerResponse:
    return _response(await _get_or_404(db, trigger_id, auth_ctx.project_id), request)


@router.patch("/{trigger_id}", response_model=TriggerResponse)
async def update_trigger(
    request: Request,
    trigger_id: uuid.UUID = Depends(parse_trigger_id),
    body: TriggerUpdateRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> TriggerResponse:
    svc = JoySafeterTriggerService(db)
    trigger = await _get_or_404(db, trigger_id, auth_ctx.project_id)
    fields = body.model_dump(exclude_unset=True)
    if "name" in fields and fields["name"] != trigger.name:
        existing = await svc.get_by_name(fields["name"], auth_ctx.project_id)
        if existing is not None and existing.id != trigger_id:
            raise ResourceConflictError(
                code="TRIGGER_NAME_EXISTS",
                message=f"A trigger named '{fields['name']}' already exists in this project",
                data={"name": fields["name"]},
                user_action="fix_input",
            )
    updated = await svc.update(trigger_id, auth_ctx.project_id, **fields)
    return _response(updated, request)


@router.delete("/{trigger_id}", status_code=204)
async def delete_trigger(
    trigger_id: uuid.UUID = Depends(parse_trigger_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> None:
    await _get_or_404(db, trigger_id, auth_ctx.project_id)
    await JoySafeterTriggerService(db).delete(trigger_id, auth_ctx.project_id)


@router.post("/{trigger_id}/run", status_code=202, response_model=TriggerFireResponse)
async def run_trigger_now(
    trigger_id: uuid.UUID = Depends(parse_trigger_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> TriggerFireResponse:
    trigger = await _get_or_404(db, trigger_id, auth_ctx.project_id)
    agent, environment_ref = await JoySafeterScheduleService(db).resolve_runnable_target(
        agent_id=trigger.agent_id,
        project_id=trigger.project_id,
        environment_ref=trigger.environment_ref,
    )
    now = datetime.now(timezone.utc)
    payload = {
        "trigger": {
            "id": str(trigger.id),
            "name": trigger.name,
            "type": "manual",
            "source_type": trigger.type,
            "fired_at": now.isoformat(),
        },
        "schedule": {
            "id": str(trigger.id),
            "name": trigger.name,
            "cron_expr": trigger.cron_expr,
            "timezone": trigger.timezone,
            "fired_at": now.isoformat(),
            "last_fired_slot": trigger.last_fired_slot.isoformat() if trigger.last_fired_slot else None,
        },
    }
    result = await AgentTriggerExecutor(db).run(
        AgentTriggerRunConfig(
            agent=agent,
            name=trigger.name,
            source=f"trigger:manual:{trigger.id}",
            prompt=render_prompt_template(trigger.prompt_template, payload),
            system_prompt=trigger.system_prompt,
            environment_ref=environment_ref,
            timeout_sec=trigger.timeout_sec,
            max_retries=trigger.max_retries,
            project_id=trigger.project_id,
            user_id=trigger.user_id,
            org_id=trigger.org_id,
            idempotency_key=f"trigger:{trigger.id}:manual:{uuid.uuid4().hex}",
            session_mode=trigger.session_mode,
            pinned_session_id=trigger.pinned_session_id,
            reusable_session_id=trigger.reusable_session_id,
            schedule_id=trigger.id,
            metadata={"trigger_id": str(trigger.id), "trigger_type": "manual", "source_trigger_type": trigger.type},
        ),
        enforce_user_quota=True,
    )
    await JoySafeterTriggerService(db).mark_attempt(
        trigger,
        success=True,
        task_id=result.task.id,
        session_id=result.session.id,
        payload=payload,
    )
    return TriggerFireResponse(status=result.task.status, task_id=f"task_{result.task.id}", session_id=f"sess_{result.session.id}")


@router.get("/{trigger_id}/runs", response_model=List[ScheduleRunResponse])
async def list_trigger_runs(
    trigger_id: uuid.UUID = Depends(parse_trigger_id),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> List[ScheduleRunResponse]:
    runs = await JoySafeterTriggerService(db).list_runs(
        trigger_id,
        project_id=auth_ctx.project_id,
        limit=limit,
        offset=offset,
    )
    if runs is None:
        raise NotFoundError(code="TRIGGER_NOT_FOUND", message="Trigger not found", data={"trigger_id": str(trigger_id)}, user_action="refresh")
    return [ScheduleRunResponse.model_validate(task) for task in runs]


@router.post("/{trigger_id}/webhook", status_code=202, response_model=TriggerFireResponse)
async def fire_webhook_trigger(
    request: Request,
    trigger_id: uuid.UUID = Depends(parse_trigger_id),
    x_joysafeter_signature: Optional[str] = Header(None),
    x_hub_signature_256: Optional[str] = Header(None),
    x_joysafeter_token: Optional[str] = Header(None),
    x_joysafeter_delivery_id: Optional[str] = Header(None),
    x_github_delivery: Optional[str] = Header(None),
    x_request_id: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> TriggerFireResponse:
    svc = JoySafeterTriggerService(db)
    trigger = await svc.get(trigger_id)
    if trigger is None or trigger.type != "webhook":
        raise NotFoundError(code="TRIGGER_NOT_FOUND", message="Trigger not found", data={"trigger_id": str(trigger_id)}, user_action="refresh")
    raw_body = await request.body()
    signature = x_joysafeter_signature or x_hub_signature_256
    token = x_joysafeter_token
    if not token and authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer":
            token = value.strip()
    authed = await svc.verify_webhook_auth(trigger, raw_body, signature, token)
    if not authed:
        raise RequestValidationAppError(
            code="TRIGGER_WEBHOOK_UNAUTHORIZED",
            message="Invalid webhook signature or token",
            data={},
            user_action="fix_input",
        )
    try:
        body: Any = json.loads(raw_body.decode("utf-8")) if raw_body.strip() else {}
    except Exception:
        body = {"raw": raw_body.decode("utf-8", errors="replace")}
    payload = {
        "body": body,
        "headers": {
            "content_type": request.headers.get("content-type"),
            "user_agent": request.headers.get("user-agent"),
            "forwarded_for": request.headers.get("x-forwarded-for"),
        },
        "trigger": {"id": str(trigger.id), "name": trigger.name, "type": trigger.type},
    }
    status, task, session_id, deduped, reason = await svc.fire_webhook(
        trigger,
        raw_body=raw_body,
        payload=payload,
        delivery_id=x_joysafeter_delivery_id or x_github_delivery or x_request_id,
        auth_fingerprint=signature or token or "",
    )
    return TriggerFireResponse(status=status, task_id=task.id if task else None, session_id=session_id, reason=reason, deduped=deduped)
