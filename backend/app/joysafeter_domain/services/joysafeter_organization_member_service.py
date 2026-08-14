from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Member
from app.joysafeter_domain.pagination import apply_created_at_desc_cursor
from app.joysafeter_domain.services.joysafeter_project_service import ProjectService
from app.joysafeter_shared.common.app_errors import (
    AccessDeniedError,
    InvalidRequestError,
    NotFoundError,
    ResourceConflictError,
)
from app.joysafeter_shared.common.joysafeter_auth.context import JoySafeterRole

# Org roles are the 3-tier vocabulary (owner/admin/member); derive the valid and
# assignable sets from the enum so there is one source of truth.
VALID_MEMBER_ROLES = frozenset(r.value for r in JoySafeterRole)
NON_OWNER_ASSIGNABLE_ROLES = frozenset(r.value for r in JoySafeterRole if r is not JoySafeterRole.OWNER)


@dataclass(frozen=True)
class MemberWithUser:
    member: Member
    user: AuthUser


def _permission_error(
    *,
    code: str,
    message: str,
    organization_id: str | None = None,
    actor_role: str | None = None,
    target_role: str | None = None,
    current_role: str | None = None,
    member_id: str | None = None,
) -> AccessDeniedError:
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


def _normalize_role_value(role: str) -> str:
    return (role or "").strip().lower()


def validate_member_role(role: str, *, allow_owner: bool = True) -> str:
    normalized = _normalize_role_value(role)
    allowed = VALID_MEMBER_ROLES if allow_owner else NON_OWNER_ASSIGNABLE_ROLES
    if normalized not in {_normalize_role_value(value) for value in allowed}:
        raise InvalidRequestError(
            code="ORGANIZATION_MEMBER_ROLE_INVALID",
            message="Invalid member role",
            data={"role": role, "allowed": sorted(allowed)},
            user_action="fix_input",
        )
    return normalized


def validate_auth_assignable_role(role: str) -> JoySafeterRole:
    normalized = _normalize_role_value(role)
    allowed = [JoySafeterRole.ADMIN.value, JoySafeterRole.MEMBER.value]
    if normalized not in set(allowed):
        raise InvalidRequestError(
            code="AUTH_INVALID_ASSIGNABLE_ROLE",
            message="Invalid role. Must be one of: admin, member",
            data={"role": role, "allowed": allowed},
            source="auth",
            user_action="correct_request",
        )
    return JoySafeterRole(normalized)


def _actor_outranks(actor: "str | JoySafeterRole", target: "str | JoySafeterRole") -> bool:
    """True when ``actor`` may grant/modify/remove a principal holding ``target``.

    The single rank rule for org-member management (owner > admin > member; an
    actor may act on peers at or below their own rank). Delegates to
    ``JoySafeterRole.can_grant`` — the one authoritative rank comparison in
    ``context.py`` — so this module no longer carries its own rank arithmetic.
    Accepts either raw role strings (the ``organizations.py`` surface) or
    ``JoySafeterRole`` enums (the ``auth.py`` surface).
    """
    a = actor if isinstance(actor, JoySafeterRole) else JoySafeterRole.normalize(actor)
    t = target if isinstance(target, JoySafeterRole) else JoySafeterRole.normalize(target)
    return a.can_grant(t)


def ensure_can_assign_role(actor_role: str, target_role: str) -> None:
    if target_role == JoySafeterRole.OWNER.value and actor_role != JoySafeterRole.OWNER.value:
        raise _permission_error(
            code="ORGANIZATION_OWNER_ROLE_ASSIGN_FORBIDDEN",
            message="Only organization owners can assign owner role",
            actor_role=actor_role,
            target_role=target_role,
        )
    if not _actor_outranks(actor_role, target_role):
        raise _permission_error(
            code="ORGANIZATION_ROLE_GRANT_FORBIDDEN",
            message="Cannot grant a role higher than your own",
            actor_role=actor_role,
            target_role=target_role,
        )


def ensure_can_modify_auth_member(actor_role: JoySafeterRole, current_role: str, new_role: JoySafeterRole) -> None:
    current = JoySafeterRole.normalize(current_role)
    if current == JoySafeterRole.OWNER:
        raise _permission_error(
            code="AUTH_OWNER_ROLE_CHANGE_FORBIDDEN",
            message="Cannot change the owner's role",
            actor_role=actor_role.value,
            current_role=current.value,
            target_role=new_role.value,
        )
    if not actor_role.can_grant(current) or not actor_role.can_grant(new_role):
        raise _permission_error(
            code="AUTH_ROLE_MODIFY_FORBIDDEN",
            message="Cannot modify or grant a role higher than your own",
            actor_role=actor_role.value,
            current_role=current.value,
            target_role=new_role.value,
        )


class OrganizationMemberService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_member_by_user_id(self, organization_id: str, user_id: str) -> Member | None:
        result = await self.db.execute(
            select(Member)
            .where(
                Member.organization_id == organization_id,
                Member.user_id == user_id,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_members_with_users(self, organization_id: str) -> list[tuple[Member, AuthUser]]:
        result = await self.db.execute(
            select(Member, AuthUser)
            .join(AuthUser, Member.user_id == AuthUser.id)
            .where(Member.organization_id == organization_id)
        )
        return [(member, user) for member, user in result.all()]

    async def require_membership(self, organization_id: str, user_id: str) -> Member:
        member = await self.get_member_by_user_id(organization_id, user_id)
        if member is None:
            raise _permission_error(
                code="ORGANIZATION_ACCESS_DENIED",
                message="No access to organization",
                organization_id=organization_id,
            )
        return member

    async def require_member_manager(self, organization_id: str, user_id: str) -> Member:
        actor = await self.get_member_by_user_id(organization_id, user_id)
        if actor is None or JoySafeterRole.normalize(actor.role) not in (JoySafeterRole.OWNER, JoySafeterRole.ADMIN):
            raise _permission_error(
                code="ORGANIZATION_PERMISSION_DENIED",
                message="Insufficient permission",
                organization_id=organization_id,
            )
        return actor

    async def require_owner(self, organization_id: str, user_id: str, *, message: str) -> Member:
        actor = await self.get_member_by_user_id(organization_id, user_id)
        if actor is None or JoySafeterRole.normalize(actor.role) != JoySafeterRole.OWNER:
            raise _permission_error(
                code="ORGANIZATION_OWNER_REQUIRED",
                message=message,
                organization_id=organization_id,
            )
        return actor

    async def list_members(self, organization_id: str) -> list[MemberWithUser]:
        result = await self.db.execute(
            select(Member, AuthUser)
            .join(AuthUser, Member.user_id == AuthUser.id)
            .where(Member.organization_id == organization_id)
            .order_by(Member.created_at)
        )
        return [MemberWithUser(member=member, user=user) for member, user in result.all()]

    async def list_members_page(
        self,
        organization_id: str,
        *,
        limit: int,
        after_id: str | None = None,
        q: str = "",
    ) -> tuple[list[MemberWithUser], bool]:
        query = (
            select(Member, AuthUser)
            .join(AuthUser, Member.user_id == AuthUser.id)
            .where(Member.organization_id == organization_id)
        )
        if q.strip():
            pattern = f"%{q.strip()}%"
            query = query.where(
                or_(
                    Member.user_id.ilike(pattern),
                    AuthUser.email.ilike(pattern),
                    AuthUser.name.ilike(pattern),
                )
            )
        query = apply_created_at_desc_cursor(query, Member, after_id).limit(limit + 1)
        result = await self.db.execute(query)
        rows = [MemberWithUser(member=member, user=user) for member, user in result.all()]
        return rows[:limit], len(rows) > limit

    async def add_member(
        self,
        *,
        organization_id: str,
        user_id: str,
        actor_user_id: str,
        role: str,
        allow_owner_role: bool = True,
        duplicate_message: str = "User is already a member",
    ) -> Member:
        normalized_role = validate_member_role(role, allow_owner=allow_owner_role)
        actor = await self.require_member_manager(organization_id, actor_user_id)
        ensure_can_assign_role(actor.role, normalized_role)

        existing = await self.get_member_by_user_id(organization_id, user_id)
        if existing is not None:
            raise ResourceConflictError(
                code="ORGANIZATION_MEMBER_ALREADY_EXISTS",
                message=duplicate_message,
                data={"organization_id": organization_id, "user_id": user_id},
                user_action="refresh",
            )

        member = Member(
            user_id=user_id,
            organization_id=organization_id,
            role=normalized_role,
        )
        self.db.add(member)
        try:
            # grant_default_project_membership flushes, so the unique-constraint
            # violation can surface here or at commit — guard both.
            await ProjectService(self.db).grant_default_project_membership(
                org_id=organization_id,
                user_id=user_id,
                role=normalized_role,
            )
            await self.db.commit()
        except IntegrityError:
            # Lost a race with a concurrent add for the same (org, user): the
            # unique constraint fired. Surface the same conflict as the up-front
            # check rather than a 500.
            await self.db.rollback()
            raise ResourceConflictError(
                code="ORGANIZATION_MEMBER_ALREADY_EXISTS",
                message=duplicate_message,
                data={"organization_id": organization_id, "user_id": user_id},
                user_action="refresh",
            ) from None
        await self.db.refresh(member)
        return member

    async def invite_member_by_email(
        self,
        *,
        organization_id: str,
        actor_role: JoySafeterRole,
        email: str,
        role: str,
    ) -> tuple[Member, AuthUser]:
        normalized_role = validate_auth_assignable_role(role)
        if not actor_role.can_grant(normalized_role):
            raise _permission_error(
                code="AUTH_ROLE_GRANT_FORBIDDEN",
                message="Cannot grant a role higher than your own",
                actor_role=actor_role.value,
                target_role=normalized_role.value,
            )

        user_result = await self.db.execute(select(AuthUser).where(AuthUser.email == email.strip()).limit(1))
        user = user_result.scalar_one_or_none()
        if not user:
            raise NotFoundError(
                code="AUTH_USER_NOT_FOUND",
                message="User not found with the given email",
                data={"email": email.strip()},
                user_action="fix_input",
            )

        existing = await self.get_member_by_user_id(organization_id, user.id)
        if existing is not None:
            raise ResourceConflictError(
                code="ORGANIZATION_MEMBER_ALREADY_EXISTS",
                message="User is already a member of this organization",
                data={"organization_id": organization_id, "user_id": user.id},
                user_action="refresh",
            )

        member = Member(user_id=user.id, organization_id=organization_id, role=normalized_role.value)
        self.db.add(member)
        try:
            await ProjectService(self.db).grant_default_project_membership(
                org_id=organization_id,
                user_id=user.id,
                role=normalized_role.value,
            )
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise ResourceConflictError(
                code="ORGANIZATION_MEMBER_ALREADY_EXISTS",
                message="User is already a member of this organization",
                data={"organization_id": organization_id, "user_id": user.id},
                user_action="refresh",
            ) from None
        await self.db.refresh(member)
        return member, user

    async def _ensure_project_access_after_role_change(
        self,
        *,
        organization_id: str,
        user_id: str,
        new_role: str,
    ) -> None:
        # owner/admin reach every project without a ProjectMember row. An ordinary
        # member needs an explicit row, so when demoting from owner/admin — who may
        # have no rows at all — backfill the default project to avoid locking them
        # out. Existing explicit grants on other projects are preserved.
        if ProjectService.role_has_org_wide_project_access(new_role):
            return
        await ProjectService(self.db).grant_default_project_membership(
            org_id=organization_id,
            user_id=user_id,
            role=new_role,
        )

    async def update_member_role_by_user_id(
        self,
        *,
        organization_id: str,
        user_id: str,
        actor_role: JoySafeterRole,
        role: str,
    ) -> Member:
        member = await self.get_member_by_user_id(organization_id, user_id)
        if member is None:
            raise NotFoundError(
                code="ORGANIZATION_MEMBER_NOT_FOUND",
                message="Member not found",
                data={"organization_id": organization_id, "user_id": user_id},
                user_action="refresh",
            )

        new_role = validate_auth_assignable_role(role)
        ensure_can_modify_auth_member(actor_role, member.role, new_role)

        member.role = new_role.value
        await self._ensure_project_access_after_role_change(
            organization_id=organization_id,
            user_id=member.user_id,
            new_role=new_role.value,
        )
        await self.db.commit()
        await self.db.refresh(member)
        return member

    async def remove_member_by_user_id(
        self,
        *,
        organization_id: str,
        user_id: str,
        actor_role: JoySafeterRole,
    ) -> Member:
        member = await self.get_member_by_user_id(organization_id, user_id)
        if member is None:
            raise NotFoundError(
                code="ORGANIZATION_MEMBER_NOT_FOUND",
                message="Member not found",
                data={"organization_id": organization_id, "user_id": user_id},
                user_action="refresh",
            )

        ensure_can_modify_auth_member(actor_role, member.role, JoySafeterRole.MEMBER)
        await ProjectService(self.db).revoke_org_project_memberships(
            org_id=organization_id,
            user_id=member.user_id,
        )
        await self.db.delete(member)
        await self.db.commit()
        return member

    async def transfer_ownership(
        self,
        *,
        organization_id: str,
        current_owner_user_id: str,
        new_owner_user_id: str,
    ) -> tuple[Member, Member]:
        current_owner = await self.require_owner(
            organization_id,
            current_owner_user_id,
            message="Only the organization owner can transfer ownership",
        )
        if new_owner_user_id == current_owner_user_id:
            raise InvalidRequestError(
                code="ORGANIZATION_OWNER_TRANSFER_SELF",
                message="Cannot transfer ownership to yourself",
                data={"organization_id": organization_id, "user_id": current_owner_user_id},
                user_action="fix_input",
            )

        new_owner = await self.get_member_by_user_id(organization_id, new_owner_user_id)
        if new_owner is None:
            raise NotFoundError(
                code="ORGANIZATION_MEMBER_NOT_FOUND",
                message="New owner must be an existing organization member",
                data={"organization_id": organization_id, "user_id": new_owner_user_id},
                user_action="fix_input",
            )

        current_owner.role = JoySafeterRole.ADMIN.value
        new_owner.role = JoySafeterRole.OWNER.value
        await self.db.commit()
        await self.db.refresh(current_owner)
        await self.db.refresh(new_owner)
        return current_owner, new_owner
