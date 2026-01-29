"""
Historical task inspection endpoints.

Provides endpoints for viewing historical task execution data,
including detailed step information and filtering capabilities.
Uses raw SQL DAO implementation via asyncpg.
"""

from typing import Dict, List, Optional
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger

from app.dynamic_agent.storage.models import ExecutionStepResponse
from app.dynamic_agent.storage.persistence.daos.task_dao import TaskDAO

router = APIRouter(prefix="/history", tags=["history"])


async def get_db_pool() -> asyncpg.Pool:
    from app.dynamic_agent.main import init_storage

    try:
        # storage = get_storage_manager()
        storage = await init_storage()
        return storage.backend.pool  # type: ignore[no-any-return]
    except RuntimeError:
        # Storage not initialized yet
        raise HTTPException(status_code=500, detail="Storage manager not initialized")


@router.get("/tasks/{task_id}/steps/{step_id}")
async def get_step_details(
    task_id: UUID,
    step_id: UUID,
    pool: asyncpg.Pool = Depends(get_db_pool),
):
    """Get detailed information about a specific execution step."""
    try:
        dao = TaskDAO(pool)
        step = await dao.get_step_by_id(step_id)

        if not step or step.task_id != task_id:
            raise HTTPException(status_code=404, detail="Step not found")

        return step.model_dump()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching step details: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/tasks")
async def list_tasks_with_filters(
    session_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    pool: asyncpg.Pool = Depends(get_db_pool),
):
    """List tasks with filtering and pagination."""
    try:
        dao = TaskDAO(pool)

        if session_id:
            # Use DAO method
            tasks, total = await dao.get_tasks_by_session(session_id=session_id, limit=limit, offset=offset)
        else:
            # Need to implement get_all_tasks or similar in DAO if needed.
            # For now, return empty if no session_id provided, as per original intent likely.
            tasks, total = [], 0

        # Memory filtering for status if DAO doesn't support it natively yet
        # Note: Pagination in DAO is applied before status filter here, which is suboptimal.
        # But matching original logic.
        if status:
            tasks = [t for t in tasks if t.status.value == status]
            total = len(tasks)

        return {
            "tasks": [t.model_dump() for t in tasks],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    except Exception as e:
        logger.error(f"Error listing tasks: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/tasks/{task_id}/search-steps")
async def search_steps(
    task_id: UUID,
    query: str = Query(..., min_length=1),
    step_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    pool: asyncpg.Pool = Depends(get_db_pool),
):
    """Search execution steps within a task."""
    try:
        dao = TaskDAO(pool)
        steps = await dao.get_all_steps_for_task(task_id)

        # Filter by query
        results = [s for s in steps if query.lower() in s.name.lower()]

        # Filter by step_type
        if step_type:
            results = [s for s in results if s.step_type == step_type]

        # Filter by status
        if status:
            results = [s for s in results if s.status.value == status]

        return {
            "task_id": str(task_id),
            "query": query,
            "results": [s.model_dump() for s in results],
            "count": len(results),
        }
    except Exception as e:
        logger.error(f"Error searching steps: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/tasks/{task_id}/statistics")
async def get_task_statistics(
    task_id: UUID,
    pool: asyncpg.Pool = Depends(get_db_pool),
):
    """Get execution statistics for a task."""
    try:
        dao = TaskDAO(pool)
        task = await dao.get_task_by_id(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        steps = await dao.get_all_steps_for_task(task_id)

        # Calculate statistics
        total_steps = len(steps)
        completed_steps = sum(1 for s in steps if s.status.value == "COMPLETED")
        failed_steps = sum(1 for s in steps if s.status.value == "FAILED")
        running_steps = sum(1 for s in steps if s.status.value == "RUNNING")

        # Calculate durations
        total_duration_ms = 0
        for step in steps:
            if step.end_time and step.start_time:
                total_duration_ms += int((step.end_time - step.start_time).total_seconds() * 1000)

        # Calculate depth (need to reconstruct tree to calculate max depth)
        step_map = {s.id: s for s in steps}
        children_map: Dict[UUID, List[ExecutionStepResponse]] = {s.id: [] for s in steps}
        roots = []

        for s in steps:
            if s.parent_step_id and s.parent_step_id in step_map:
                children_map[s.parent_step_id].append(s)
            else:
                roots.append(s)

        max_depth = 0

        def calculate_depth(step_id, depth=0):
            nonlocal max_depth
            max_depth = max(max_depth, depth)
            for child in children_map[step_id]:
                calculate_depth(child.id, depth + 1)

        for root in roots:
            calculate_depth(root.id)

        return {
            "task_id": str(task_id),
            "status": task.status.value,
            "total_steps": total_steps,
            "completed_steps": completed_steps,
            "failed_steps": failed_steps,
            "running_steps": running_steps,
            "success_rate": (completed_steps / total_steps * 100) if total_steps > 0 else 0,
            "total_duration_ms": total_duration_ms,
            "tree_depth": max_depth,
            "created_at": task.created_at.isoformat(),
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting task statistics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
