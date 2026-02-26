"""
OpenClaw Worker management API.

Endpoints for registering, listing, removing, and health-checking
OpenClaw worker instances.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.services.openclaw_worker_service import OpenClawWorkerService

router = APIRouter(prefix="/openclaw/workers", tags=["OpenClaw Workers"])


class WorkerRegisterRequest(BaseModel):
    name: str = Field(..., max_length=255)
    endpoint_url: str = Field(..., max_length=512)
    max_tasks: int = Field(default=3, ge=1, le=20)
    container_id: Optional[str] = None


def _serialize_worker(w) -> Dict[str, Any]:
    return {
        "id": w.id,
        "name": w.name,
        "endpointUrl": w.endpoint_url,
        "status": w.status,
        "containerId": w.container_id,
        "currentTasks": w.current_tasks,
        "maxTasks": w.max_tasks,
        "lastHeartbeatAt": w.last_heartbeat_at.isoformat() if w.last_heartbeat_at else None,
        "errorMessage": w.error_message,
        "createdAt": w.created_at.isoformat() if w.created_at else None,
        "updatedAt": w.updated_at.isoformat() if w.updated_at else None,
    }


@router.get("")
async def list_workers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = OpenClawWorkerService(db)
    workers = await service.list_workers()
    return {"success": True, "data": [_serialize_worker(w) for w in workers]}


@router.post("")
async def register_worker(
    payload: WorkerRegisterRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = OpenClawWorkerService(db)
    worker = await service.register_worker(
        name=payload.name,
        endpoint_url=payload.endpoint_url,
        max_tasks=payload.max_tasks,
        container_id=payload.container_id,
    )
    return {"success": True, "data": _serialize_worker(worker)}


@router.delete("/{worker_id}")
async def remove_worker(
    worker_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = OpenClawWorkerService(db)
    removed = await service.remove_worker(worker_id)
    if not removed:
        return {"success": False, "error": "Worker not found"}
    return {"success": True}


@router.post("/{worker_id}/ping")
async def ping_worker(
    worker_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = OpenClawWorkerService(db)
    worker = await service.get_worker(worker_id)
    if not worker:
        return {"success": False, "error": "Worker not found"}
    alive = await service.ping_worker(worker)
    return {"success": True, "data": {"alive": alive, "worker": _serialize_worker(worker)}}


@router.post("/health-check-all")
async def health_check_all(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = OpenClawWorkerService(db)
    summary = await service.health_check_all()
    return {"success": True, "data": summary}
