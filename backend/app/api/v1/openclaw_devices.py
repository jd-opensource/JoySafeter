"""
OpenClaw Device pairing management API.

Mirrors the moltworker AdminPage device management:
- List paired devices
- Approve individual device pairing requests
- Approve all pending requests
"""

from __future__ import annotations

import json
import subprocess

from fastapi import APIRouter, Depends
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.services.openclaw_instance_service import OpenClawInstanceService

router = APIRouter(prefix="/v1/openclaw/devices", tags=["OpenClaw Devices"])


async def _get_running_instance(db: AsyncSession, user_id: str):
    service = OpenClawInstanceService(db)
    instance = await service.get_instance_by_user(user_id)
    if not instance or instance.status != "running" or not instance.container_id:
        return None
    return instance


def _docker_exec(container_id: str, cmd: list[str], timeout: int = 15) -> str:
    """Run a command inside the user's OpenClaw container."""
    result = subprocess.run(
        ["docker", "exec", container_id] + cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"Command failed with exit code {result.returncode}")
    return result.stdout.strip()


@router.get("")
async def list_devices(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List devices paired with the user's OpenClaw instance."""
    instance = await _get_running_instance(db, str(current_user.id))
    if not instance:
        return {"success": True, "data": []}

    try:
        output = _docker_exec(instance.container_id, ["openclaw", "devices", "list", "--json"])
        devices = json.loads(output) if output else []
        return {"success": True, "data": devices}
    except Exception as e:
        logger.warning(f"Failed to list devices for user {current_user.id}: {e}")
        return {"success": True, "data": [], "warning": str(e)}


@router.post("/{device_id}/approve")
async def approve_device(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Approve a specific device pairing request."""
    instance = await _get_running_instance(db, str(current_user.id))
    if not instance:
        return {"success": False, "error": "No running instance"}

    try:
        _docker_exec(instance.container_id, ["openclaw", "devices", "approve", device_id])
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/approve-all")
async def approve_all_devices(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Approve all pending device pairing requests."""
    instance = await _get_running_instance(db, str(current_user.id))
    if not instance:
        return {"success": False, "error": "No running instance"}

    try:
        output = _docker_exec(instance.container_id, ["openclaw", "devices", "list", "--json"])
        devices = json.loads(output) if output else {}
        pending = devices.get("pending", [])
        for p in pending:
            device_id = p.get("deviceId")
            if device_id:
                _docker_exec(instance.container_id, ["openclaw", "devices", "approve", device_id])
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}
