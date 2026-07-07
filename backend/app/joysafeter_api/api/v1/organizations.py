"""Organization management API.

Provides CRUD for organizations and member management,
aligned with the unified Organization + Project model.
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_organization import Member, Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_shared.common.app_errors import (
    AccessDeniedError,
    AppError,
    InvalidRequestError,
    NotFoundError,
    ResourceConflictError,
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


def _organization_not_found_error(organization_id: str) -> AppError:
    return NotFoundError(
        code="ORGANIZATION_NOT_FOUND",
        message="Organization not found",
        data={"organization_id": organization_id},
        user_action="refresh",
    )


def _organization_member_not_found_error(organization_id: str, member_id: str | None = None) -> AppError:
    data = {"organization_id": organization_id}
    if member_id is not None:
        data["member_id"] = member_id
    return NotFoundError(
        code="ORGANIZATION_MEMBER_NOT_FOUND",
        message="Member not found",
        data=data,
        user_action="refresh",
    )


def _organization_permission_error(
    *,
    code: str,
    message: str,
    organization_id: str | None = None,
    actor_role: str | None = None,
    target_role: str | None = None,
    current_role: str | None = None,
    member_id: str | None = None,
) -> AppError:
    data: dict[str, object] = {}
    if organization_id is not None:
        data["organization_id"] = organization_id
    if actor_role is not None:
        data["actor_role"] = actor_role
    if target_role is not None:
        data["target_role"] = target_role
    if current_role is not None:
        data["current_role"] = current_role
    if member_id is not None:
        data["member_id"] = member_id
    return AccessDeniedError(
        code=code,
        message=message,
        data=data,
        source="auth",
        user_action="request_access",
    )


VALID_MEMBER_ROLES = {"owner", "admin", "developer", "member", "viewer"}


def _validate_member_role(role: str) -> str:
    normalized = role.strip().lower()
    if normalized == "member":
        normalized = "developer"
    if normalized not in VALID_MEMBER_ROLES:
        raise InvalidRequestError(
            code="ORGANIZATION_MEMBER_ROLE_INVALID",
            message="Invalid member role",
            data={"role": role, "allowed": sorted(VALID_MEMBER_ROLES)},
            user_action="fix_input",
        )
    return normalized


def _role_rank(role: str) -> int:
    return JoySafeterRole.normalize(role).rank


def _ensure_can_assign_role(actor_role: str, target_role: str) -> None:
    if target_role == "owner" and actor_role != "owner":
        raise _organization_permission_error(
            code="ORGANIZATION_OWNER_ROLE_ASSIGN_FORBIDDEN",
            message="Only organization owners can assign owner role",
            actor_role=actor_role,
            target_role=target_role,
        )
    if _role_rank(actor_role) < _role_rank(target_role):
        raise _organization_permission_error(
            code="ORGANIZATION_ROLE_GRANT_FORBIDDEN",
            message="Cannot grant a role higher than your own",
            actor_role=actor_role,
            target_role=target_role,
        )


def _ensure_can_modify_member(actor_role: str, current_role: str, new_role: str) -> None:
    if current_role == "owner" and new_role != "owner":
        raise _organization_permission_error(
            code="ORGANIZATION_OWNER_ROLE_CHANGE_FORBIDDEN",
            message="Cannot change the organization owner role",
            actor_role=actor_role,
            current_role=current_role,
            target_role=new_role,
        )
    if actor_role != "owner" and new_role == "owner":
        raise _organization_permission_error(
            code="ORGANIZATION_OWNER_ROLE_ASSIGN_FORBIDDEN",
            message="Only organization owners can assign owner role",
            actor_role=actor_role,
            target_role=new_role,
        )
    if _role_rank(actor_role) < _role_rank(current_role) or _role_rank(actor_role) < _role_rank(new_role):
        raise _organization_permission_error(
            code="ORGANIZATION_ROLE_MODIFY_FORBIDDEN",
            message="Cannot modify or grant a role higher than your own",
            actor_role=actor_role,
            current_role=current_role,
            target_role=new_role,
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
    member_result = await db.execute(
        select(Member).where(
            Member.organization_id == organization_id,
            Member.user_id == current_user.id,
        )
    )
    if not member_result.scalar_one_or_none():
        raise _organization_permission_error(
            code="ORGANIZATION_ACCESS_DENIED",
            message="No access to organization",
            organization_id=organization_id,
        )

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
    result = await db.execute(
        select(Member).where(
            Member.organization_id == organization_id,
            Member.user_id == current_user.id,
            Member.role.in_(["owner", "admin"]),
        )
    )
    actor = result.scalar_one_or_none()
    if not actor:
        raise _organization_permission_error(
            code="ORGANIZATION_PERMISSION_DENIED",
            message="Insufficient permission",
            organization_id=organization_id,
        )

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
    result = await db.execute(
        select(Member).where(
            Member.organization_id == organization_id,
            Member.user_id == current_user.id,
            Member.role == "owner",
        )
    )
    if not result.scalar_one_or_none():
        raise _organization_permission_error(
            code="ORGANIZATION_OWNER_REQUIRED",
            message="Only the organization owner can delete it",
            organization_id=organization_id,
        )

    result = await db.execute(select(Organization).where(Organization.id == organization_id))
    org = result.scalar_one_or_none()
    if not org:
        raise _organization_not_found_error(organization_id)

    # Delete all members
    await db.execute(select(Member).where(Member.organization_id == organization_id))
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
        raise _organization_permission_error(
            code="ORGANIZATION_OWNER_REQUIRED",
            message="Only the organization owner can transfer ownership",
            organization_id=organization_id,
        )

    if req.new_owner_user_id == current_user.id:
        raise InvalidRequestError(
            code="ORGANIZATION_OWNER_TRANSFER_SELF",
            message="Cannot transfer ownership to yourself",
            data={"organization_id": organization_id, "user_id": current_user.id},
            user_action="fix_input",
        )

    result = await db.execute(
        select(Member).where(
            Member.organization_id == organization_id,
            Member.user_id == req.new_owner_user_id,
        )
    )
    new_owner = result.scalar_one_or_none()
    if not new_owner:
        raise NotFoundError(
            code="ORGANIZATION_MEMBER_NOT_FOUND",
            message="New owner must be an existing organization member",
            data={"organization_id": organization_id, "user_id": req.new_owner_user_id},
            user_action="fix_input",
        )

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
        raise _organization_permission_error(
            code="ORGANIZATION_ACCESS_DENIED",
            message="No access to organization",
            organization_id=organization_id,
        )

    result = await db.execute(select(Member).where(Member.organization_id == organization_id))
    members = result.scalars().all()

    data = []
    for m in members:
        user = m.user
        data.append(
            {
                "id": m.id,
                "user_id": m.user_id,
                "organization_id": m.organization_id,
                "role": m.role,
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
        raise _organization_permission_error(
            code="ORGANIZATION_PERMISSION_DENIED",
            message="Insufficient permission",
            organization_id=organization_id,
        )
    _ensure_can_assign_role(actor.role, role)

    existing = await db.execute(
        select(Member).where(
            Member.organization_id == organization_id,
            Member.user_id == req.user_id,
        )
    )
    if existing.scalar_one_or_none():
        raise ResourceConflictError(
            code="ORGANIZATION_MEMBER_ALREADY_EXISTS",
            message="User is already a member",
            data={"organization_id": organization_id, "user_id": req.user_id},
            user_action="refresh",
        )

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
        raise _organization_permission_error(
            code="ORGANIZATION_PERMISSION_DENIED",
            message="Insufficient permission",
            organization_id=organization_id,
        )

    result = await db.execute(select(Member).where(Member.id == member_id, Member.organization_id == organization_id))
    member = result.scalar_one_or_none()
    if not member:
        raise _organization_member_not_found_error(organization_id, member_id)

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
        raise _organization_permission_error(
            code="ORGANIZATION_PERMISSION_DENIED",
            message="Insufficient permission",
            organization_id=organization_id,
        )

    result = await db.execute(select(Member).where(Member.id == member_id, Member.organization_id == organization_id))
    member = result.scalar_one_or_none()
    if not member:
        raise _organization_member_not_found_error(organization_id, member_id)

    if member.role == "owner":
        raise InvalidRequestError(
            code="ORGANIZATION_OWNER_REMOVE_FORBIDDEN",
            message="Cannot remove the owner",
            data={"organization_id": organization_id, "member_id": member_id},
            user_action="fix_input",
        )
    if _role_rank(actor.role) < _role_rank(member.role):
        raise _organization_permission_error(
            code="ORGANIZATION_ROLE_REMOVE_FORBIDDEN",
            message="Cannot remove a member with a higher role than your own",
            organization_id=organization_id,
            actor_role=actor.role,
            current_role=member.role,
            member_id=member_id,
        )

    await db.delete(member)
    await db.commit()
