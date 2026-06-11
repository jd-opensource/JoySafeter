"""
JoySafeter auth routes — /auth endpoints for user context, projects, and API keys.
"""

import re
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    JoySafeterRole,
    get_joysafeter_auth_context,
    require_joysafeter_admin,
    require_joysafeter_write,
)
from app.joysafeter_shared.database import get_db
from app.joysafeter_domain.models.auth import AuthUser
from app.joysafeter_domain.models.organization import Member, Organization
from app.joysafeter_domain.models.project import Project
from app.joysafeter_api.services import ApiKeyService
from app.joysafeter_api.services import ProjectService

router = APIRouter(tags=["joysafeter-auth"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AuthMeResponse(BaseModel):
    user_id: str
    org_id: str
    project_id: str
    role: str
    org_name: Optional[str] = None
    project_name: Optional[str] = None


class SwitchContextRequest(BaseModel):
    org_id: Optional[str] = None
    project_id: Optional[str] = None


class SwitchContextResponse(BaseModel):
    user_id: str
    org_id: str
    project_id: str
    role: str


class ProjectResponse(BaseModel):
    id: str
    org_id: str
    name: str
    slug: str
    is_default: bool
    archived_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class CreateProjectRequest(BaseModel):
    name: str
    slug: str


class ApiKeyResponse(BaseModel):
    id: str
    project_id: str
    name: str
    key_prefix: str
    role: str
    created_at: Optional[str] = None
    last_used_at: Optional[str] = None


class ApiKeyCreateResponse(BaseModel):
    """Response for API key creation — includes the raw key (shown only once)."""
    id: str
    project_id: str
    name: str
    key_prefix: str
    role: str
    raw_key: str


class CreateApiKeyRequest(BaseModel):
    name: str
    role: str = "developer"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _project_to_response(project: Project) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        org_id=project.org_id,
        name=project.name,
        slug=project.slug,
        is_default=project.is_default,
        archived_at=str(project.archived_at) if project.archived_at else None,
        created_at=str(project.created_at) if project.created_at else None,
        updated_at=str(project.updated_at) if project.updated_at else None,
    )


def _api_key_to_response(key) -> ApiKeyResponse:
    return ApiKeyResponse(
        id=str(key.id),
        project_id=key.project_id,
        name=key.name,
        key_prefix=key.key_prefix,
        role=key.role,
        created_at=str(key.created_at) if key.created_at else None,
        last_used_at=str(key.last_used_at) if key.last_used_at else None,
    )


def _normalize_assignable_role(role: str) -> JoySafeterRole:
    normalized = (role or "").strip().lower()
    if normalized == "member":
        normalized = "developer"
    if normalized not in {JoySafeterRole.ADMIN.value, JoySafeterRole.DEVELOPER.value, JoySafeterRole.VIEWER.value}:
        raise HTTPException(
            400,
            "无效角色，必须为以下之一 / Invalid role. Must be one of: admin, developer, viewer",
        )
    return JoySafeterRole(normalized)


def _ensure_can_assign_role(actor_role: JoySafeterRole, target_role: JoySafeterRole) -> None:
    if not actor_role.can_grant(target_role):
        raise HTTPException(403, "不能授予高于自身权限的角色 / Cannot grant a role higher than your own")


def _ensure_can_modify_member(actor_role: JoySafeterRole, current_role: str, new_role: JoySafeterRole) -> None:
    current = JoySafeterRole.normalize(current_role)
    if current == JoySafeterRole.OWNER:
        raise HTTPException(403, "无法修改所有者的角色 / Cannot change the owner's role")
    if not actor_role.can_grant(current) or not actor_role.can_grant(new_role):
        raise HTTPException(403, "不能修改或授予高于自身权限的角色 / Cannot modify or grant a role higher than your own")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/me")
async def get_me(
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
):
    """Return current user + org + project info in the format expected by the frontend."""
    # Look up user
    user_result = await db.execute(
        select(AuthUser).where(AuthUser.id == auth_ctx.user_id).limit(1)
    )
    user = user_result.scalar_one_or_none()

    # Look up current org
    org_result = await db.execute(
        select(Organization).where(Organization.id == auth_ctx.org_id).limit(1)
    )
    org = org_result.scalar_one_or_none()

    # Look up current project
    proj_result = await db.execute(
        select(Project).where(Project.id == auth_ctx.project_id).limit(1)
    )
    proj = proj_result.scalar_one_or_none()

    # List all orgs user belongs to
    all_members_result = await db.execute(
        select(Member, Organization)
        .join(Organization, Member.organization_id == Organization.id)
        .where(Member.user_id == auth_ctx.user_id)
    )
    all_memberships = all_members_result.all()
    organizations = [
        {"id": o.id, "name": o.name, "slug": o.slug, "role": m.role, "created_at": o.created_at.isoformat() if o.created_at else None}
        for m, o in all_memberships
    ]

    # List all projects in current org
    all_projects_result = await db.execute(
        select(Project).where(Project.org_id == auth_ctx.org_id, Project.archived_at.is_(None))
    )
    all_projects = all_projects_result.scalars().all()
    projects = [
        {"id": p.id, "name": p.name, "slug": p.slug, "is_default": p.is_default}
        for p in all_projects
    ]

    return {
        "user": {
            "id": user.id if user else auth_ctx.user_id,
            "email": user.email if user else "",
            "name": user.name if user else "",
        },
        "organization": {
            "id": org.id if org else auth_ctx.org_id,
            "name": org.name if org else "",
            "slug": org.slug if org else "",
            "role": auth_ctx.role.value,
        },
        "project": {
            "id": proj.id if proj else auth_ctx.project_id,
            "name": proj.name if proj else "",
            "slug": proj.slug if proj else "",
            "is_default": proj.is_default if proj else True,
        },
        "organizations": organizations,
        "projects": projects,
    }


@router.post("/switch-context")
async def switch_context(
    req: SwitchContextRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
):
    """Switch the user's active org/project context. Validates membership."""
    target_org_id = req.org_id or auth_ctx.org_id

    # Validate user is a member of the target org
    member_result = await db.execute(
        select(Member).where(
            Member.user_id == auth_ctx.user_id,
            Member.organization_id == target_org_id,
        ).limit(1)
    )
    member = member_result.scalar_one_or_none()
    if not member:
        raise HTTPException(403, "User is not a member of the target organization")

    # Resolve project
    target_project_id = req.project_id
    if not target_project_id:
        proj_svc = ProjectService(db)
        default_proj = await proj_svc.get_default_project(target_org_id)
        if not default_proj:
            raise HTTPException(404, "No default project found for the organization")
        target_project_id = default_proj.id
    else:
        proj_result = await db.execute(
            select(Project).where(
                Project.id == target_project_id,
                Project.org_id == target_org_id,
            ).limit(1)
        )
        proj = proj_result.scalar_one_or_none()
        if not proj:
            raise HTTPException(404, "Project not found in the target organization")

    # Fetch resolved project details
    proj_result = await db.execute(
        select(Project).where(Project.id == target_project_id).limit(1)
    )
    resolved_project = proj_result.scalar_one_or_none()

    # List all projects in target org
    all_projects_result = await db.execute(
        select(Project).where(Project.org_id == target_org_id, Project.archived_at.is_(None))
    )
    all_projects = all_projects_result.scalars().all()

    # Issue new JWT with updated org/project context
    from app.joysafeter_shared.security import create_access_token
    new_access_token = create_access_token(
        subject=auth_ctx.user_id,
        org_id=target_org_id,
        project_id=target_project_id,
        role=JoySafeterRole.normalize(member.role).value,
    )

    return {
        "access_token": new_access_token,
        "project": {
            "id": resolved_project.id if resolved_project else target_project_id,
            "name": resolved_project.name if resolved_project else "",
            "slug": resolved_project.slug if resolved_project else "",
            "is_default": resolved_project.is_default if resolved_project else False,
        },
        "projects": [
            {"id": p.id, "name": p.name, "slug": p.slug, "is_default": p.is_default}
            for p in all_projects
        ],
    }


@router.get("/projects")
async def list_projects(
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> list[ProjectResponse]:
    """List projects for the current org."""
    svc = ProjectService(db)
    projects = await svc.list_projects(auth_ctx.org_id, include_archived=include_archived)
    return [_project_to_response(p) for p in projects]


@router.post("/projects", status_code=201)
async def create_project(
    req: CreateProjectRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_admin),
) -> ProjectResponse:
    """Create a new project (requires admin role)."""
    svc = ProjectService(db)
    project = await svc.create_project(
        org_id=auth_ctx.org_id,
        name=req.name,
        slug=req.slug,
    )
    return _project_to_response(project)


@router.get("/api-keys")
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> list[ApiKeyResponse]:
    """List API keys for the current project."""
    svc = ApiKeyService(db)
    keys = await svc.list_project_keys(auth_ctx.project_id)
    return [_api_key_to_response(k) for k in keys]


@router.post("/api-keys", status_code=201)
async def create_api_key(
    req: CreateApiKeyRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> ApiKeyCreateResponse:
    """Create a new API key. Returns the raw key once."""
    role = _normalize_assignable_role(req.role)
    _ensure_can_assign_role(auth_ctx.role, role)
    svc = ApiKeyService(db)
    api_key, raw_key = await svc.create_api_key(
        project_id=auth_ctx.project_id,
        org_id=auth_ctx.org_id,
        name=req.name,
        created_by=auth_ctx.user_id,
        role=role.value,
    )
    return ApiKeyCreateResponse(
        id=str(api_key.id),
        project_id=api_key.project_id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        role=api_key.role,
        raw_key=raw_key,
    )


@router.delete("/api-keys/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> None:
    """Revoke an API key."""
    svc = ApiKeyService(db)
    try:
        await svc.revoke_key(key_id, auth_ctx.project_id)
    except ValueError:
        raise HTTPException(404, "API key not found")


# ---------------------------------------------------------------------------
# Project detail routes
# ---------------------------------------------------------------------------


@router.get("/projects/{project_id}")
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> ProjectResponse:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.org_id == auth_ctx.org_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(404, "Project not found")
    return _project_to_response(project)


class UpdateProjectRequest(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None


@router.patch("/projects/{project_id}")
async def update_project(
    project_id: str,
    req: UpdateProjectRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_admin),
) -> ProjectResponse:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.org_id == auth_ctx.org_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(404, "Project not found")
    if req.name is not None:
        project.name = req.name
    if req.slug is not None:
        project.slug = req.slug
    await db.commit()
    await db.refresh(project)
    return _project_to_response(project)


@router.delete("/projects/{project_id}")
async def archive_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_admin),
) -> dict:
    from datetime import datetime, timezone
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.org_id == auth_ctx.org_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(404, "Project not found")
    if project.is_default:
        raise HTTPException(400, "Cannot archive the default project")
    project.archived_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "archived"}


@router.post("/projects/{project_id}/set-default")
async def set_default_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_admin),
) -> ProjectResponse:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.org_id == auth_ctx.org_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(404, "Project not found")
    # Unset current default
    all_projects_result = await db.execute(
        select(Project).where(Project.org_id == auth_ctx.org_id, Project.is_default.is_(True))
    )
    for p in all_projects_result.scalars().all():
        p.is_default = False
    project.is_default = True
    await db.commit()
    await db.refresh(project)
    return _project_to_response(project)


# ---------------------------------------------------------------------------
# User search (for member invite)
# ---------------------------------------------------------------------------


@router.get("/search-users")
async def search_users(
    q: str = Query("", min_length=1, max_length=100),
    limit: int = Query(10, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_admin),
):
    """Search users by email or name for member invitation."""
    from sqlalchemy import or_

    search = f"%{q}%"
    result = await db.execute(
        select(AuthUser)
        .where(
            or_(
                AuthUser.email.ilike(search),
                AuthUser.name.ilike(search),
            )
        )
        .limit(limit)
    )
    users = result.scalars().all()

    existing_result = await db.execute(
        select(Member.user_id).where(Member.organization_id == auth_ctx.org_id)
    )
    existing_ids = {row[0] for row in existing_result.all()}

    return [
        {
            "id": u.id,
            "email": u.email,
            "name": u.name or "",
            "image": u.image,
            "already_member": u.id in existing_ids,
        }
        for u in users
    ]


# ---------------------------------------------------------------------------
# Organization Management
# ---------------------------------------------------------------------------


class CreateOrganizationRequest(BaseModel):
    name: str


class OrganizationResponse(BaseModel):
    id: str
    name: str
    slug: str
    created_at: Optional[str] = None


class MemberResponse(BaseModel):
    user_id: str
    email: str
    display_name: str
    role: str
    joined_at: Optional[str] = None


class InviteMemberRequest(BaseModel):
    email: str
    role: str = "member"


class UpdateMemberRoleRequest(BaseModel):
    role: str


def _slugify(name: str) -> str:
    """Generate a URL-friendly slug from a name."""
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    if not slug:
        slug = "org"
    # Append short unique suffix to avoid collisions
    slug = f"{slug}-{uuid.uuid4().hex[:6]}"
    return slug


@router.post("/organizations", status_code=201)
async def create_organization(
    req: CreateOrganizationRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> OrganizationResponse:
    """Create a new organization. The current user becomes the owner."""
    if not req.name or not req.name.strip():
        raise HTTPException(400, "Organization name is required")

    slug = _slugify(req.name)

    # Create organization
    org = Organization(name=req.name.strip(), slug=slug)
    db.add(org)
    await db.flush()

    # Create owner membership
    member = Member(
        user_id=auth_ctx.user_id,
        organization_id=org.id,
        role="owner",
    )
    db.add(member)

    # Create default project
    project = Project(
        org_id=org.id,
        name="Default",
        slug="default",
        is_default=True,
    )
    db.add(project)

    await db.commit()
    await db.refresh(org)

    return OrganizationResponse(
        id=org.id,
        name=org.name,
        slug=org.slug,
        created_at=str(org.created_at) if org.created_at else None,
    )


@router.get("/members")
async def list_members(
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> list[MemberResponse]:
    """List members of the current organization."""
    result = await db.execute(
        select(Member, AuthUser)
        .join(AuthUser, Member.user_id == AuthUser.id)
        .where(Member.organization_id == auth_ctx.org_id)
    )
    rows = result.all()
    return [
        MemberResponse(
            user_id=member.user_id,
            email=user.email,
            display_name=user.name,
            role=member.role,
            joined_at=str(member.created_at) if member.created_at else None,
        )
        for member, user in rows
    ]


@router.post("/members/invite", status_code=201)
async def invite_member(
    req: InviteMemberRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_admin),
) -> MemberResponse:
    """Invite a user to the current organization by email. Requires admin role."""
    # Look up user by email
    user_result = await db.execute(
        select(AuthUser).where(AuthUser.email == req.email.strip()).limit(1)
    )
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "未找到该邮箱对应的用户 / User not found with the given email")

    # Check if already a member
    existing = await db.execute(
        select(Member).where(
            Member.user_id == user.id,
            Member.organization_id == auth_ctx.org_id,
        ).limit(1)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "该用户已是组织成员 / User is already a member of this organization")

    role = _normalize_assignable_role(req.role)
    _ensure_can_assign_role(auth_ctx.role, role)

    member = Member(
        user_id=user.id,
        organization_id=auth_ctx.org_id,
        role=role.value,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)

    return MemberResponse(
        user_id=user.id,
        email=user.email,
        display_name=user.name,
        role=member.role,
        joined_at=str(member.created_at) if member.created_at else None,
    )


@router.delete("/members/{user_id}", status_code=204)
async def remove_member(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_admin),
) -> None:
    """Remove a member from the current organization. Cannot remove the owner."""
    # Find the member
    result = await db.execute(
        select(Member).where(
            Member.user_id == user_id,
            Member.organization_id == auth_ctx.org_id,
        ).limit(1)
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(404, "Member not found")

    _ensure_can_modify_member(auth_ctx.role, member.role, JoySafeterRole.VIEWER)

    await db.execute(
        sa_delete(Member).where(
            Member.user_id == user_id,
            Member.organization_id == auth_ctx.org_id,
        )
    )
    await db.commit()


@router.put("/members/{user_id}")
async def update_member_role(
    user_id: str,
    req: UpdateMemberRoleRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_admin),
) -> MemberResponse:
    """Update a member's role. Cannot change the owner's role."""
    # Find the member
    result = await db.execute(
        select(Member).where(
            Member.user_id == user_id,
            Member.organization_id == auth_ctx.org_id,
        ).limit(1)
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(404, "Member not found")

    new_role = _normalize_assignable_role(req.role)
    _ensure_can_modify_member(auth_ctx.role, member.role, new_role)

    member.role = new_role.value
    await db.commit()
    await db.refresh(member)

    # Fetch user info
    user_result = await db.execute(
        select(AuthUser).where(AuthUser.id == user_id).limit(1)
    )
    user = user_result.scalar_one_or_none()

    return MemberResponse(
        user_id=member.user_id,
        email=user.email if user else "",
        display_name=user.name if user else "",
        role=member.role,
        joined_at=str(member.created_at) if member.created_at else None,
    )
