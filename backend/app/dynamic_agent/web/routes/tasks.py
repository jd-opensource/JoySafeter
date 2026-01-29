"""
FastAPI routes for Task Execution Tracking API.

Provides endpoints for retrieving task details, execution steps, and real-time updates.
Uses raw SQL DAO implementation via asyncpg.
"""

import asyncio
import json
from typing import List, Optional
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger

from app.dynamic_agent.storage.models import ExecutionStepResponse, TaskResponse, TaskWithStepsResponse
from app.dynamic_agent.storage.persistence.daos.task_dao import TaskDAO

router = APIRouter(prefix="/tasks", tags=["tasks"])


async def get_db_pool() -> asyncpg.Pool:
    from app.dynamic_agent.main import init_storage

    try:
        # storage = get_storage_manager()
        storage = await init_storage()
        return storage.backend.pool  # type: ignore[no-any-return]
    except RuntimeError:
        # Storage not initialized yet
        raise HTTPException(status_code=500, detail="Storage manager not initialized")


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: UUID,
    pool: asyncpg.Pool = Depends(get_db_pool),
) -> TaskResponse:
    """Get task details by ID."""
    dao = TaskDAO(pool)
    task = await dao.get_task_by_id(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return task


@router.get("/{task_id}/steps", response_model=List[ExecutionStepResponse])
async def get_execution_steps(
    task_id: UUID,
    format: str = Query("tree", pattern="^(flat|tree)$"),
    pool: asyncpg.Pool = Depends(get_db_pool),
) -> List[ExecutionStepResponse]:
    """Get execution steps for a task."""
    dao = TaskDAO(pool)

    # Verify task exists
    task = await dao.get_task_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Get all steps (DAO returns flat list of Pydantic models)
    all_steps = await dao.get_all_steps_for_task(task_id)

    if format == "tree":
        return _build_tree_response(all_steps)
    else:
        return all_steps


@router.get("/{task_id}/with-steps", response_model=TaskWithStepsResponse)
async def get_task_with_steps(
    task_id: UUID,
    pool: asyncpg.Pool = Depends(get_db_pool),
) -> TaskWithStepsResponse:
    """Get task with all execution steps (flat list)."""
    from datetime import datetime, timezone

    from app.dynamic_agent.storage.models import ExecutionStepStatus

    dao = TaskDAO(pool)
    task = await dao.get_task_by_id(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Get all steps for this task (flat list, no parent-child relationship)
    steps = await dao.get_all_steps_for_task(task_id)

    # Check for timeout steps (excluding AGENT type)
    # Only modify response data, not database
    # Only check RUNNING steps, ignore COMPLETED steps regardless of duration
    timeout_threshold_min = 10  # 10 minutes
    steps_list = []

    for step in steps:
        # Skip AGENT type steps (they can run longer)
        if step.step_type == "AGENT":
            steps_list.append(step)
            continue

        # Skip COMPLETED steps (only check RUNNING steps for timeout)
        if step.status != ExecutionStepStatus.RUNNING:
            steps_list.append(step)
            continue

        # Calculate elapsed time for RUNNING steps
        now = datetime.now(timezone.utc)
        elapsed = now - step.start_time
        elapsed_ms = elapsed.total_seconds() * 1000

        # Check for timeout
        timeout_threshold_ms = timeout_threshold_min * 60 * 1000
        if elapsed_ms > timeout_threshold_ms:
            # Create new step object with FAILED status (only in response)
            step = ExecutionStepResponse(
                id=step.id,
                task_id=step.task_id,
                step_type=step.step_type,
                name=step.name,
                input_data=step.input_data,
                output_data=step.output_data,
                status=ExecutionStepStatus.FAILED,
                error_message=f"Execution timeout: exceeded {timeout_threshold_min} minutes",
                agent_trace=step.agent_trace,
                start_time=step.start_time,
                end_time=step.end_time,
                created_at=step.created_at,
            )
            logger.warning(
                f"Step {step.id} ({step.name}) marked as FAILED in response due to timeout ({elapsed_ms / 1000:.1f}s)"
            )

        steps_list.append(step)

    # TaskWithStepsResponse inherits from TaskResponse, so we can unpack
    return TaskWithStepsResponse(**task.model_dump(), steps=steps_list)


@router.get("/{task_id}/stream")
async def stream_task_updates(
    task_id: UUID,
    pool: asyncpg.Pool = Depends(get_db_pool),
):
    """Subscribe to real-time task updates via Server-Sent Events (SSE)."""
    from fastapi.responses import StreamingResponse

    async def event_generator():
        dao = TaskDAO(pool)
        task = await dao.get_task_by_id(task_id)

        if not task:
            yield f"data: {json.dumps({'error': 'Task not found'})}\n\n"
            return

        # Send initial task state
        yield f"data: {json.dumps({'type': 'task_start', 'task_id': str(task_id)})}\n\n"

        last_updated = task.updated_at
        poll_interval = 1  # seconds
        max_polls = 300  # 5 minutes

        for i in range(max_polls):
            # Send heartbeat every 15 seconds
            if i > 0 and i % 15 == 0:
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"

            await asyncio.sleep(poll_interval)

            # Refresh task
            updated_task = await dao.get_task_by_id(task_id)
            if not updated_task:
                break

            # Check if task was updated
            # Note: asyncpg returns datetime objects, so comparison works directly
            if updated_task.updated_at > last_updated:
                last_updated = updated_task.updated_at

                yield f"data: {json.dumps({'type': 'task_update', 'status': updated_task.status.value})}\n\n"

            # Check if task is finished
            if updated_task.status.value in ("COMPLETED", "FAILED", "CANCELLED"):
                yield f"data: {json.dumps({'type': 'task_end', 'status': updated_task.status.value})}\n\n"
                break

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/sessions/{session_id}/tasks")
async def get_session_tasks(
    session_id: str,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    pool: asyncpg.Pool = Depends(get_db_pool),
):
    """Get root tasks for a session with pagination."""
    dao = TaskDAO(pool)
    tasks, total = await dao.get_tasks_by_session(str(session_id), limit=limit, offset=offset)

    return {
        "tasks": tasks,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{task_id}/subtasks")
async def get_task_subtasks(
    task_id: UUID,
    created_by_step_id: Optional[UUID] = None,
    pool: asyncpg.Pool = Depends(get_db_pool),
):
    """Get all subtasks of a parent task.

    Args:
        task_id: Parent task ID
        created_by_step_id: Optional step ID to filter subtasks created by a specific step
        pool: Database connection pool

    Returns:
        List of subtasks with steps (timeout-checked)
    """
    from datetime import datetime, timezone

    from app.dynamic_agent.storage.models import ExecutionStepStatus

    dao = TaskDAO(pool)

    if created_by_step_id:
        # Query by created_by_step_id for precise filtering
        subtasks = await dao.get_subtasks_by_step(created_by_step_id)
    else:
        # Query by parent_id (backward compatible)
        subtasks = await dao.get_subtasks(task_id)

    # Apply timeout logic to each subtask's steps
    timeout_threshold_min = 10  # 10 minutes
    subtasks_with_steps = []

    for subtask in subtasks:
        # Get all steps for this subtask
        steps = await dao.get_all_steps_for_task(subtask.id)

        # Apply timeout logic (same as get_task_with_steps)
        steps_list = []
        for step in steps:
            # Skip AGENT type steps (they can run longer)
            if step.step_type == "AGENT":
                steps_list.append(step)
                continue

            # Skip COMPLETED steps (only check RUNNING steps for timeout)
            if step.status != ExecutionStepStatus.RUNNING:
                steps_list.append(step)
                continue

            # Calculate elapsed time for RUNNING steps
            now = datetime.now(timezone.utc)
            elapsed = now - step.start_time
            elapsed_ms = elapsed.total_seconds() * 1000

            # Check for timeout
            timeout_threshold_ms = timeout_threshold_min * 60 * 1000
            if elapsed_ms > timeout_threshold_ms:
                # Create new step object with FAILED status (only in response)
                step = ExecutionStepResponse(
                    id=step.id,
                    task_id=step.task_id,
                    step_type=step.step_type,
                    name=step.name,
                    input_data=step.input_data,
                    output_data=step.output_data,
                    status=ExecutionStepStatus.FAILED,
                    error_message=f"Execution timeout: exceeded {timeout_threshold_min} minutes",
                    agent_trace=step.agent_trace,
                    start_time=step.start_time,
                    end_time=step.end_time,
                    created_at=step.created_at,
                )
                logger.warning(
                    f"Step {step.id} ({step.name}) in subtask {subtask.id} marked as FAILED in response due to timeout ({elapsed_ms / 1000:.1f}s)"
                )

            steps_list.append(step)

        # Build subtask response with steps
        subtasks_with_steps.append({**subtask.model_dump(), "steps": steps_list})

    return {
        "subtasks": subtasks_with_steps,
        "total": len(subtasks_with_steps),
    }


@router.post("/batch")
async def get_tasks_batch(
    task_ids: List[UUID],
    pool: asyncpg.Pool = Depends(get_db_pool),
):
    """Get multiple tasks with their steps in a single request.

    Args:
        task_ids: List of task IDs to fetch
        pool: Database connection pool

    Returns:
        Dictionary mapping task_id to task data with steps
    """
    dao = TaskDAO(pool)

    # Fetch tasks and steps in batch
    tasks_dict = await dao.get_tasks_batch(task_ids)
    steps_dict = await dao.get_steps_batch(task_ids)

    # Build response
    result = {}
    for task_id in task_ids:
        task = tasks_dict.get(task_id)
        if task:
            steps = steps_dict.get(task_id, [])
            result[str(task_id)] = {**task.model_dump(), "steps": [step.model_dump() for step in steps]}

    return result


def _build_tree_response(steps: List[ExecutionStepResponse]) -> List[ExecutionStepResponse]:
    """Build execution tree from flat list of Pydantic models.

    Args:
        steps: Flat list of ExecutionStepResponse objects

    Returns:
        List of root ExecutionStepResponse with nested children
    """
    # Create map of steps by ID
    step_map = {step.id: step for step in steps}

    root_steps = []

    # Link children to parents
    for step in steps:
        if step.parent_step_id and step.parent_step_id in step_map:
            parent = step_map[step.parent_step_id]
            parent.children.append(step)
        else:
            root_steps.append(step)

    return root_steps
