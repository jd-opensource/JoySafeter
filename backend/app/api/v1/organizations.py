"""
Organization and member API
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
from app.models.enums import OrgRole
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
    role: Optional[str] = Field(default=OrgRole.MEMBER)
    workspaceInvitations: Optional[list] = None  # compatible with frontend multi-workspace invitation params


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
    """Create an organization and set the current user as owner."""
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
    """Set active organization (currently only validates membership and returns org info)."""
    service = OrganizationService(db)
    data = await service.set_active_organization(organization_id, current_user)
    return success_response(data=data, message="Organization set active")


@router.get("/{organization_id}")
async def get_organization(
    organization_id: uuid.UUID,
    include: Optional[str] = Query(None, description="Optional: seats"),
    db: AsyncSession = Depends(get_db),
    current_user: User = require_org_role(OrgRole.MEMBER),
):
    """Get organization details."""
    service = OrganizationService(db)
    include_seats = "seats" in _parse_include(include)
    data = await service.get_organization(organization_id, include_seats, current_user)
    return success_response(data=data)


@router.put("/{organization_id}")
async def update_organization(
    organization_id: uuid.UUID,
    payload: UpdateOrganizationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_org_role(OrgRole.ADMIN),
):
    """Update organization settings."""
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
    current_user: User = require_org_role(OrgRole.ADMIN),
):
    """Update seats."""
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
    include: Optional[str] = Query(None, description="Optional: usage"),
    db: AsyncSession = Depends(get_db),
    current_user: User = require_org_role(OrgRole.MEMBER),
):
    """List members."""
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
    current_user: User = require_org_role(OrgRole.ADMIN),
):
    """Invite a new member."""
    service = OrganizationService(db)
    data = await service.invite_member(
        organization_id,
        email=payload.email,
        role=payload.role or OrgRole.MEMBER,
        current_user=current_user,
    )
    return success_response(data=data, message="Member invited")


@router.get("/{organization_id}/members/{member_id}")
async def get_member(
    organization_id: uuid.UUID,
    member_id: uuid.UUID,
    include: Optional[str] = Query(None, description="Optional: usage"),
    db: AsyncSession = Depends(get_db),
    current_user: User = require_org_role(OrgRole.MEMBER),
):
    """Get member details."""
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
    current_user: User = require_org_role(OrgRole.ADMIN),
):
    """Update member role."""
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
    shouldReduceSeats: bool = Query(False, description="Whether to reduce seats when removing a member"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a member."""
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
