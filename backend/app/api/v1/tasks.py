"""Tasks API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.app_errors import AccessDeniedError, InvalidRequestError, NotFoundError
from app.common.dependencies import CurrentUser, require_workspace_role
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.models.task import Task, TaskPriority
from app.models.workspace import WorkspaceMemberRole
from app.schemas import BaseResponse
from app.schemas.task import (
    AssignTaskRequest,
    CreateTaskRequest,
    DispatchTaskRequest,
    TaskListResponse,
    TaskSummary,
    UpdateTaskRequest,
)
from app.services.task_service import TaskService
from app.services.workspace_permission import check_workspace_access

router = APIRouter(prefix="/v1/tasks", tags=["Tasks"])


def _to_summary(t: Task) -> TaskSummary:
    return TaskSummary(
        id=t.id,
        workspace_id=t.workspace_id,
        title=t.title,
        description=t.description,
        goal=t.goal,
        status=t.status.value if hasattr(t.status, "value") else str(t.status),
        priority=t.priority.value if hasattr(t.priority, "value") else str(t.priority),
        agent_id=t.agent_id,
        creator_id=t.creator_id,
        latest_run_id=t.latest_run_id,
        parent_task_id=t.parent_task_id,
        tags=t.tags,
        position=t.position,
        auto_approve=t.auto_approve,
        due_date=t.due_date,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


@router.get("", response_model=BaseResponse[TaskListResponse])
async def list_tasks(
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    workspace_id: uuid.UUID = Query(...),
    status: str | None = Query(None),
    parent_task_id: uuid.UUID | None = Query(None),
    agent_id: uuid.UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[TaskListResponse]:
    service = TaskService(db)
    tasks = await service.list_tasks(
        workspace_id=workspace_id,
        status=status,
        parent_task_id=parent_task_id,
        agent_id=agent_id,
        limit=limit,
    )
    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=TaskListResponse(items=[_to_summary(t) for t in tasks]),
    )


@router.post("", response_model=BaseResponse[TaskSummary])
async def create_task(
    request: CreateTaskRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[TaskSummary]:
    service = TaskService(db)

    try:
        priority = TaskPriority(request.priority)
    except ValueError:
        raise InvalidRequestError(
            f"Invalid priority: {request.priority}",
            code="TASK_PRIORITY_INVALID",
            data={"priority": request.priority},
        )

    has_access = await check_workspace_access(db, request.workspace_id, current_user, WorkspaceMemberRole.member)
    if not has_access:
        raise AccessDeniedError("No access to workspace", code="WORKSPACE_ACCESS_DENIED")

    task = await service.create_task(
        workspace_id=request.workspace_id,
        creator_id=str(current_user.id),
        title=request.title,
        description=request.description,
        goal=request.goal,
        priority=priority,
        agent_id=request.agent_id,
        parent_task_id=request.parent_task_id,
        tags=request.tags,
        position=request.position,
        auto_approve=request.auto_approve,
    )
    return BaseResponse(success=True, code=200, msg="Task created", data=_to_summary(task))


@router.get("/meta/transitions", response_model=BaseResponse)
async def get_transitions(
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    workspace_id: uuid.UUID = Query(...),
) -> BaseResponse:
    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=TaskService.get_transitions(),
    )


@router.get("/{task_id}", response_model=BaseResponse[TaskSummary])
async def get_task(
    task_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[TaskSummary]:
    service = TaskService(db)
    task = await service.get_task(task_id, workspace_id)
    if not task:
        raise NotFoundError("Task not found", code="TASK_NOT_FOUND", data={"task_id": str(task_id)})
    return BaseResponse(success=True, code=200, msg="ok", data=_to_summary(task))


@router.patch("/{task_id}", response_model=BaseResponse[TaskSummary])
async def update_task(
    task_id: uuid.UUID,
    request: UpdateTaskRequest,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[TaskSummary]:
    service = TaskService(db)
    updates = request.model_dump(exclude_unset=True)
    task = await service.update_task(task_id, workspace_id, **updates)
    if not task:
        raise NotFoundError("Task not found", code="TASK_NOT_FOUND", data={"task_id": str(task_id)})
    return BaseResponse(success=True, code=200, msg="Task updated", data=_to_summary(task))


@router.post("/{task_id}/assign", response_model=BaseResponse[TaskSummary])
async def assign_task(
    task_id: uuid.UUID,
    request: AssignTaskRequest,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[TaskSummary]:
    service = TaskService(db)
    task = await service.assign_to_agent(
        task_id=task_id,
        workspace_id=workspace_id,
        agent_id=request.agent_id,
    )
    return BaseResponse(success=True, code=200, msg="Task assigned", data=_to_summary(task))


@router.post("/{task_id}/dispatch", response_model=BaseResponse[TaskSummary])
async def dispatch_task(
    task_id: uuid.UUID,
    request: DispatchTaskRequest,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[TaskSummary]:
    from app.services.dispatch_service import DispatchService

    dispatch = DispatchService(db)
    await dispatch.dispatch_task(
        task_id=task_id,
        user_id=str(current_user.id),
    )
    service = TaskService(db)
    task = await service.get_task(task_id, workspace_id)
    if task is None:
        raise NotFoundError("Task not found", code="TASK_NOT_FOUND", data={"task_id": str(task_id)})
    return BaseResponse(success=True, code=200, msg="Task dispatched", data=_to_summary(task))


@router.post("/{task_id}/cancel", response_model=BaseResponse[TaskSummary])
async def cancel_task(
    task_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[TaskSummary]:
    from app.services.dispatch_service import DispatchService

    # Find the latest run for this task and cancel it
    service = TaskService(db)
    task = await service.get_task(task_id, workspace_id)
    if not task:
        raise NotFoundError("Task not found", code="TASK_NOT_FOUND", data={"task_id": str(task_id)})

    if task.latest_run_id:
        # Cancel the run through the orchestrator, which will auto-sync task status
        dispatch = DispatchService(db)
        try:
            await dispatch.cancel_run(task.latest_run_id)
        except Exception:
            pass  # Run may already be in a terminal state
    else:
        # No active run — safe to transition status directly via service
        await service.cancel_task(task)

    await db.refresh(task)
    return BaseResponse(success=True, code=200, msg="Task cancelled", data=_to_summary(task))


@router.get("/{task_id}/runs")
async def list_task_runs(
    task_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse:
    from app.schemas.agent_run import AgentRunResponse
    from app.services.agent_run_service import AgentRunService

    service = AgentRunService(db)
    runs = await service.list_runs(workspace_id=workspace_id, task_id=task_id)
    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=[AgentRunResponse.model_validate(r) for r in runs],
    )
