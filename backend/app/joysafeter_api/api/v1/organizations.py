"""Organization management API.

Provides CRUD for organizations and member management,
aligned with the unified Organization + Project model.
"""

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.joysafeter_api.api.v1.audit import audit_joysafeter_event
from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Member, Organization
from app.joysafeter_domain.pagination import apply_created_at_desc_cursor
from app.joysafeter_domain.services.joysafeter_organization_member_service import OrganizationMemberService
from app.joysafeter_domain.services.joysafeter_organization_service import OrganizationService
from app.joysafeter_shared.common.app_errors import (
    AppError,
    NotFoundError,
)
from app.joysafeter_shared.common.dependencies import CurrentUser
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.database import get_db

router = APIRouter(tags=["joysafeter-organizations"])


class CreateOrganizationRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: Optional[str] = None


class UpdateOrganizationRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    logo: Optional[str] = None
    project_creation_policy: Optional[Literal["admins_only", "all_members"]] = None


class AddMemberRequest(BaseModel):
    email: str
    role: str = "member"


class UpdateMemberRoleRequest(BaseModel):
    role: str


class TransferOwnershipRequest(BaseModel):
    new_owner_user_id: str


class OrganizationResponse(BaseModel):
    id: str
    name: str
    slug: str
    logo: Optional[str] = None
    project_id: Optional[str] = None
    project_creation_policy: str = "admins_only"
    created_at: str


class OrganizationListItem(BaseModel):
    id: str
    name: str
    slug: str
    logo: Optional[str] = None
    role: str
    owner_name: Optional[str] = None
    owner_email: Optional[str] = None
    project_creation_policy: str = "admins_only"
    created_at: Optional[str] = None


class PaginatedOrganizationsResponse(BaseModel):
    data: list[OrganizationListItem]
    has_more: bool
    first_id: Optional[str] = None
    last_id: Optional[str] = None


class MemberResponse(BaseModel):
    id: str
    user_id: str
    organization_id: str
    role: str
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    joined_at: Optional[str] = None


class PaginatedMembersResponse(BaseModel):
    data: list[MemberResponse]
    has_more: bool
    first_id: Optional[str] = None
    last_id: Optional[str] = None


class MemberCandidateResponse(BaseModel):
    id: str
    email: str
    name: str
    image: Optional[str] = None
    already_member: bool


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
    q: str = Query("", max_length=100),
    limit: int = Query(50, ge=1, le=200),
    after_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PaginatedOrganizationsResponse:
    owner_membership = aliased(Member)
    owner_user = aliased(AuthUser)
    query = (
        select(Organization, Member, owner_user)
        .join(Member, Member.organization_id == Organization.id)
        .outerjoin(
            owner_membership,
            and_(
                owner_membership.organization_id == Organization.id,
                owner_membership.role == JoySafeterRole.OWNER.value,
            ),
        )
        .outerjoin(owner_user, owner_user.id == owner_membership.user_id)
        .where(Member.user_id == current_user.id)
    )
    if q.strip():
        pattern = f"%{q.strip()}%"
        query = query.where(
            or_(
                Organization.id.ilike(pattern),
                Organization.name.ilike(pattern),
                Organization.slug.ilike(pattern),
                owner_user.name.ilike(pattern),
                owner_user.email.ilike(pattern),
            )
        )
    query = apply_created_at_desc_cursor(query, Organization, after_id).limit(limit + 1)
    result = await db.execute(query)
    rows = result.all()
    page_rows = rows[:limit]
    return PaginatedOrganizationsResponse(
        data=[
            OrganizationListItem(
                id=org.id,
                name=org.name,
                slug=org.slug,
                logo=org.logo,
                role=JoySafeterRole.normalize(member.role).value,
                owner_name=owner.name if owner else None,
                owner_email=owner.email if owner else None,
                project_creation_policy=org.project_creation_policy,
                created_at=org.created_at.isoformat() if org.created_at else None,
            )
            for org, member, owner in page_rows
        ],
        has_more=len(rows) > limit,
        first_id=page_rows[0][0].id if page_rows else None,
        last_id=page_rows[-1][0].id if page_rows else None,
    )


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
        "project_creation_policy": org.project_creation_policy,
        "created_at": org.created_at.isoformat() if org.created_at else None,
    }


@router.get("/{organization_id}")
async def get_organization(
    organization_id: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    membership = await OrganizationMemberService(db).require_membership(organization_id, current_user.id)

    owner_membership = aliased(Member)
    owner_user = aliased(AuthUser)
    org_result = await db.execute(
        select(Organization, owner_user)
        .outerjoin(
            owner_membership,
            and_(
                owner_membership.organization_id == Organization.id,
                owner_membership.role == JoySafeterRole.OWNER.value,
            ),
        )
        .outerjoin(owner_user, owner_user.id == owner_membership.user_id)
        .where(Organization.id == organization_id)
    )
    row = org_result.one_or_none()
    if not row:
        raise _organization_not_found_error(organization_id)
    org, owner = row

    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "logo": org.logo,
        "project_creation_policy": org.project_creation_policy,
        "role": JoySafeterRole.normalize(membership.role).value,
        "owner_name": owner.name if owner else None,
        "owner_email": owner.email if owner else None,
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
    if req.project_creation_policy is not None:
        org.project_creation_policy = req.project_creation_policy

    await db.commit()
    await db.refresh(org)
    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "logo": org.logo,
        "project_creation_policy": org.project_creation_policy,
    }


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
    q: str = Query("", max_length=100),
    limit: int = Query(50, ge=1, le=200),
    after_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PaginatedMembersResponse:
    member_svc = OrganizationMemberService(db)
    await member_svc.require_membership(organization_id, current_user.id)
    rows, has_more = await member_svc.list_members_page(
        organization_id,
        limit=limit,
        after_id=after_id,
        q=q,
    )
    return PaginatedMembersResponse(
        data=[
            MemberResponse(
                id=item.member.id,
                user_id=item.member.user_id,
                organization_id=item.member.organization_id,
                role=item.member.role,
                user_name=item.user.name,
                user_email=item.user.email,
                joined_at=str(item.member.created_at) if item.member.created_at else None,
            )
            for item in rows
        ],
        has_more=has_more,
        first_id=rows[0].member.id if rows else None,
        last_id=rows[-1].member.id if rows else None,
    )


@router.get("/{organization_id}/member-candidates")
async def search_member_candidates(
    organization_id: str,
    current_user: CurrentUser,
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(10, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
) -> list[MemberCandidateResponse]:
    member_svc = OrganizationMemberService(db)
    await member_svc.require_member_manager(organization_id, current_user.id)
    search = f"%{q.strip()}%"
    result = await db.execute(
        select(AuthUser).where(or_(AuthUser.email.ilike(search), AuthUser.name.ilike(search))).limit(limit)
    )
    users = result.scalars().all()
    existing_result = await db.execute(select(Member.user_id).where(Member.organization_id == organization_id))
    existing_ids = {row[0] for row in existing_result.all()}
    return [
        MemberCandidateResponse(
            id=user.id,
            email=user.email,
            name=user.name or "",
            image=user.image,
            already_member=user.id in existing_ids,
        )
        for user in users
    ]


@router.post("/{organization_id}/members", status_code=201)
async def add_member(
    organization_id: str,
    req: AddMemberRequest,
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MemberResponse:
    member_svc = OrganizationMemberService(db)
    actor = await member_svc.require_member_manager(organization_id, current_user.id)
    member, user = await member_svc.add_existing_member_by_email(
        organization_id=organization_id,
        actor_role=JoySafeterRole.normalize(actor.role),
        email=req.email,
        role=req.role,
    )
    await audit_joysafeter_event(
        db,
        request,
        JoySafeterAuthContext(
            user_id=current_user.id,
            org_id=organization_id,
            project_id=None,  # type: ignore[arg-type]
            role=JoySafeterRole.normalize(actor.role),
        ),
        event_type="member.added",
        target_type="organization_member",
        target_id=user.id,
        details={"target_email": user.email, "assigned_role": member.role},
    )
    return MemberResponse(
        id=member.id,
        user_id=member.user_id,
        organization_id=member.organization_id,
        role=member.role,
        user_name=user.name,
        user_email=user.email,
        joined_at=str(member.created_at) if member.created_at else None,
    )


@router.put("/{organization_id}/members/{user_id}")
async def update_member_role(
    organization_id: str,
    user_id: str,
    req: UpdateMemberRoleRequest,
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MemberResponse:
    member_svc = OrganizationMemberService(db)
    actor = await member_svc.require_member_manager(organization_id, current_user.id)
    existing_member = await member_svc.get_member_by_user_id(organization_id, user_id)
    previous_role = existing_member.role if existing_member is not None else None
    member = await member_svc.update_member_role_by_user_id(
        organization_id=organization_id,
        user_id=user_id,
        actor_user_id=current_user.id,
        actor_role=JoySafeterRole.normalize(actor.role),
        role=req.role,
    )
    user = (await db.execute(select(AuthUser).where(AuthUser.id == user_id).limit(1))).scalar_one_or_none()
    await audit_joysafeter_event(
        db,
        request,
        JoySafeterAuthContext(
            user_id=current_user.id,
            org_id=organization_id,
            project_id=None,  # type: ignore[arg-type]
            role=JoySafeterRole.normalize(actor.role),
        ),
        event_type="member.role_updated",
        target_type="organization_member",
        target_id=user_id,
        details={"previous_role": previous_role, "new_role": member.role},
    )
    return MemberResponse(
        id=member.id,
        user_id=member.user_id,
        organization_id=member.organization_id,
        role=member.role,
        user_name=user.name if user else None,
        user_email=user.email if user else None,
        joined_at=str(member.created_at) if member.created_at else None,
    )


@router.delete("/{organization_id}/members/{user_id}", status_code=204)
async def remove_member(
    organization_id: str,
    user_id: str,
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    member_svc = OrganizationMemberService(db)
    actor = await member_svc.require_member_manager(organization_id, current_user.id)
    member = await member_svc.remove_member_by_user_id(
        organization_id=organization_id,
        user_id=user_id,
        actor_user_id=current_user.id,
        actor_role=JoySafeterRole.normalize(actor.role),
    )
    await audit_joysafeter_event(
        db,
        request,
        JoySafeterAuthContext(
            user_id=current_user.id,
            org_id=organization_id,
            project_id=None,  # type: ignore[arg-type]
            role=JoySafeterRole.normalize(actor.role),
        ),
        event_type="member.removed",
        target_type="organization_member",
        target_id=user_id,
        details={"previous_role": member.role},
    )
