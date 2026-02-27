"""
OpenClaw Task API.

Endpoints for submitting, listing, inspecting, and cancelling tasks
dispatched to the user's OpenClaw instance.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.services.openclaw_task_service import OpenClawTaskService

router = APIRouter(prefix="/v1/openclaw/tasks", tags=["OpenClaw Tasks"])


class TaskSubmitRequest(BaseModel):
    title: str = Field(..., max_length=512)
    input_data: Optional[Dict[str, Any]] = None


def _serialize_task(t) -> Dict[str, Any]:
    return {
        "id": t.id,
        "userId": t.user_id,
        "instanceId": t.instance_id,
        "title": t.title,
        "inputData": t.input_data,
        "status": t.status,
        "output": t.output,
        "redisChannel": t.redis_channel,
        "startedAt": t.started_at.isoformat() if t.started_at else None,
        "completedAt": t.completed_at.isoformat() if t.completed_at else None,
        "createdAt": t.created_at.isoformat() if t.created_at else None,
        "updatedAt": t.updated_at.isoformat() if t.updated_at else None,
    }


@router.get("")
async def list_tasks(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = OpenClawTaskService(db)
    tasks = await service.list_tasks(
        user_id=str(current_user.id),
        status=status,
        limit=limit,
        offset=offset,
    )
    return {"success": True, "data": [_serialize_task(t) for t in tasks]}


@router.post("")
async def submit_task(
    payload: TaskSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = OpenClawTaskService(db)
    try:
        task = await service.submit_task(
            user_id=str(current_user.id),
            title=payload.title,
            input_data=payload.input_data,
        )
    except RuntimeError as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "data": _serialize_task(task)}


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = OpenClawTaskService(db)
    task = await service.get_task(task_id)
    if not task:
        return {"success": False, "error": "Task not found"}
    if task.user_id != str(current_user.id):
        return {"success": False, "error": "Forbidden"}
    return {"success": True, "data": _serialize_task(task)}


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = OpenClawTaskService(db)
    try:
        task = await service.cancel_task(task_id, str(current_user.id))
    except PermissionError as exc:
        return {"success": False, "error": str(exc)}
    if not task:
        return {"success": False, "error": "Task not found"}
    return {"success": True, "data": _serialize_task(task)}


@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = OpenClawTaskService(db)
    try:
        success = await service.delete_task(task_id, str(current_user.id))
    except PermissionError as exc:
        return {"success": False, "error": str(exc)}
    if not success:
        return {"success": False, "error": "Task not found"}
    return {"success": True}
