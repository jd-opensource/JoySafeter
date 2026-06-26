"""Organization management API.

Provides CRUD for organizations and member management,
aligned with the unified Organization + Project model.
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_shared.common.dependencies import CurrentUser
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterRole
from app.joysafeter_shared.database import get_db
from app.joysafeter_domain.models.joysafeter_organization import Member, Organization
from app.joysafeter_domain.models.joysafeter_project import Project

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


class UpdateMemberRequest(BaseModel):
    role: str


class TransferOwnershipRequest(BaseModel):
    new_owner_user_id: str


class OrganizationResponse(BaseModel):
    id: str
    name: str
    slug: str
    logo: Optional[str] = None
    created_at: str


class MemberResponse(BaseModel):
    id: str
    user_id: str
    organization_id: str
    role: str
    user_name: Optional[str] = None
    user_email: Optional[str] = None


def _generate_str_id() -> str:
    return str(uuid.uuid4())


VALID_MEMBER_ROLES = {"owner", "admin", "developer", "member", "viewer"}


def _validate_member_role(role: str) -> str:
    normalized = role.strip().lower()
    if normalized == "member":
        normalized = "developer"
    if normalized not in VALID_MEMBER_ROLES:
        raise HTTPException(400, "Invalid member role")
    return normalized


def _role_rank(role: str) -> int:
    return JoySafeterRole.normalize(role).rank


def _ensure_can_assign_role(actor_role: str, target_role: str) -> None:
    if target_role == "owner" and actor_role != "owner":
        raise HTTPException(403, "Only organization owners can assign owner role")
    if _role_rank(actor_role) < _role_rank(target_role):
        raise HTTPException(403, "Cannot grant a role higher than your own")


def _ensure_can_modify_member(actor_role: str, current_role: str, new_role: str) -> None:
    if current_role == "owner" and new_role != "owner":
        raise HTTPException(403, "Cannot change the organization owner role")
    if actor_role != "owner" and new_role == "owner":
        raise HTTPException(403, "Only organization owners can assign owner role")
    if _role_rank(actor_role) < _role_rank(current_role) or _role_rank(actor_role) < _role_rank(new_role):
        raise HTTPException(403, "Cannot modify or grant a role higher than your own")


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
    slug = req.slug or req.name.lower().replace(" ", "-")
    org_id = _generate_str_id()

    org = Organization(id=org_id, name=req.name, slug=slug)
    db.add(org)

    member = Member(
        id=_generate_str_id(),
        user_id=current_user.id,
        organization_id=org_id,
        role="owner",
    )
    db.add(member)

    default_project = Project(
        id=_generate_str_id(),
        org_id=org_id,
        name="Default",
        slug="default",
        is_default=True,
    )
    db.add(default_project)

    await db.commit()
    await db.refresh(org)

    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "project_id": default_project.id,
    }


@router.get("/{organization_id}")
async def get_organization(
    organization_id: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Member).where(
            Member.organization_id == organization_id,
            Member.user_id == current_user.id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(403, "No access to organization")

    result = await db.execute(
        select(Organization).where(Organization.id == organization_id)
    )
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(404, "Organization not found")

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
    result = await db.execute(
        select(Member).where(
            Member.organization_id == organization_id,
            Member.user_id == current_user.id,
            Member.role.in_(["owner", "admin"]),
        )
    )
    actor = result.scalar_one_or_none()
    if not actor:
        raise HTTPException(403, "Insufficient permission")

    result = await db.execute(
        select(Organization).where(Organization.id == organization_id)
    )
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(404, "Organization not found")

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
    result = await db.execute(
        select(Member).where(
            Member.organization_id == organization_id,
            Member.user_id == current_user.id,
            Member.role == "owner",
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(403, "Only the organization owner can delete it")

    result = await db.execute(
        select(Organization).where(Organization.id == organization_id)
    )
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(404, "Organization not found")

    # Delete all members
    await db.execute(
        select(Member).where(Member.organization_id == organization_id)
    )
    from sqlalchemy import delete
    await db.execute(delete(Member).where(Member.organization_id == organization_id))

    # Delete all projects in the org
    from app.joysafeter_domain.models.joysafeter_project import Project
    await db.execute(delete(Project).where(Project.org_id == organization_id))

    # Delete the org itself
    await db.delete(org)
    await db.commit()


@router.post("/{organization_id}/transfer-ownership")
async def transfer_ownership(
    organization_id: str,
    req: TransferOwnershipRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Member).where(
            Member.organization_id == organization_id,
            Member.user_id == current_user.id,
            Member.role == "owner",
        )
    )
    current_owner = result.scalar_one_or_none()
    if not current_owner:
        raise HTTPException(403, "Only the organization owner can transfer ownership")

    if req.new_owner_user_id == current_user.id:
        raise HTTPException(400, "Cannot transfer ownership to yourself")

    result = await db.execute(
        select(Member).where(
            Member.organization_id == organization_id,
            Member.user_id == req.new_owner_user_id,
        )
    )
    new_owner = result.scalar_one_or_none()
    if not new_owner:
        raise HTTPException(404, "New owner must be an existing organization member")

    current_owner.role = "admin"
    new_owner.role = "owner"
    await db.commit()

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
    result = await db.execute(
        select(Member).where(
            Member.organization_id == organization_id,
            Member.user_id == current_user.id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(403, "No access to organization")

    result = await db.execute(
        select(Member).where(Member.organization_id == organization_id)
    )
    members = result.scalars().all()

    data = []
    for m in members:
        user = m.user
        data.append({
            "id": m.id,
            "user_id": m.user_id,
            "organization_id": m.organization_id,
            "role": m.role,
            "user_name": user.name if user else None,
            "user_email": user.email if user else None,
        })
    return {"data": data}


@router.post("/{organization_id}/members", status_code=201)
async def add_member(
    organization_id: str,
    req: AddMemberRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    role = _validate_member_role(req.role)

    result = await db.execute(
        select(Member).where(
            Member.organization_id == organization_id,
            Member.user_id == current_user.id,
            Member.role.in_(["owner", "admin"]),
        )
    )
    actor = result.scalar_one_or_none()
    if not actor:
        raise HTTPException(403, "Insufficient permission")
    _ensure_can_assign_role(actor.role, role)

    existing = await db.execute(
        select(Member).where(
            Member.organization_id == organization_id,
            Member.user_id == req.user_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "User is already a member")

    member = Member(
        id=_generate_str_id(),
        user_id=req.user_id,
        organization_id=organization_id,
        role=role,
    )
    db.add(member)
    await db.commit()
    return {"id": member.id, "user_id": member.user_id, "role": member.role}


@router.put("/{organization_id}/members/{member_id}")
async def update_member_role(
    organization_id: str,
    member_id: str,
    req: UpdateMemberRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    new_role = _validate_member_role(req.role)

    result = await db.execute(
        select(Member).where(
            Member.organization_id == organization_id,
            Member.user_id == current_user.id,
            Member.role.in_(["owner", "admin"]),
        )
    )
    actor = result.scalar_one_or_none()
    if not actor:
        raise HTTPException(403, "Insufficient permission")

    result = await db.execute(
        select(Member).where(Member.id == member_id, Member.organization_id == organization_id)
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(404, "Member not found")

    _ensure_can_modify_member(actor.role, member.role, new_role)
    member.role = new_role
    await db.commit()
    return {"id": member.id, "user_id": member.user_id, "role": member.role}


@router.delete("/{organization_id}/members/{member_id}", status_code=204)
async def remove_member(
    organization_id: str,
    member_id: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Member).where(
            Member.organization_id == organization_id,
            Member.user_id == current_user.id,
            Member.role.in_(["owner", "admin"]),
        )
    )
    actor = result.scalar_one_or_none()
    if not actor:
        raise HTTPException(403, "Insufficient permission")

    result = await db.execute(
        select(Member).where(Member.id == member_id, Member.organization_id == organization_id)
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(404, "Member not found")

    if member.role == "owner":
        raise HTTPException(400, "Cannot remove the owner")
    if _role_rank(actor.role) < _role_rank(member.role):
        raise HTTPException(403, "Cannot remove a member with a higher role than your own")

    await db.delete(member)
    await db.commit()
