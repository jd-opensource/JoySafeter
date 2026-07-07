import asyncio
import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_api.services import JoySafeterAgentService as AgentService
from app.joysafeter_api.services import JoySafeterTaskService as TaskService
from app.joysafeter_api.services import enqueue_joysafeter_task
from app.joysafeter_domain.schemas.base import CursorPaginatedResponse as PaginatedResponse
from app.joysafeter_domain.schemas.joysafeter_task import JoySafeterCreateTaskRequest as CreateTaskRequest
from app.joysafeter_domain.schemas.joysafeter_task import JoySafeterCreateTaskResponse as CreateTaskResponse
from app.joysafeter_domain.schemas.joysafeter_task import JoySafeterTaskResponse as TaskResponse
from app.joysafeter_shared.common.app_errors import (
    AppError,
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    RateLimitExceededError,
    RequestValidationAppError,
    ResourceConflictError,
    ServiceUnavailableError,
)
from app.joysafeter_shared.common.async_boundaries import async_boundary_error_payload
from app.joysafeter_shared.common.boundary_errors import log_boundary_failure
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    get_joysafeter_auth_context,
    require_joysafeter_write,
)
from app.joysafeter_shared.common.stream_errors import async_error_payload
from app.joysafeter_shared.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["joysafeter-tasks"])


def _raise_task_limit_exceeded(
    *,
    code: str,
    message: str,
    data: dict,
) -> None:
    raise RateLimitExceededError(
        code=code,
        message=message,
        data=data,
        source="api",
        retryable=True,
        user_action="retry",
    )


def _task_idempotency_conflict_error(
    *,
    existing,
    field: str,
    message: str,
    requested_value: object | None = None,
    existing_value: object | None = None,
) -> AppError:
    data = {
        "task_id": str(existing.id),
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
    data: dict[str, object] = {"task_id": str(task_id)}
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
    data: dict[str, object] = {"task_id": str(task_id)}
    if session_id is not None:
        data["session_id"] = str(session_id)
    return ServiceUnavailableError(
        code="TASK_ENQUEUE_FAILED",
        message="Failed to enqueue task",
        data=data,
        source="runtime",
        retryable=True,
        user_action="retry",
    )


def _task_enqueue_failed_stop_reason(*, task_id: uuid.UUID, session_id: uuid.UUID | None = None) -> dict[str, object]:
    data: dict[str, object] = {"task_id": str(task_id)}
    if session_id is not None:
        data["session_id"] = str(session_id)
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
    payload_data: dict[str, object] = {"task_id": str(task_id)}
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


def _validate_idempotent_task_replay(req: CreateTaskRequest, existing) -> None:
    if req.agent_id is not None and existing.agent_id != req.agent_id:
        raise _task_idempotency_conflict_error(
            existing=existing,
            field="agent_id",
            message="Idempotency-Key was already used for a different agent",
            requested_value=req.agent_id,
            existing_value=existing.agent_id,
        )
    if req.chat_session_id is not None and existing.chat_session_id != req.chat_session_id:
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


@router.post("", status_code=202, response_model=CreateTaskResponse)
async def create_task(
    req: CreateTaskRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> CreateTaskResponse:
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        idempotency_key = None
    else:
        idempotency_key = idempotency_key.strip()

    # Idempotent retry: if this key already produced a task, return it and skip
    # all side effects (session creation, enqueue). Clients should send a unique
    # key (e.g. a UUID) per logical submission.
    if idempotency_key:
        existing = await TaskService(db).get_by_idempotency_key(idempotency_key, project_id=auth_ctx.project_id)
        if existing is not None:
            _validate_idempotent_task_replay(req, existing)
            if existing.status == "failed" and "Failed to enqueue task" in (existing.error or ""):
                raise _task_enqueue_failed_error(task_id=existing.id, session_id=existing.chat_session_id)
            return CreateTaskResponse(id=existing.id, status=existing.status)

    # Per-project admission control (tenancy). The project is the tenant
    # boundary; a single tenant must not occupy unbounded fleet capacity. Placed
    # AFTER the idempotency short-circuit so a retry of an already-created task
    # is never rejected. This is a soft limit: count-then-create can slightly
    # over-admit under concurrent submits, which is acceptable for a fairness
    # quota (unlike idempotency, which must be strict).
    if auth_ctx.project_id is not None:
        from app.joysafeter_shared.config.settings import settings

        admission_svc = TaskService(db)
        limit = await admission_svc.resolve_project_task_limit(
            auth_ctx.project_id, default_limit=settings.max_concurrent_per_project
        )
        active = await admission_svc.count_active_tasks_for_project(auth_ctx.project_id)
        if active >= limit:
            _raise_task_limit_exceeded(
                code="PROJECT_TASK_LIMIT_EXCEEDED",
                message=f"Project has reached its concurrent task limit ({limit}).",
                data={
                    "limit": limit,
                    "active": active,
                    "project_id": auth_ctx.project_id,
                },
            )

    # Per-user admission control (tenancy). Fairness quota so one human cannot
    # occupy the whole project/fleet budget. Applies ONLY to human principals:
    # a service API key is a single automation identity bounded by the
    # per-project gate above, and keying its budget on the key's creator would
    # silently clamp all of that key's traffic to one human's limit.
    if auth_ctx.principal_type == "user" and auth_ctx.user_id:
        from app.joysafeter_shared.config.settings import settings

        user_svc = TaskService(db)
        user_limit = settings.max_concurrent_per_user
        user_active = await user_svc.count_active_tasks_for_user(auth_ctx.user_id)
        if user_active >= user_limit:
            _raise_task_limit_exceeded(
                code="USER_TASK_LIMIT_EXCEEDED",
                message=f"User has reached their concurrent task limit ({user_limit}).",
                data={
                    "limit": user_limit,
                    "active": user_active,
                    "user_id": auth_ctx.user_id,
                },
            )

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

    # Resolve environment_ref: prefer request field, fall back to agent default
    environment_ref = req.environment_ref or getattr(agent, "environment_ref", None)

    # Validate environment_ref if provided
    if environment_ref:
        from app.joysafeter_api.services import JoySafeterEnvironmentService as EnvironmentService

        env_svc = EnvironmentService(db)
        env = await env_svc.get_environment_by_ref(environment_ref, project_id=auth_ctx.project_id)
        if not env:
            raise RequestValidationAppError(
                code="TASK_ENVIRONMENT_NOT_FOUND",
                message=f"Environment not found: {environment_ref}",
                data={"environment_ref": environment_ref},
                user_action="fix_input",
            )

    # Auto-create a ChatSession for the task if none provided
    chat_session_id = req.chat_session_id
    auto_created_session_id: uuid.UUID | None = None
    session_svc = None
    if not chat_session_id:
        from app.joysafeter_api.services import SessionService

        session_svc = SessionService(db)
        session = await session_svc.create_session(
            agent_id=agent.id,
            title=f"Task: {req.prompt[:80]}",
            environment_ref=environment_ref,
            agent_version=getattr(agent, "version", None),
            agent_snapshot={"name": agent.name, "model": getattr(agent, "model", None)},
            project_id=auth_ctx.project_id,
        )
        chat_session_id = session.id
        auto_created_session_id = session.id
    else:
        from app.joysafeter_api.services import SessionService

        session_svc = SessionService(db)
        existing_session = await session_svc.get_session(chat_session_id)
        if not existing_session or existing_session.project_id != auth_ctx.project_id:
            raise NotFoundError(
                code="TASK_SESSION_NOT_FOUND",
                message="Session not found",
                data={"session_id": str(chat_session_id)},
                user_action="refresh",
            )
        if existing_session.agent_id != agent.id:
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
                    "active_task_ids": [str(active_task.id) for active_task in active_tasks],
                },
                retryable=True,
                user_action="retry",
            )

    assert session_svc is not None

    svc = TaskService(db)
    task = await svc.create_task(
        agent_id=agent.id,
        prompt=req.prompt,
        system_prompt=req.system_prompt,
        chat_session_id=chat_session_id,
        timeout_sec=req.timeout_sec,
        max_retries=req.max_retries,
        project_id=auth_ctx.project_id,
        idempotency_key=idempotency_key,
        user_id=auth_ctx.user_id,
        org_id=auth_ctx.org_id,
    )

    task_created = bool(getattr(task, "_created_by_create_task", True))
    if not task_created:
        if auto_created_session_id is not None and task.chat_session_id != auto_created_session_id:
            from app.joysafeter_api.services import SessionService

            try:
                await SessionService(db).delete_session(auto_created_session_id)
            except Exception as exc:
                log_boundary_failure(
                    logger,
                    boundary="task_api",
                    code="TASK_IDEMPOTENCY_ORPHAN_SESSION_DELETE_FAILED",
                    message="Failed to delete orphan idempotency session",
                    operation="delete_orphan_idempotency_session",
                    error=exc,
                    data={"session_id": str(auto_created_session_id), "task_id": str(task.id)},
                )
        elif auto_created_session_id is None and task.chat_session_id != chat_session_id:
            raise _task_idempotency_conflict_error(
                existing=task,
                field="chat_session_id",
                message="Idempotency-Key was already used for a different session",
                requested_value=chat_session_id,
                existing_value=task.chat_session_id,
            )

        if task.status == "failed" and "Failed to enqueue task" in (task.error or ""):
            raise _task_enqueue_failed_error(task_id=task.id, session_id=task.chat_session_id)
        return CreateTaskResponse(id=task.id, status=task.status)

    try:
        running_accepted = await session_svc.update_session_status_for_task_event(chat_session_id, "running", task.id)
        if not running_accepted:
            raise RuntimeError("Session already has another active task")
        await session_svc.send_event(
            chat_session_id,
            "session.status_running",
            {"task_id": str(task.id)},
        )
        await enqueue_joysafeter_task(task.id)
    except Exception as exc:
        from app.joysafeter_domain.models.joysafeter_task import JoySafeterTaskStatus

        await svc.update_task_error(
            task.id,
            f"Failed to enqueue task: {exc}",
            JoySafeterTaskStatus.FAILED,
        )
        stop_reason = _task_enqueue_failed_stop_reason(task_id=task.id, session_id=chat_session_id)
        try:
            idle_accepted = await session_svc.update_session_status_for_task_event(
                chat_session_id,
                "idle",
                task.id,
                stop_reason=stop_reason,
            )
            if idle_accepted:
                await session_svc.send_event(
                    chat_session_id,
                    "session.status_idle",
                    {"task_id": str(task.id), "stop_reason": stop_reason},
                )
        except Exception:
            logger.debug(
                "Could not compensate session %s to idle after direct task dispatch failure",
                chat_session_id,
                exc_info=True,
            )
        raise _task_enqueue_failed_error(task_id=task.id, session_id=chat_session_id)

    return CreateTaskResponse(id=task.id, status=task.status)


@router.get("")
async def list_tasks(
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[uuid.UUID] = Query(None),
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
        first_id=str(data[0].id) if data else None,
        last_id=str(data[-1].id) if data else None,
    )


@router.get("/{task_id}")
async def get_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> TaskResponse:
    svc = TaskService(db)
    task = await svc.get_task(task_id, project_id=auth_ctx.project_id)
    if not task:
        raise NotFoundError(
            code="TASK_NOT_FOUND",
            message="Task not found",
            data={"task_id": str(task_id)},
            user_action="refresh",
        )
    return TaskResponse.model_validate(task)


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: uuid.UUID,
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
            data={"task_id": str(task_id)},
            user_action="refresh",
        )

    try:
        task = await svc.cancel_task(task_id)
    except ValueError as e:
        raise _task_cancel_conflict_error(task_id, e) from e
    # cancel_task returns None only if the task doesn't exist, which we
    # already checked above.
    assert task is not None

    from app.joysafeter_orchestrator.grpc.proto import joysafeter_pb2
    from app.joysafeter_orchestrator.lifespan import get_bridge_registry, get_redis_coordinator, get_session_broadcaster

    # Send gRPC CancelTask to the sandbox bridge if the task is running locally
    registry = get_bridge_registry()
    grpc_cancel_sent = False
    if registry:
        bridge = registry.get_by_task(task_id)
        if bridge:
            bridge.request_cancel()
            # Send CancelTask message over gRPC so the runner actually stops
            if bridge.runner_stream:
                try:
                    cancel_msg = joysafeter_pb2.OrchestratorMessage(
                        cancel=joysafeter_pb2.CancelTask(reason="Cancelled via API")
                    )
                    await bridge.write_to_runner(cancel_msg)
                    grpc_cancel_sent = True
                except Exception as exc:
                    log_boundary_failure(
                        logger,
                        boundary="task_api",
                        code="TASK_CANCEL_GRPC_SEND_FAILED",
                        message="Failed to send gRPC CancelTask",
                        operation="cancel_task_grpc_send",
                        error=exc,
                        data={"task_id": str(task_id)},
                    )

    # Cross-instance: if the task wasn't found on this instance, route via Redis
    if not grpc_cancel_sent:
        coordinator = get_redis_coordinator()
        if coordinator:
            sandbox_id = await coordinator.get_task_sandbox(task_id)
            if sandbox_id:
                owner = await coordinator.get_sandbox_owner(sandbox_id)
                if owner:
                    # Decode bytes from Redis if needed
                    if isinstance(owner, bytes):
                        owner = owner.decode()
                    await coordinator.send_instance_command(
                        owner,
                        {"type": "cancel", "sandbox_id": str(sandbox_id)},
                    )

    # Transition the linked ChatSession to idle with cancellation stop_reason
    session_id = task.chat_session_id
    if session_id:
        from app.joysafeter_api.services import SessionService
        from app.joysafeter_domain.models.joysafeter_session import SessionStatus

        session_svc = SessionService(db)
        stop_reason = {"type": "cancelled"}
        session_idle_updated = False
        try:
            session_idle_updated = await session_svc.update_session_status_for_task_event(
                session_id,
                SessionStatus.IDLE.value,
                task_id,
                stop_reason=stop_reason,
            )
        except ConflictError:
            # The task is already cancelled; a terminal/otherwise stale session
            # should not turn a successful task cancellation into a false failure.
            logger.debug(
                "Ignoring stale session idle transition while cancelling task %s for session %s",
                task_id,
                session_id,
                exc_info=True,
            )
        except Exception as exc:
            log_boundary_failure(
                logger,
                boundary="task_api",
                code="TASK_CANCEL_SESSION_IDLE_MARK_FAILED",
                message="Failed to mark session idle after cancelling task",
                operation="cancel_task_mark_session_idle",
                error=exc,
                data={"session_id": str(session_id), "task_id": str(task_id)},
            )
            await db.rollback()
            raise ServiceUnavailableError(
                code="TASK_CANCEL_SESSION_SYNC_FAILED",
                message="Task was cancelled, but failed to mark the linked session idle.",
                data={"task_id": str(task_id), "session_id": str(session_id)},
                source="api",
                retryable=True,
                user_action="refresh",
            ) from None

        if session_idle_updated:
            try:
                await session_svc.send_event(
                    session_id,
                    "session.status_idle",
                    {"task_id": str(task_id), "stop_reason": stop_reason},
                )
            except Exception:
                logger.debug("Failed to persist cancel idle event for session %s", session_id, exc_info=True)

        # Emit SSE event so connected clients learn about the cancellation
        broadcaster = get_session_broadcaster()
        if broadcaster and session_idle_updated:
            await broadcaster.send(
                session_id,
                {"type": "session.status_idle", "task_id": str(task_id), "stop_reason": stop_reason},
            )

    # Publish cancellation over Redis pub/sub for cross-instance WebSocket streams
    coordinator = get_redis_coordinator()
    if coordinator:
        await coordinator.publish_event(
            task_id,
            json.dumps({"type": "complete", "output": "", "error": "Cancelled via API", "status": "cancelled"}),
        )

    return {"id": str(task_id), "status": "cancelled"}


@router.websocket("/{task_id}/stream")
async def task_stream(websocket: WebSocket, task_id: uuid.UUID):
    """WebSocket endpoint for real-time task output streaming."""
    from sqlalchemy import select

    from app.joysafeter_domain.models.joysafeter_auth import AuthUser
    from app.joysafeter_domain.models.joysafeter_organization import Member
    from app.joysafeter_domain.models.joysafeter_project import Project
    from app.joysafeter_orchestrator.lifespan import get_bridge_registry
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
        user_result = await auth_db.execute(select(AuthUser).where(AuthUser.id == str(payload.sub)))
        user = user_result.scalar_one_or_none()
        if not user or not user.is_active:
            await websocket.close(code=4001, reason="TASK_STREAM_AUTH_REQUIRED")
            return

        member_result = await auth_db.execute(
            select(Member)
            .where(
                Member.user_id == str(payload.sub),
                Member.organization_id == str(payload.org_id),
            )
            .limit(1)
        )
        if not member_result.scalar_one_or_none():
            await websocket.close(code=4003, reason="TASK_STREAM_PROJECT_ACCESS_DENIED")
            return

        project_result = await auth_db.execute(
            select(Project)
            .where(
                Project.id == str(payload.project_id),
                Project.org_id == str(payload.org_id),
            )
            .limit(1)
        )
        project = project_result.scalar_one_or_none()
        if not project:
            await websocket.close(code=4003, reason="TASK_STREAM_PROJECT_ACCESS_DENIED")
            return

        auth_svc = TaskService(auth_db)
        auth_task = await auth_svc.get_task(task_id, project_id=payload.project_id)
        if not auth_task:
            await websocket.close(code=4004, reason="TASK_STREAM_TASK_NOT_FOUND")
            return

    registry = get_bridge_registry()
    if not registry:
        await websocket.close(code=1011, reason="TASK_STREAM_KERNEL_UNAVAILABLE")
        return

    bridge = registry.get_by_task(task_id)
    if not bridge:
        # Task might not be running yet — accept and send current status
        await websocket.accept()
        async with AsyncSessionLocal() as db:
            svc = TaskService(db)
            task = await svc.get_task(task_id, project_id=payload.project_id)
            if not task:
                await websocket.send_json(
                    _task_stream_error_payload(
                        code="TASK_STREAM_TASK_NOT_FOUND",
                        message="Task not found",
                        task_id=task_id,
                        user_action="refresh",
                    )
                )
                await websocket.close()
                return
            await websocket.send_json({"type": "status", "status": task.status})
            from app.joysafeter_domain.models.joysafeter_task import JoySafeterTaskStatus as TaskStatus

            if TaskStatus(task.status).is_terminal():
                await websocket.send_json(
                    {
                        "type": "complete",
                        "output": task.output,
                        "error": task.error,
                    }
                )
                await websocket.close()
                return

        # Wait for bridge to appear (task being scheduled)
        for _ in range(60):
            await asyncio.sleep(1)
            bridge = registry.get_by_task(task_id)
            if bridge:
                break

        if not bridge:
            # Cross-instance: try Redis pub/sub for task events
            from app.joysafeter_orchestrator.lifespan import get_redis_coordinator

            coordinator = get_redis_coordinator()
            if coordinator:
                await _stream_via_redis(websocket, task_id, coordinator)
            else:
                await websocket.send_json(
                    _task_stream_error_payload(
                        code="TASK_STREAM_TASK_NOT_SCHEDULED",
                        message="Task is not scheduled yet and no cross-instance stream is available",
                        task_id=task_id,
                        source="runtime",
                        retryable=True,
                        user_action="retry",
                    )
                )
                await websocket.close()
            return
    else:
        await websocket.accept()

    # Subscribe to task events (local bridge)
    q = bridge.subscribe(task_id)
    try:
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=30)
                await websocket.send_json({"type": msg.type, **msg.payload})
                if msg.type == "complete":
                    break
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
            except WebSocketDisconnect:
                break
    finally:
        bridge.unsubscribe(task_id, q)
        try:
            await websocket.close()
        except Exception:
            pass


async def _stream_via_redis(websocket: WebSocket, task_id: uuid.UUID, coordinator):
    """Stream task events via Redis pub/sub (cross-instance fallback).

    Subscribes to the Redis channel first, then checks the DB for terminal
    state to avoid missing a completion event between the DB check in the
    caller and the subscribe call here.
    """
    channel = f"joysafeter:events:{task_id}"
    pubsub = coordinator._redis.pubsub()
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
                    data={"task_id": str(task_id)},
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
