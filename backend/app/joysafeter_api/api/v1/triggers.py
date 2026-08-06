from __future__ import annotations

import json
import uuid
from typing import Any, List, Optional

from fastapi import APIRouter, Body, Depends, Header, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_api.api.v1.id_helpers import parse_task_after_id, parse_trigger_id
from app.joysafeter_domain.schemas.base import CursorPaginatedResponse as PaginatedResponse
from app.joysafeter_domain.schemas.joysafeter_trigger import (
    TriggerCreateRequest,
    TriggerFireResponse,
    TriggerResponse,
    TriggerRunResponse,
    TriggerUpdateRequest,
)
from app.joysafeter_domain.services.joysafeter_trigger_service import JoySafeterTriggerService
from app.joysafeter_shared.common.app_errors import NotFoundError, RequestValidationAppError
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    get_joysafeter_auth_context,
    require_joysafeter_write,
)
from app.joysafeter_shared.database import get_db
from app.joysafeter_shared.ids import SessionId
from app.joysafeter_shared.rate_limit import get_client_ip, rate_limit
from app.joysafeter_shared.utils.id_utils import format_task_id

router = APIRouter(tags=["joysafeter-triggers"])


def _webhook_url(request: Request, trigger_id: uuid.UUID) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/v1/triggers/trig_{trigger_id}/webhook"


def _response(trigger, request: Request) -> TriggerResponse:
    data = TriggerResponse.model_validate(trigger)
    # Only webhook triggers have an ingress URL; cron triggers are worker-fired.
    data.webhook_url = _webhook_url(request, trigger.id) if trigger.type == "webhook" else None
    return data


def _webhook_rate_limit_key(request: Request) -> str:
    trigger_id = request.path_params.get("trigger_id") or "unknown"
    return f"rate_limit:webhook:{trigger_id}:{get_client_ip(request)}"


def _webhook_delivery_id(
    request: Request,
    trigger,
    *,
    fallback_delivery_id: Optional[str],
    github_delivery_id: Optional[str],
    request_id: Optional[str],
) -> Optional[str]:
    configured_header = ((trigger.config or {}).get("dedupe_header") or "").strip()
    if configured_header:
        configured_value = request.headers.get(configured_header)
        if configured_value:
            return configured_value
    # ``X-Request-ID`` is a transport correlation id, not a provider delivery
    # identity. Gateways often mint a fresh value for each retry; using it here
    # would bypass the service's body-hash fallback and duplicate deliveries.
    _ = request_id
    return fallback_delivery_id or github_delivery_id


_WEBHOOK_SECRET_RESOLUTION_ERROR_CODES = frozenset(
    {
        "TRIGGER_SECRET_REF_REQUIRED",
        "TRIGGER_SECRET_NOT_FOUND",
        "TRIGGER_SECRET_KEY_NOT_FOUND",
    }
)


def _webhook_unauthorized() -> RequestValidationAppError:
    return RequestValidationAppError(
        code="TRIGGER_WEBHOOK_UNAUTHORIZED",
        message="Invalid webhook signature or token",
        data={},
        user_action="fix_input",
    )


@router.post("", status_code=201, response_model=TriggerResponse)
async def create_trigger(
    request: Request,
    body: TriggerCreateRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> TriggerResponse:
    svc = JoySafeterTriggerService(db)
    trigger = await svc.create(
        name=body.name,
        type=body.type,
        agent_id=body.agent_id,
        prompt_template=body.prompt_template,
        environment_ref=body.environment_ref,
        description=body.description,
        enabled=body.enabled,
        session_mode=body.session_mode,
        pinned_session_id=body.pinned_session_id,
        session_key=body.session_key,
        filter=body.filter,
        timeout_sec=body.timeout_sec,
        max_retries=body.max_retries,
        cron_expr=body.cron_expr,
        timezone=body.timezone,
        run_at=body.run_at,
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
    triggers = await JoySafeterTriggerService(db).list(
        project_id=auth_ctx.project_id, enabled=enabled, type=type, limit=limit, offset=offset
    )
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
    fields = body.model_dump(exclude_unset=True)
    updated = await svc.update(trigger_id, auth_ctx.project_id, **fields)
    if updated is None:
        raise NotFoundError(
            code="TRIGGER_NOT_FOUND",
            message="Trigger not found",
            data={"trigger_id": str(trigger_id)},
            user_action="refresh",
        )
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
    idempotency_key_header: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> TriggerFireResponse:
    trigger = await _get_or_404(db, trigger_id, auth_ctx.project_id)
    status, task, session_id, deduped, reason = await JoySafeterTriggerService(db).fire_manual(
        trigger,
        idempotency_header=idempotency_key_header,
    )
    return TriggerFireResponse(
        status=status,
        task_id=f"task_{task.id}" if task is not None else None,
        session_id=str(SessionId(session_id)) if session_id is not None else None,
        deduped=deduped,
        reason=reason,
    )


@router.get("/{trigger_id}/runs", response_model=PaginatedResponse[TriggerRunResponse])
async def list_trigger_runs(
    trigger_id: uuid.UUID = Depends(parse_trigger_id),
    limit: int = Query(50, ge=1, le=500),
    after_id: Optional[uuid.UUID] = Depends(parse_task_after_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> PaginatedResponse[TriggerRunResponse]:
    page = await JoySafeterTriggerService(db).list_runs_page(
        trigger_id,
        project_id=auth_ctx.project_id,
        limit=limit,
        after_id=after_id,
    )
    if page is None:
        raise NotFoundError(
            code="TRIGGER_NOT_FOUND",
            message="Trigger not found",
            data={"trigger_id": str(trigger_id)},
            user_action="refresh",
        )
    runs, has_more = page
    data = [TriggerRunResponse.model_validate(task) for task in runs]
    return PaginatedResponse(
        data=data,
        has_more=has_more,
        first_id=format_task_id(data[0].id) if data else None,
        last_id=format_task_id(data[-1].id) if data else None,
    )


@router.post("/{trigger_id}/webhook", status_code=202, response_model=TriggerFireResponse)
@rate_limit(max_requests=60, window_seconds=60, key_func=_webhook_rate_limit_key)
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
        raise NotFoundError(
            code="TRIGGER_NOT_FOUND",
            message="Trigger not found",
            data={"trigger_id": str(trigger_id)},
            user_action="refresh",
        )
    raw_body = await request.body()
    signature = x_joysafeter_signature or x_hub_signature_256
    token = x_joysafeter_token
    if not token and authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer":
            token = value.strip()
    try:
        authed = await svc.verify_webhook_auth(trigger, raw_body, signature, token)
    except (NotFoundError, RequestValidationAppError) as exc:
        if exc.code in _WEBHOOK_SECRET_RESOLUTION_ERROR_CODES:
            raise _webhook_unauthorized() from exc
        raise
    if not authed:
        raise _webhook_unauthorized()
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
        delivery_id=_webhook_delivery_id(
            request,
            trigger,
            fallback_delivery_id=x_joysafeter_delivery_id,
            github_delivery_id=x_github_delivery,
            request_id=x_request_id,
        ),
        auth_fingerprint=signature or token or "",
    )
    return TriggerFireResponse(
        status=status,
        task_id=(f"task_{task.id}" if task else None),
        session_id=(str(SessionId(session_id)) if session_id else None),
        reason=reason,
        deduped=deduped,
    )


@router.post("/{trigger_id}/test", status_code=202, response_model=TriggerFireResponse)
async def test_fire_webhook_trigger(
    request: Request,
    trigger_id: uuid.UUID = Depends(parse_trigger_id),
    body: dict[str, Any] = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> TriggerFireResponse:
    """Owner-authenticated test fire of a webhook trigger (no signature needed).

    Synthesizes a delivery from the supplied sample body and fires through the
    real webhook path with a unique delivery id (so it always fires, never
    dedups) — including for a disabled trigger, so it can be validated before
    going live.
    """
    trigger = await _get_or_404(db, trigger_id, auth_ctx.project_id)
    if trigger.type != "webhook":
        raise RequestValidationAppError(
            code="TRIGGER_NOT_WEBHOOK",
            message="Test fire is only available for webhook triggers",
            data={"trigger_id": str(trigger_id), "type": trigger.type},
            user_action="fix_input",
        )
    sample_body = body or {"test": True}
    raw_body = json.dumps(sample_body).encode("utf-8")
    payload = {
        "body": sample_body,
        "headers": {"content_type": "application/json", "user_agent": "joysafeter-test", "forwarded_for": None},
        "trigger": {"id": str(trigger.id), "name": trigger.name, "type": "webhook", "test": True},
    }
    status, task, session_id, deduped, reason = await JoySafeterTriggerService(db).fire_webhook(
        trigger,
        raw_body=raw_body,
        payload=payload,
        delivery_id=f"test:{uuid.uuid4().hex}",
        auth_fingerprint="test",
        ignore_enabled=True,
    )
    return TriggerFireResponse(
        status=status,
        task_id=(f"task_{task.id}" if task else None),
        session_id=(str(SessionId(session_id)) if session_id else None),
        reason=reason,
        deduped=deduped,
    )


@router.get("/{trigger_id}/webhook-sample")
async def webhook_sample(
    request: Request,
    trigger_id: uuid.UUID = Depends(parse_trigger_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> dict[str, Any]:
    """A copy-paste, correctly-signed ``curl`` for delivering to this webhook."""
    trigger = await _get_or_404(db, trigger_id, auth_ctx.project_id)
    if trigger.type != "webhook":
        raise RequestValidationAppError(
            code="TRIGGER_NOT_WEBHOOK",
            message="Webhook sample is only available for webhook triggers",
            data={"trigger_id": str(trigger_id), "type": trigger.type},
            user_action="fix_input",
        )
    url = _webhook_url(request, trigger.id)
    sample_body = {"example": "payload"}
    curl = await JoySafeterTriggerService(db).build_webhook_curl(trigger, url=url, sample_body=sample_body)
    return {
        "url": url,
        "signature_header": "X-JoySafeter-Signature",
        "sample_body": sample_body,
        "curl": curl,
    }
