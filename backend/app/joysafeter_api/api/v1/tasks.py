import asyncio
import hashlib
import json
import logging
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_api.api.v1.id_helpers import parse_task_after_id, parse_task_id
from app.joysafeter_domain.schemas.base import CursorPaginatedResponse as PaginatedResponse
from app.joysafeter_domain.schemas.joysafeter_task import JoySafeterCreateTaskRequest as CreateTaskRequest
from app.joysafeter_domain.schemas.joysafeter_task import JoySafeterCreateTaskResponse as CreateTaskResponse
from app.joysafeter_domain.schemas.joysafeter_task import JoySafeterTaskResponse as TaskResponse
from app.joysafeter_domain.services.joysafeter_agent_service import JoySafeterAgentService as AgentService
from app.joysafeter_domain.services.joysafeter_environment_service import EnvironmentService
from app.joysafeter_domain.services.joysafeter_session_service import SessionService
from app.joysafeter_domain.services.joysafeter_task_service import JoySafeterTaskService as TaskService
from app.joysafeter_shared.common.app_errors import (
    AppError,
    InvalidRequestError,
    NotFoundError,
    RequestValidationAppError,
    ResourceConflictError,
    ServiceUnavailableError,
)
from app.joysafeter_shared.common.async_boundaries import async_boundary_error_payload
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    get_joysafeter_auth_context,
    require_joysafeter_write,
)
from app.joysafeter_shared.common.stream_errors import async_error_payload
from app.joysafeter_shared.database import get_db
from app.joysafeter_shared.utils.id_utils import format_session_id, format_task_id, same_id

logger = logging.getLogger(__name__)

router = APIRouter(tags=["joysafeter-tasks"])

# When a client omits Idempotency-Key we still derive a fallback key, scoped to a
# short time window, so that an accidental double-submit (double-click, proxy or
# network retry) collapses to a single task instead of firing the tooling twice.
# A deliberate re-run in a later window hashes differently and creates a fresh
# task, so intentional repeats are never silently swallowed.
_AUTO_IDEMPOTENCY_WINDOW_SECONDS = 10


def _auto_idempotency_window_bucket() -> int:
    return int(time.time()) // _AUTO_IDEMPOTENCY_WINDOW_SECONDS


def _derive_auto_idempotency_key(req: CreateTaskRequest, auth_ctx: JoySafeterAuthContext) -> str:
    """Deterministic fallback idempotency key for submissions with no client key.

    The key covers the fields that define "the same submission" (so a different
    prompt/session/environment produces a different key and a distinct task) plus
    a coarse time-window bucket (so identical submits collapse only when they are
    near-simultaneous).
    """
    identity = "\x1f".join(
        [
            "auto",
            str(auth_ctx.user_id or ""),
            str(req.agent_id or ""),
            str(req.agent_name or ""),
            req.prompt or "",
            req.system or "",
            str(req.chat_session_id or ""),
            str(req.environment_ref or ""),
            str(_auto_idempotency_window_bucket()),
        ]
    )
    return "auto:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _task_idempotency_conflict_error(
    *,
    existing,
    field: str,
    message: str,
    requested_value: object | None = None,
    existing_value: object | None = None,
) -> AppError:
    data = {
        "task_id": format_task_id(existing.id),
        "conflict_field": field,
    }
    if requested_value is not None:
        data["requested_value"] = str(requested_value)
    if existing_value is not None:
        data["existing_value"] = str(existing_value)
    return ResourceConflictError(
        code="TASK_IDEMPOTENCY_KEY_MISMATCH",
        message=message,
        data=data,
        user_action="fix_input",
    )


def _task_cancel_conflict_error(task_id: uuid.UUID, exc: ValueError) -> AppError:
    message = str(exc)
    data: dict[str, object] = {"task_id": format_task_id(task_id)}
    prefix = "Task already in terminal state: "
    if message.startswith(prefix):
        data["task_status"] = message.removeprefix(prefix)
        return ResourceConflictError(
            code="TASK_ALREADY_TERMINAL",
            message=message,
            data=data,
            user_action="refresh",
        )
    return ResourceConflictError(
        code="TASK_CANCEL_CONFLICT",
        message=message,
        data=data,
        user_action="refresh",
    )


def _task_enqueue_failed_error(*, task_id: uuid.UUID, session_id: uuid.UUID | None = None) -> AppError:
    data: dict[str, object] = {"task_id": format_task_id(task_id)}
    if session_id is not None:
        data["session_id"] = format_session_id(session_id)
    return ServiceUnavailableError(
        code="TASK_ENQUEUE_FAILED",
        message="Failed to enqueue task",
        data=data,
        source="runtime",
        retryable=True,
        user_action="retry",
    )


def _task_enqueue_failed_stop_reason(*, task_id: uuid.UUID, session_id: uuid.UUID | None = None) -> dict[str, object]:
    data: dict[str, object] = {"task_id": format_task_id(task_id)}
    if session_id is not None:
        data["session_id"] = format_session_id(session_id)
    return async_error_payload(
        code="TASK_ENQUEUE_FAILED",
        message="Failed to enqueue task",
        data=data,
        source="runtime",
        retryable=True,
        user_action="retry",
    )


def _task_stream_error_payload(
    *,
    code: str,
    message: str,
    task_id: uuid.UUID,
    source: str = "websocket",
    retryable: bool = False,
    user_action: str | None = None,
    data: dict[str, object] | None = None,
    detail: str | None = None,
) -> dict[str, object]:
    payload_data: dict[str, object] = {"task_id": format_task_id(task_id)}
    if data:
        payload_data.update(data)
    return async_error_payload(
        code=code,
        message=message,
        data=payload_data,
        source=source,
        retryable=retryable,
        user_action=user_action,
        detail=detail,
    )


async def _relay_task_cancel_to_orchestrator(task, db: AsyncSession, *, reason: str) -> bool:
    # Single-sourced with the scheduler's ``replace`` policy so the two cancel
    # paths can never drift. See TaskCancellationService for the invariant.
    from app.joysafeter_domain.services.task_cancellation_service import TaskCancellationService

    return await TaskCancellationService(db).relay_cancel(task, reason=reason)


def _validate_idempotent_task_replay(req: CreateTaskRequest, existing) -> None:
    if req.agent_id is not None and not same_id(existing.agent_id, req.agent_id):
        raise _task_idempotency_conflict_error(
            existing=existing,
            field="agent_id",
            message="Idempotency-Key was already used for a different agent",
            requested_value=req.agent_id,
            existing_value=existing.agent_id,
        )
    if req.chat_session_id is not None and not same_id(existing.chat_session_id, req.chat_session_id):
        raise _task_idempotency_conflict_error(
            existing=existing,
            field="chat_session_id",
            message="Idempotency-Key was already used for a different session",
            requested_value=req.chat_session_id,
            existing_value=existing.chat_session_id,
        )
    if existing.prompt != req.prompt:
        raise _task_idempotency_conflict_error(
            existing=existing,
            field="prompt",
            message="Idempotency-Key was already used for a different prompt",
            requested_value=req.prompt,
            existing_value=existing.prompt,
        )


async def _load_task_environment_or_raise(
    db: AsyncSession,
    environment_ref: str,
    project_id: Optional[str],
) -> Any:
    env = await EnvironmentService(db).get_environment_by_ref(environment_ref, project_id=project_id)
    if not env:
        raise RequestValidationAppError(
            code="TASK_ENVIRONMENT_NOT_FOUND",
            message=f"Environment not found: {environment_ref}",
            data={"environment_ref": environment_ref},
            user_action="fix_input",
        )
    if getattr(env, "archived_at", None) is not None:
        raise ResourceConflictError(
            code="ENVIRONMENT_ARCHIVED",
            message=f"Environment is archived: {environment_ref}",
            data={"environment_ref": environment_ref, "environment_id": str(env.id)},
            user_action="refresh",
        )
    return env


async def _validate_task_environment_matches_existing_session(
    *,
    db: AsyncSession,
    session,
    agent,
    requested_environment_ref: str,
    requested_environment,
    project_id: Optional[str],
) -> None:
    effective_ref = session.environment_ref or getattr(agent, "environment_ref", None)
    if effective_ref:
        effective_environment = await EnvironmentService(db).get_environment_by_ref(
            effective_ref, project_id=project_id
        )
        if effective_environment and same_id(effective_environment.id, requested_environment.id):
            return

    raise ResourceConflictError(
        code="TASK_SESSION_ENVIRONMENT_MISMATCH",
        message="Task environment_ref does not match the existing session environment",
        data={
            "session_id": str(session.id),
            "requested_environment_ref": requested_environment_ref,
            "session_environment_ref": effective_ref,
        },
        user_action="fix_input",
    )


async def _task_environment_refs_match_for_replay(
    db: AsyncSession,
    requested_environment_ref: str,
    effective_environment_ref: str | None,
    project_id: Optional[str],
) -> bool:
    if not effective_environment_ref:
        return False
    requested = requested_environment_ref.strip()
    effective = effective_environment_ref.strip()
    if requested == effective:
        return True

    env_svc = EnvironmentService(db)
    requested_env = await env_svc.get_environment_by_ref(requested, project_id=project_id)
    effective_env = await env_svc.get_environment_by_ref(effective, project_id=project_id)
    return bool(requested_env and effective_env and requested_env.id == effective_env.id)


async def _validate_idempotent_task_environment_replay(
    *,
    db: AsyncSession,
    req: CreateTaskRequest,
    existing,
    project_id: Optional[str],
) -> None:
    if not req.environment_ref:
        return

    effective_ref = None
    if existing.chat_session_id is not None:
        session = await SessionService(db).get_session(existing.chat_session_id, project_id=project_id)
        if session is not None:
            effective_ref = session.environment_ref
    if not effective_ref:
        agent = await AgentService(db).get_agent(existing.agent_id, project_id=project_id)
        effective_ref = getattr(agent, "environment_ref", None) if agent is not None else None
    if await _task_environment_refs_match_for_replay(db, req.environment_ref, effective_ref, project_id):
        return

    raise _task_idempotency_conflict_error(
        existing=existing,
        field="environment_ref",
        message="Idempotency-Key was already used for a different environment",
        requested_value=req.environment_ref,
        existing_value=effective_ref,
    )


@router.post("", status_code=202, response_model=CreateTaskResponse)
async def create_task(
    req: CreateTaskRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> CreateTaskResponse:
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        # No client-supplied key: derive a short-window fallback so an accidental
        # resubmit does not fire the same real task twice. Clients that need
        # guaranteed dedup across windows should still send an explicit key.
        idempotency_key = _derive_auto_idempotency_key(req, auth_ctx)
    else:
        idempotency_key = idempotency_key.strip()

    # Idempotent retry: if this key already produced a task, return it and skip
    # all side effects (session creation, enqueue). Clients should send a unique
    # key (e.g. a UUID) per logical submission.
    if idempotency_key:
        existing = await TaskService(db).get_by_idempotency_key(idempotency_key, project_id=auth_ctx.project_id)
        if existing is not None:
            _validate_idempotent_task_replay(req, existing)
            await _validate_idempotent_task_environment_replay(
                db=db,
                req=req,
                existing=existing,
                project_id=auth_ctx.project_id,
            )
            if existing.status == "failed" and "Failed to enqueue task" in (existing.error or ""):
                raise _task_enqueue_failed_error(task_id=existing.id, session_id=existing.chat_session_id)
            return CreateTaskResponse(id=existing.id, status=existing.status)

    agent_svc = AgentService(db)
    agent = None
    if req.agent_id:
        agent = await agent_svc.get_agent(req.agent_id, project_id=auth_ctx.project_id)
    elif req.agent_name:
        agent = await agent_svc.get_agent_by_name(req.agent_name, project_id=auth_ctx.project_id)
    if not agent:
        data: dict[str, object] = {}
        if req.agent_id is not None:
            data["agent_id"] = str(req.agent_id)
        if req.agent_name is not None:
            data["agent_name"] = req.agent_name
        raise NotFoundError(
            code="TASK_AGENT_NOT_FOUND",
            message="Agent not found",
            data=data,
            user_action="refresh",
        )
    if agent.archived_at is not None:
        raise ResourceConflictError(
            code="AGENT_ARCHIVED",
            message="Agent is archived and cannot create new tasks.",
            data={"agent_id": str(agent.id)},
            user_action="refresh",
        )

    requested_environment = None
    if req.environment_ref:
        requested_environment = await _load_task_environment_or_raise(db, req.environment_ref, auth_ctx.project_id)

    # Auto-create a ChatSession for the task if none provided
    chat_session_id = req.chat_session_id
    auto_created_session_id: uuid.UUID | None = None
    session_svc = None
    if not chat_session_id:
        environment_ref = req.environment_ref or getattr(agent, "environment_ref", None)
        effective_environment = requested_environment
        if environment_ref and requested_environment is None:
            effective_environment = await _load_task_environment_or_raise(db, environment_ref, auth_ctx.project_id)
        session_svc = SessionService(db)
        session = await session_svc.create_session(
            agent_id=agent.id,
            title=f"Task: {req.prompt[:80]}",
            environment_ref=environment_ref,
            agent_version=getattr(agent, "version", None),
            agent_snapshot=agent_svc.build_execution_snapshot(
                agent,
                environment=effective_environment,
                environment_ref=environment_ref,
            ),
            project_id=auth_ctx.project_id,
        )
        chat_session_id = session.id
        auto_created_session_id = session.id
    else:
        session_svc = SessionService(db)
        existing_session = await session_svc.get_session(chat_session_id, project_id=auth_ctx.project_id)
        if not existing_session:
            raise NotFoundError(
                code="TASK_SESSION_NOT_FOUND",
                message="Session not found",
                data={"session_id": str(chat_session_id)},
                user_action="refresh",
            )
        if not same_id(existing_session.agent_id, agent.id):
            raise InvalidRequestError(
                code="TASK_SESSION_AGENT_MISMATCH",
                message="Session does not belong to the selected agent",
                data={
                    "session_id": str(chat_session_id),
                    "session_agent_id": str(existing_session.agent_id),
                    "requested_agent_id": str(agent.id),
                },
                user_action="fix_input",
            )
        if req.environment_ref:
            assert requested_environment is not None
            await _validate_task_environment_matches_existing_session(
                db=db,
                session=existing_session,
                agent=agent,
                requested_environment_ref=req.environment_ref,
                requested_environment=requested_environment,
                project_id=auth_ctx.project_id,
            )
        else:
            effective_environment_ref = existing_session.environment_ref or getattr(agent, "environment_ref", None)
            if effective_environment_ref:
                await _load_task_environment_or_raise(db, effective_environment_ref, auth_ctx.project_id)
        if existing_session.archived_at:
            raise ResourceConflictError(
                code="SESSION_ARCHIVED",
                message="Session is archived",
                data={"session_id": str(chat_session_id)},
                user_action="fix_input",
            )
        if existing_session.status == "terminated":
            raise ResourceConflictError(
                code="SESSION_TERMINATED",
                message="Session is terminated",
                data={"session_id": str(chat_session_id), "session_status": existing_session.status},
                user_action="fix_input",
            )
        if existing_session.status == "rescheduling":
            raise ResourceConflictError(
                code="SESSION_RESCHEDULING",
                message="Session is rescheduling, try again later",
                data={"session_id": str(chat_session_id), "session_status": existing_session.status},
                retryable=True,
                user_action="retry",
            )
        if existing_session.status == "running":
            raise ResourceConflictError(
                code="SESSION_ALREADY_RUNNING",
                message="Session is already running; wait for completion before creating a new task",
                data={"session_id": str(chat_session_id), "session_status": existing_session.status},
                retryable=True,
                user_action="retry",
            )

        active_tasks = await TaskService(db).list_active_tasks_by_session(
            chat_session_id,
            project_id=auth_ctx.project_id,
        )
        if active_tasks:
            raise ResourceConflictError(
                code="SESSION_ACTIVE_TASK",
                message="Session has an active task; wait for completion before creating a new task",
                data={
                    "session_id": str(chat_session_id),
                    "active_task_ids": [format_task_id(active_task.id) for active_task in active_tasks],
                },
                retryable=True,
                user_action="retry",
            )

    assert session_svc is not None

    from app.joysafeter_domain.services.task_submission_service import TaskSubmissionService

    submission = TaskSubmissionService(db)
    task, _created = await submission.create_and_dispatch(
        agent_id=agent.id,
        prompt=req.prompt,
        system_prompt=req.system,
        chat_session_id=chat_session_id,
        session_svc=session_svc,
        timeout_sec=req.timeout_sec,
        max_retries=req.max_retries,
        project_id=auth_ctx.project_id,
        user_id=auth_ctx.user_id,
        org_id=auth_ctx.org_id,
        idempotency_key=idempotency_key,
        auto_created_session_id=auto_created_session_id,
        enforce_user_quota=auth_ctx.principal_type == "user",
    )
    return CreateTaskResponse(id=task.id, status=task.status)


@router.get("")
async def list_tasks(
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[uuid.UUID] = Depends(parse_task_after_id),
    agent_id: Optional[uuid.UUID] = Query(None),
    session_id: Optional[uuid.UUID] = Query(None),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> PaginatedResponse[TaskResponse]:
    svc = TaskService(db)
    tasks, has_more = await svc.list_tasks(
        limit=limit,
        after_id=after_id,
        agent_id=agent_id,
        session_id=session_id,
        status=status,
        project_id=auth_ctx.project_id,
    )
    data = [TaskResponse.model_validate(t) for t in tasks]
    return PaginatedResponse(
        data=data,
        has_more=has_more,
        first_id=format_task_id(data[0].id) if data else None,
        last_id=format_task_id(data[-1].id) if data else None,
    )


@router.get("/{task_id}")
async def get_task(
    task_id: uuid.UUID = Depends(parse_task_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> TaskResponse:
    svc = TaskService(db)
    task = await svc.get_task(task_id, project_id=auth_ctx.project_id)
    if not task:
        raise NotFoundError(
            code="TASK_NOT_FOUND",
            message="Task not found",
            data={"task_id": format_task_id(task_id)},
            user_action="refresh",
        )
    return TaskResponse.model_validate(task)


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: uuid.UUID = Depends(parse_task_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> dict:
    svc = TaskService(db)

    # Fetch task first (we need chat_session_id for post-cancel work)
    task = await svc.get_task(task_id, project_id=auth_ctx.project_id)
    if not task:
        raise NotFoundError(
            code="TASK_NOT_FOUND",
            message="Task not found",
            data={"task_id": format_task_id(task_id)},
            user_action="refresh",
        )

    from app.joysafeter_domain.services.task_cancellation_service import TaskCancellationService

    try:
        await TaskCancellationService(db).cancel(task, reason="Cancelled via API")
    except ValueError as e:
        raise _task_cancel_conflict_error(task_id, e) from e

    return {"id": format_task_id(task_id), "status": "cancelled"}


async def _authorize_task_stream(
    db: AsyncSession, *, user_id: str, org_id: str, project_id: str
) -> tuple[int, str] | None:
    """Authorize a task-stream subscription's principal against the project.

    Returns a ``(close_code, reason)`` to reject the socket with, or ``None`` when
    the caller may stream. This mirrors the HTTP read path exactly: the caller
    must be an active user, an org member, AND able to access the project — org
    super-users reach every project in the org, everyone else needs an explicit
    ProjectMember row. Checking only org membership (as an earlier version did)
    let any org member stream a project they had no grant on.
    """
    from sqlalchemy import select

    from app.joysafeter_domain.models.joysafeter_auth import AuthUser
    from app.joysafeter_domain.models.joysafeter_organization import Member
    from app.joysafeter_domain.services.joysafeter_project_service import ProjectService
    from app.joysafeter_shared.common.joysafeter_auth import JoySafeterRole

    user = (await db.execute(select(AuthUser).where(AuthUser.id == user_id))).scalar_one_or_none()
    if not user or not user.is_active:
        return (4001, "TASK_STREAM_AUTH_REQUIRED")

    member = (
        await db.execute(select(Member).where(Member.user_id == user_id, Member.organization_id == org_id).limit(1))
    ).scalar_one_or_none()
    if member is None:
        return (4003, "TASK_STREAM_PROJECT_ACCESS_DENIED")

    project = await ProjectService(db).get_accessible_project(
        project_id=project_id,
        org_id=org_id,
        user_id=user_id,
        org_role=JoySafeterRole.normalize(member.role),
        allow_archived=True,
    )
    if project is None:
        return (4003, "TASK_STREAM_PROJECT_ACCESS_DENIED")

    return None


@router.websocket("/{task_id}/stream")
async def task_stream(websocket: WebSocket, task_id: uuid.UUID = Depends(parse_task_id)):
    """WebSocket endpoint for real-time task output streaming."""
    from app.joysafeter_shared.common.cookie_auth import extract_token_from_cookies
    from app.joysafeter_shared.security import decode_token

    token = None
    try:
        token = extract_token_from_cookies(websocket.cookies)
    except Exception:
        token = None
    token = token or websocket.query_params.get("token")
    payload = decode_token(token) if token else None
    if not payload or payload.type != "access" or not payload.project_id or not payload.org_id:
        await websocket.close(code=4001, reason="TASK_STREAM_AUTH_REQUIRED")
        return

    from app.joysafeter_shared.database import AsyncSessionLocal

    async with AsyncSessionLocal() as auth_db:
        rejection = await _authorize_task_stream(
            auth_db,
            user_id=str(payload.sub),
            org_id=str(payload.org_id),
            project_id=str(payload.project_id),
        )
        if rejection is not None:
            code, reason = rejection
            await websocket.close(code=code, reason=reason)
            return

        auth_svc = TaskService(auth_db)
        auth_task = await auth_svc.get_task(task_id, project_id=payload.project_id)
        if not auth_task:
            await websocket.close(code=4004, reason="TASK_STREAM_TASK_NOT_FOUND")
            return

    await websocket.accept()
    from app.joysafeter_shared.cache.redis import RedisClient

    redis_client = RedisClient.get_client()
    if redis_client:
        await _stream_via_redis(websocket, task_id, redis_client)
    else:
        await websocket.send_json(
            _task_stream_error_payload(
                code="TASK_STREAM_REDIS_UNAVAILABLE",
                message="Task stream Redis fallback is unavailable",
                task_id=task_id,
                source="runtime",
                retryable=True,
                user_action="retry",
            )
        )
        try:
            await websocket.close()
        except Exception:
            pass


async def _stream_via_redis(websocket: WebSocket, task_id: uuid.UUID, redis_client):
    """Stream task events via Redis pub/sub (cross-instance fallback).

    Subscribes to the Redis channel first, then checks the DB for terminal
    state to avoid missing a completion event between the DB check in the
    caller and the subscribe call here.
    """
    channel = f"joysafeter:events:{task_id}"
    pubsub = redis_client.pubsub()
    try:
        await pubsub.subscribe(channel)

        # After subscribing, check if task already reached a terminal state.
        # Any completion event published concurrently will be caught by the
        # subscription, so there is no missed-message window.
        from app.joysafeter_shared.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            svc = TaskService(db)
            task = await svc.get_task(task_id)
            if task:
                from app.joysafeter_domain.models.joysafeter_task import JoySafeterTaskStatus as TaskStatus

                if TaskStatus(task.status).is_terminal():
                    await websocket.send_json(
                        {
                            "type": "complete",
                            "output": task.output,
                            "error": task.error,
                            "status": task.status,
                        }
                    )
                    return

        while True:
            try:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=30)
            except asyncio.CancelledError:
                break

            if msg and msg["type"] == "message":
                data = msg["data"]
                if isinstance(data, bytes):
                    data = data.decode()
                try:
                    event = json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    continue
                await websocket.send_json(event)
                if event.get("type") == "complete":
                    break
            else:
                # No message within timeout -- send keepalive ping
                await websocket.send_json({"type": "ping"})
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    except Exception as exc:
        logger.warning(
            "Redis task stream failed for task %s",
            task_id,
            extra={
                "error": async_boundary_error_payload(
                    code="TASK_STREAM_REDIS_FAILED",
                    message="Cross-instance task stream failed",
                    boundary="task_api",
                    operation="stream_task_events",
                    data={"task_id": format_task_id(task_id)},
                    detail=exc.__class__.__name__,
                )
            },
            exc_info=True,
        )
        try:
            await websocket.send_json(
                _task_stream_error_payload(
                    code="TASK_STREAM_REDIS_FAILED",
                    message="Cross-instance task stream failed",
                    task_id=task_id,
                    source="runtime",
                    retryable=True,
                    user_action="retry",
                    detail=exc.__class__.__name__,
                )
            )
        except Exception:
            logger.debug("Failed to send Redis task stream error for task %s", task_id, exc_info=True)
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
        except Exception:
            pass
        try:
            await websocket.close()
        except Exception:
            pass
