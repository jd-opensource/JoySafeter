"""
OpenClaw Instance management API.

Per-user OpenClaw instance lifecycle: create, get status, stop, restart, delete.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.services.openclaw_instance_service import OpenClawInstanceService

router = APIRouter(prefix="/v1/openclaw/instances", tags=["OpenClaw Instances"])


class InstanceConfigRequest(BaseModel):
    config_json: Optional[Dict[str, Any]] = Field(default=None, description="OpenClaw config overrides")


def _serialize_instance(inst) -> Dict[str, Any]:
    return {
        "id": inst.id,
        "userId": inst.user_id,
        "name": inst.name,
        "status": inst.status,
        "containerId": inst.container_id,
        "gatewayPort": inst.gateway_port,
        "gatewayToken": inst.gateway_token,
        "lastActiveAt": inst.last_active_at.isoformat() if inst.last_active_at else None,
        "errorMessage": inst.error_message,
        "createdAt": inst.created_at.isoformat() if inst.created_at else None,
        "updatedAt": inst.updated_at.isoformat() if inst.updated_at else None,
    }


@router.get("")
async def get_my_instance(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the current user's OpenClaw instance status."""
    service = OpenClawInstanceService(db)
    status_data = await service.get_instance_status(str(current_user.id))
    return {"success": True, "data": status_data}


@router.post("")
async def start_instance(
    payload: Optional[InstanceConfigRequest] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start or ensure the current user's OpenClaw instance is running."""
    service = OpenClawInstanceService(db)

    if payload and payload.config_json:
        inst = await service.get_instance_by_user(str(current_user.id))
        if inst:
            inst.config_json = payload.config_json
            await db.commit()

    try:
        instance = await service.ensure_instance_running(str(current_user.id))
        return {"success": True, "data": _serialize_instance(instance)}
    except RuntimeError as exc:
        return {"success": False, "error": str(exc)}


@router.post("/stop")
async def stop_instance(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stop the current user's OpenClaw instance."""
    service = OpenClawInstanceService(db)
    instance = await service.stop_instance(str(current_user.id))
    if not instance:
        return {"success": False, "error": "No instance found"}
    return {"success": True, "data": _serialize_instance(instance)}


@router.post("/restart")
async def restart_instance(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Restart the current user's OpenClaw instance."""
    service = OpenClawInstanceService(db)
    try:
        instance = await service.restart_instance(str(current_user.id))
        return {"success": True, "data": _serialize_instance(instance)}
    except RuntimeError as exc:
        return {"success": False, "error": str(exc)}


@router.delete("")
async def delete_instance(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete the current user's OpenClaw instance and container."""
    service = OpenClawInstanceService(db)
    deleted = await service.delete_instance(str(current_user.id))
    if not deleted:
        return {"success": False, "error": "No instance found"}
    return {"success": True}
