"""Organization management API.

Provides CRUD for organizations and member management,
aligned with the unified Organization + Project model.
"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_organization import Member, Organization
from app.joysafeter_domain.services.joysafeter_organization_member_service import OrganizationMemberService
from app.joysafeter_domain.services.joysafeter_organization_service import OrganizationService
from app.joysafeter_shared.common.app_errors import (
    AppError,
    NotFoundError,
)
from app.joysafeter_shared.common.dependencies import CurrentUser
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterRole
from app.joysafeter_shared.database import get_db

router = APIRouter(tags=["joysafeter-organizations"])


class CreateOrganizationRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: Optional[str] = None


class UpdateOrganizationRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    logo: Optional[str] = None


class AddMemberRequest(BaseModel):
    user_id: str
    role: str = "member"


class TransferOwnershipRequest(BaseModel):
    new_owner_user_id: str


class OrganizationResponse(BaseModel):
    id: str
    name: str
    slug: str
    logo: Optional[str] = None
    project_id: Optional[str] = None
    created_at: str


class MemberResponse(BaseModel):
    id: str
    user_id: str
    organization_id: str
    role: str
    user_name: Optional[str] = None
    user_email: Optional[str] = None


def _organization_not_found_error(organization_id: str) -> AppError:
    return NotFoundError(
        code="ORGANIZATION_NOT_FOUND",
        message="Organization not found",
        data={"organization_id": organization_id},
        user_action="refresh",
    )


@router.get("")
async def list_organizations(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Organization, Member)
        .join(Member, Member.organization_id == Organization.id)
        .where(Member.user_id == current_user.id)
        .order_by(Organization.created_at.desc())
    )
    rows = result.all()
    return {
        "data": [
            {
                "id": org.id,
                "name": org.name,
                "slug": org.slug,
                "logo": org.logo,
                "role": JoySafeterRole.normalize(member.role).value,
                "created_at": org.created_at.isoformat() if org.created_at else None,
            }
            for org, member in rows
        ]
    }


@router.post("", status_code=201)
async def create_organization(
    req: CreateOrganizationRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    created = await OrganizationService(db).create_with_owner_and_default_project(
        name=req.name,
        slug=req.slug,
        owner_user_id=current_user.id,
    )
    org = created.organization

    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "project_id": created.default_project.id,
        "created_at": org.created_at.isoformat() if org.created_at else None,
    }


@router.get("/{organization_id}")
async def get_organization(
    organization_id: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await OrganizationMemberService(db).require_membership(organization_id, current_user.id)

    org_result = await db.execute(select(Organization).where(Organization.id == organization_id))
    org = org_result.scalar_one_or_none()
    if not org:
        raise _organization_not_found_error(organization_id)

    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "logo": org.logo,
        "created_at": org.created_at.isoformat() if org.created_at else None,
    }


@router.put("/{organization_id}")
async def update_organization(
    organization_id: str,
    req: UpdateOrganizationRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await OrganizationMemberService(db).require_member_manager(organization_id, current_user.id)

    org_result = await db.execute(select(Organization).where(Organization.id == organization_id))
    org = org_result.scalar_one_or_none()
    if not org:
        raise _organization_not_found_error(organization_id)

    if req.name is not None:
        org.name = req.name
    if req.logo is not None:
        org.logo = req.logo

    await db.commit()
    await db.refresh(org)
    return {"id": org.id, "name": org.name, "slug": org.slug, "logo": org.logo}


@router.delete("/{organization_id}", status_code=204)
async def delete_organization(
    organization_id: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Delete an organization. Only the owner can delete. Cascades to projects, members, and resources."""
    await OrganizationService(db).delete_organization(organization_id=organization_id, actor_user_id=current_user.id)


@router.post("/{organization_id}/transfer-ownership")
async def transfer_ownership(
    organization_id: str,
    req: TransferOwnershipRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    current_owner, new_owner = await OrganizationMemberService(db).transfer_ownership(
        organization_id=organization_id,
        current_owner_user_id=current_user.id,
        new_owner_user_id=req.new_owner_user_id,
    )

    return {
        "organization_id": organization_id,
        "previous_owner_user_id": current_user.id,
        "previous_owner_role": current_owner.role,
        "new_owner_user_id": new_owner.user_id,
        "new_owner_role": new_owner.role,
    }


# ── Members ──────────────────────────────────────────────────────────


@router.get("/{organization_id}/members")
async def list_members(
    organization_id: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    member_svc = OrganizationMemberService(db)
    await member_svc.require_membership(organization_id, current_user.id)
    members = await member_svc.list_members(organization_id)

    data = []
    for item in members:
        member = item.member
        user = item.user
        data.append(
            {
                "id": member.id,
                "user_id": member.user_id,
                "organization_id": member.organization_id,
                "role": member.role,
                "user_name": user.name if user else None,
                "user_email": user.email if user else None,
            }
        )
    return {"data": data}


@router.post("/{organization_id}/members", status_code=201)
async def add_member(
    organization_id: str,
    req: AddMemberRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    member = await OrganizationMemberService(db).add_member(
        organization_id=organization_id,
        user_id=req.user_id,
        actor_user_id=current_user.id,
        role=req.role,
    )
    return {"id": member.id, "user_id": member.user_id, "role": member.role}
