"""
Admin Sandbox Management API
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.common.exceptions import ForbiddenException
from app.common.response import success_response
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.models.user_sandbox import UserSandbox
from app.services.sandbox_manager import SandboxManagerService

router = APIRouter(prefix="/v1/sandboxes", tags=["Sandboxes"])


# Dependencies


async def _verify_sandbox_ownership(sandbox_id: str, current_user: User, db: AsyncSession):
    """Validate that the current user owns the sandbox or is a super user."""
    if current_user.is_super_user:
        return
    result = await db.execute(select(UserSandbox).where(UserSandbox.id == sandbox_id))
    sb = result.scalar_one_or_none()
    if not sb:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    if sb.user_id != str(current_user.id):
        raise ForbiddenException("Access denied")


# Schemas


class SandboxResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    container_id: Optional[str] = None
    status: str
    image: str
    runtime: Optional[str] = None
    last_active_at: Optional[datetime] = None
    error_message: Optional[str] = None
    cpu_limit: Optional[float] = None
    memory_limit: Optional[int] = None
    idle_timeout: int
    created_at: datetime
    updated_at: datetime

    # User info (joined)
    user_name: Optional[str] = None
    user_email: Optional[str] = None


class SandboxListResponse(BaseModel):
    items: List[SandboxResponse]
    total: int
    page: int
    size: int


# Endpoints


@router.get("", response_model=SandboxListResponse)
async def list_sandboxes(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all user sandboxes with pagination and filtering."""
    # Build query
    query = select(UserSandbox).join(UserSandbox.user)

    if not current_user.is_super_user:
        user_id = str(current_user.id)

    if status:
        query = query.where(UserSandbox.status == status)
    if user_id:
        query = query.where(UserSandbox.user_id == user_id)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar_one()

    # Pagination
    query = query.offset((page - 1) * size).limit(size).order_by(UserSandbox.updated_at.desc())

    # Execute
    result = await db.execute(query)
    sandboxes = result.scalars().all()

    # Serialize
    items = []
    for sb in sandboxes:
        # Since we joined, we can access user info if eager loaded,
        # but here we rely on lazy loading (which triggers individual queries)
        # or we should optins join load. For admin list, N+1 is acceptable for small page size,
        # but let's be efficient if we can.
        # actually, UserSandbox.user is relationship.

        # Pydantic conversion needs help with lazy loaded relationships usually
        # unless we use response_model config from_attributes=True and it handles it
        # But let's build dict manually for control
        item = SandboxResponse(
            id=sb.id,
            user_id=sb.user_id,
            container_id=sb.container_id,
            status=sb.status,
            image=sb.image,
            runtime=sb.runtime,
            last_active_at=sb.last_active_at,
            error_message=sb.error_message,
            cpu_limit=sb.cpu_limit,
            memory_limit=sb.memory_limit,
            idle_timeout=sb.idle_timeout,
            created_at=sb.created_at,
            updated_at=sb.updated_at,
            user_name=sb.user.name if sb.user else "Unknown",
            user_email=sb.user.email if sb.user else "Unknown",
        )
        items.append(item)

    return SandboxListResponse(items=items, total=total, page=page, size=size)


@router.get("/{sandbox_id}", response_model=SandboxResponse)
async def get_sandbox(
    sandbox_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get sandbox details."""
    await _verify_sandbox_ownership(sandbox_id, current_user, db)

    result = await db.execute(select(UserSandbox).where(UserSandbox.id == sandbox_id))
    sb = result.scalar_one_or_none()

    if not sb:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    return SandboxResponse(
        id=sb.id,
        user_id=sb.user_id,
        container_id=sb.container_id,
        status=sb.status,
        image=sb.image,
        runtime=sb.runtime,
        last_active_at=sb.last_active_at,
        error_message=sb.error_message,
        cpu_limit=sb.cpu_limit,
        memory_limit=sb.memory_limit,
        idle_timeout=sb.idle_timeout,
        created_at=sb.created_at,
        updated_at=sb.updated_at,
        user_name=sb.user.name if sb.user else "Unknown",
        user_email=sb.user.email if sb.user else "Unknown",
    )


@router.post("/{sandbox_id}/stop")
async def stop_sandbox(
    sandbox_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stop a sandbox."""
    await _verify_sandbox_ownership(sandbox_id, current_user, db)
    service = SandboxManagerService(db)
    success = await service.stop_sandbox(sandbox_id)
    if not success:
        raise HTTPException(status_code=404, detail="Sandbox not found or already stopped")

    return success_response(message="Sandbox stopped successfully")


@router.post("/{sandbox_id}/restart")
async def restart_sandbox(
    sandbox_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Restart a sandbox."""
    await _verify_sandbox_ownership(sandbox_id, current_user, db)
    service = SandboxManagerService(db)
    success = await service.restart_sandbox(sandbox_id)
    if not success:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    return success_response(message="Sandbox scheduled for restart")


@router.post("/{sandbox_id}/rebuild")
async def rebuild_sandbox(
    sandbox_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rebuild a sandbox (force stop and recreate)."""
    await _verify_sandbox_ownership(sandbox_id, current_user, db)
    service = SandboxManagerService(db)
    # Stop first
    await service.stop_sandbox(sandbox_id)

    # 获取记录以确认 user_id
    result = await db.execute(select(UserSandbox).where(UserSandbox.id == sandbox_id))
    record = result.scalar_one_or_none()
    if record:
        try:
            await service.ensure_sandbox_running(record.user_id)
        except Exception as e:
            import logging
            logging.error(f"Failed to rebuild sandbox {sandbox_id}: {e}")

    return success_response(message="Sandbox rebuilt successfully")


@router.delete("/{sandbox_id}")
async def delete_sandbox(
    sandbox_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a sandbox permanently."""
    await _verify_sandbox_ownership(sandbox_id, current_user, db)
    service = SandboxManagerService(db)
    success = await service.delete_sandbox(sandbox_id)
    if not success:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    return success_response(message="Sandbox deleted successfully")
