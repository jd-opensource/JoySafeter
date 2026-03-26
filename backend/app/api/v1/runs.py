"""Runs API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import CurrentUser
from app.core.database import get_db
from app.models.agent_run import AgentRun, AgentRunStatus
from app.schemas import BaseResponse
from app.schemas.runs import (
    AgentDefinitionResponse,
    AgentListResponse,
    CreateRunRequest,
    CreateRunResponse,
    CreateSkillCreatorRunRequest,
    RunEventResponse,
    RunEventsPageResponse,
    RunListResponse,
    RunSnapshotResponse,
    RunSummary,
)
from app.services.run_reducers import agent_registry
from app.services.run_service import RunService
from app.utils.task_manager import task_manager

router = APIRouter(prefix="/v1/runs", tags=["Runs"])


def _to_run_summary(run: AgentRun) -> RunSummary:
    definition = agent_registry.find(run.agent_name)
    return RunSummary(
        run_id=run.id,
        status=run.status.value if hasattr(run.status, "value") else str(run.status),
        run_type=run.run_type,
        agent_name=run.agent_name,
        agent_display_name=definition.display_name if definition else run.agent_name,
        source=run.source,
        thread_id=run.thread_id,
        graph_id=run.graph_id,
        title=run.title,
        started_at=run.started_at,
        finished_at=run.finished_at,
        last_seq=run.last_seq,
        error_code=run.error_code,
        error_message=run.error_message,
        last_heartbeat_at=run.last_heartbeat_at,
        updated_at=run.updated_at,
    )


@router.get("", response_model=BaseResponse[RunListResponse])
async def list_runs(
    current_user: CurrentUser,
    run_type: str | None = Query(None),
    agent_name: str | None = Query(None),
    status: str | None = Query(None),
    search: str | None = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[RunListResponse]:
    service = RunService(db)
    runs = await service.list_recent_runs(
        user_id=str(current_user.id),
        run_type=run_type,
        agent_name=agent_name,
        status=status,
        search=search,
        limit=limit,
    )
    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=RunListResponse(items=[_to_run_summary(run) for run in runs]),
    )


@router.get("/agents", response_model=BaseResponse[AgentListResponse])
async def list_agents(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentListResponse]:
    service = RunService(db)
    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=AgentListResponse(
            items=[
                AgentDefinitionResponse(agent_name=definition.agent_name, display_name=definition.display_name)
                for definition in await service.list_agents()
            ]
        ),
    )


@router.get("/active", response_model=BaseResponse[RunSummary | None])
async def get_active_run(
    current_user: CurrentUser,
    agent_name: str = Query(..., min_length=1),
    graph_id: uuid.UUID = Query(...),
    thread_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[RunSummary | None]:
    service = RunService(db)
    run = await service.find_latest_active_run(
        user_id=str(current_user.id),
        agent_name=agent_name,
        graph_id=graph_id,
        thread_id=thread_id,
    )
    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=_to_run_summary(run) if run else None,
    )


@router.get("/active/skill-creator", response_model=BaseResponse[RunSummary | None])
async def get_active_skill_creator_run(
    current_user: CurrentUser,
    graph_id: uuid.UUID,
    thread_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[RunSummary | None]:
    return await get_active_run(
        current_user=current_user,
        agent_name="skill_creator",
        graph_id=graph_id,
        thread_id=thread_id,
        db=db,
    )


@router.post("", response_model=BaseResponse[CreateRunResponse])
async def create_run(
    request: CreateRunRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[CreateRunResponse]:
    service = RunService(db)
    try:
        run = await service.create_run(
            user_id=str(current_user.id),
            agent_name=request.agent_name,
            graph_id=request.graph_id,
            thread_id=request.thread_id,
            message=request.message,
            input=request.input,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return BaseResponse(
        success=True,
        code=200,
        msg="Run created",
        data=CreateRunResponse(
            run_id=run.id,
            thread_id=run.thread_id or "",
            status=run.status.value if hasattr(run.status, "value") else str(run.status),
        ),
    )


@router.post("/skill-creator", response_model=BaseResponse[CreateRunResponse])
async def create_skill_creator_run(
    request: CreateSkillCreatorRunRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[CreateRunResponse]:
    return await create_run(
        request=CreateRunRequest(
            agent_name="skill_creator",
            graph_id=request.graph_id,
            message=request.message,
            thread_id=request.thread_id,
            input={"edit_skill_id": request.edit_skill_id},
        ),
        current_user=current_user,
        db=db,
    )


@router.get("/{run_id}", response_model=BaseResponse[RunSummary])
async def get_run(
    run_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[RunSummary]:
    service = RunService(db)
    run = await service.get_run(run_id, str(current_user.id))
    if run is None:
        return BaseResponse(success=False, code=404, msg="Run not found", data=None)
    return BaseResponse(success=True, code=200, msg="ok", data=_to_run_summary(run))


@router.get("/{run_id}/snapshot", response_model=BaseResponse[RunSnapshotResponse])
async def get_run_snapshot(
    run_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[RunSnapshotResponse]:
    service = RunService(db)
    snapshot = await service.get_snapshot(run_id, str(current_user.id))
    if snapshot is None:
        return BaseResponse(success=False, code=404, msg="Snapshot not found", data=None)
    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=RunSnapshotResponse(
            run_id=run_id,
            status=snapshot.status,
            last_seq=snapshot.last_seq,
            projection=snapshot.projection or {},
        ),
    )


@router.get("/{run_id}/events", response_model=BaseResponse[RunEventsPageResponse])
async def get_run_events(
    current_user: CurrentUser,
    run_id: uuid.UUID,
    after_seq: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[RunEventsPageResponse]:
    service = RunService(db)
    events = await service.list_events_after(run_id, str(current_user.id), after_seq=after_seq, limit=limit)
    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=RunEventsPageResponse(
            run_id=run_id,
            events=[
                RunEventResponse(
                    seq=event.seq,
                    event_type=event.event_type,
                    payload=event.payload or {},
                    trace_id=event.trace_id,
                    observation_id=event.observation_id,
                    parent_observation_id=event.parent_observation_id,
                    created_at=event.created_at,
                )
                for event in events
            ],
            next_after_seq=events[-1].seq if events else after_seq,
        ),
    )


@router.post("/{run_id}/cancel", response_model=BaseResponse[RunSummary])
async def cancel_run(
    run_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[RunSummary]:
    service = RunService(db)
    run = await service.get_run(run_id, str(current_user.id))
    if run is None:
        return BaseResponse(success=False, code=404, msg="Run not found", data=None)

    if run.thread_id and run.status in {
        AgentRunStatus.QUEUED,
        AgentRunStatus.RUNNING,
        AgentRunStatus.INTERRUPT_WAIT,
    }:
        try:
            await task_manager.stop_task(run.thread_id)
        except Exception:
            pass

    run = await service.mark_status(
        run_id=run_id,
        user_id=str(current_user.id),
        status=AgentRunStatus.CANCELLED,
        error_code="cancelled",
        error_message="Cancelled by user",
    )
    if run is None:
        return BaseResponse(success=False, code=404, msg="Run not found", data=None)
    return BaseResponse(success=True, code=200, msg="Run cancelled", data=_to_run_summary(run))
