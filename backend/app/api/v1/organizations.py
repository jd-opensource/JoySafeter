"""
组织与成员相关 API
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user, require_org_role
from app.common.response import success_response
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.services.organization_service import OrganizationService

router = APIRouter(prefix="/v1/organizations", tags=["Organizations"])


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class UpdateOrganizationRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    slug: Optional[str] = Field(None, min_length=3, max_length=255)
    logo: Optional[str] = Field(None, max_length=500)


class UpdateSeatsRequest(BaseModel):
    seats: int = Field(..., ge=1, le=50)


class InviteMemberRequest(BaseModel):
    email: EmailStr
    role: Optional[str] = Field(default="member")
    workspaceInvitations: Optional[list] = None  # 兼容前端多工作空间邀请参数


class UpdateMemberRoleRequest(BaseModel):
    role: str = Field(..., description="owner/admin/member")


class CreateOrganizationRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: Optional[str] = Field(None, min_length=3, max_length=255)
    logo: Optional[str] = Field(None, max_length=500)


# --------------------------------------------------------------------------- #
# Routes - Organizations
# --------------------------------------------------------------------------- #
@router.post("")
async def create_organization(
    payload: CreateOrganizationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建组织并设当前用户为 owner"""
    service = OrganizationService(db)
    data = await service.create_organization(
        name=payload.name,
        slug=payload.slug or payload.name.lower().replace(" ", "-"),
        logo=payload.logo,
        current_user=current_user,
    )
    return success_response(data=data, message="Organization created")


@router.post("/{organization_id}/activate")
async def set_active_organization(
    organization_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """设置活跃组织（当前仅校验成员身份并返回组织信息）"""
    service = OrganizationService(db)
    data = await service.set_active_organization(organization_id, current_user)
    return success_response(data=data, message="Organization set active")


@router.get("/{organization_id}")
async def get_organization(
    organization_id: uuid.UUID,
    include: Optional[str] = Query(None, description="可选 seats"),
    db: AsyncSession = Depends(get_db),
    current_user: User = require_org_role("member"),
):
    """获取组织详情"""
    service = OrganizationService(db)
    include_seats = "seats" in _parse_include(include)
    data = await service.get_organization(organization_id, include_seats, current_user)
    return success_response(data=data)


@router.put("/{organization_id}")
async def update_organization(
    organization_id: uuid.UUID,
    payload: UpdateOrganizationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_org_role("admin"),
):
    """更新组织设置"""
    service = OrganizationService(db)
    data = await service.update_organization(
        organization_id,
        name=payload.name,
        slug=payload.slug,
        logo=payload.logo,
        current_user=current_user,
    )
    return success_response(data=data, message="Organization updated")


@router.put("/{organization_id}/seats")
async def update_seats(
    organization_id: uuid.UUID,
    payload: UpdateSeatsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_org_role("admin"),
):
    """更新 seats"""
    service = OrganizationService(db)
    data = await service.update_seats(
        organization_id,
        seats=payload.seats,
        current_user=current_user,
    )
    return success_response(data=data, message="Seats updated")


# --------------------------------------------------------------------------- #
# Routes - Members
# --------------------------------------------------------------------------- #
@router.get("/{organization_id}/members")
async def list_members(
    organization_id: uuid.UUID,
    include: Optional[str] = Query(None, description="可选 usage"),
    db: AsyncSession = Depends(get_db),
    current_user: User = require_org_role("member"),
):
    """获取成员列表"""
    service = OrganizationService(db)
    include_usage = "usage" in _parse_include(include)
    data = await service.list_members(
        organization_id,
        include_usage=include_usage,
        current_user=current_user,
    )
    return success_response(data=data)


@router.post("/{organization_id}/members")
async def invite_member(
    organization_id: uuid.UUID,
    payload: InviteMemberRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_org_role("admin"),
):
    """邀请新成员"""
    service = OrganizationService(db)
    data = await service.invite_member(
        organization_id,
        email=payload.email,
        role=payload.role or "member",
        current_user=current_user,
    )
    return success_response(data=data, message="Member invited")


@router.get("/{organization_id}/members/{member_id}")
async def get_member(
    organization_id: uuid.UUID,
    member_id: uuid.UUID,
    include: Optional[str] = Query(None, description="可选 usage"),
    db: AsyncSession = Depends(get_db),
    current_user: User = require_org_role("member"),
):
    """获取成员详情"""
    service = OrganizationService(db)
    include_usage = "usage" in _parse_include(include)
    data = await service.get_member(
        organization_id,
        member_id,
        include_usage=include_usage,
        current_user=current_user,
    )
    return success_response(data=data)


@router.put("/{organization_id}/members/{member_id}")
async def update_member_role(
    organization_id: uuid.UUID,
    member_id: uuid.UUID,
    payload: UpdateMemberRoleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_org_role("admin"),
):
    """更新成员角色"""
    service = OrganizationService(db)
    data = await service.update_member_role(
        organization_id,
        member_id,
        role=payload.role,
        current_user=current_user,
    )
    return success_response(data=data, message="Member role updated")


@router.delete("/{organization_id}/members/{member_id}")
async def remove_member(
    organization_id: uuid.UUID,
    member_id: uuid.UUID,
    shouldReduceSeats: bool = Query(False, description="移除成员时是否同步减少 seats"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """移除成员"""
    service = OrganizationService(db)
    await service.remove_member(
        organization_id,
        member_id,
        current_user=current_user,
        should_reduce_seats=bool(shouldReduceSeats),
    )
    return success_response(message="Member removed")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _parse_include(include: Optional[str]) -> set[str]:
    if not include:
        return set()
    return {part.strip() for part in include.split(",") if part.strip()}
