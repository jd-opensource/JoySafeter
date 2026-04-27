"""
Organization and member service.
"""

import uuid
from typing import Dict, List, Optional

from pydantic import EmailStr

from app.common.app_errors import (
    AccessDeniedError,
    InvalidRequestError,
    NotFoundError,
    ResourceConflictError,
)
from app.models.auth import AuthUser as User
from app.models.enums import OrgRole
from app.models.organization import Member, Organization
from app.repositories.organization import MemberRepository, OrganizationRepository
from app.repositories.user import UserRepository

from .base import BaseService


class OrganizationService(BaseService[Organization]):
    """Organization and member business logic."""

    TEAM_PLAN = "team"
    SUPPORTED_ROLES = {OrgRole.OWNER, OrgRole.ADMIN, OrgRole.MEMBER}

    def __init__(self, db):
        super().__init__(db)
        self.org_repo = OrganizationRepository(db)
        self.member_repo = MemberRepository(db)
        self.user_repo = UserRepository(db)

    # --------------------------------------------------------------------- #
    # organization
    # --------------------------------------------------------------------- #
    async def create_organization(
        self,
        *,
        name: str,
        slug: str,
        logo: Optional[str],
        current_user: User,
    ) -> Dict:
        """Create an organization and set the current user as owner."""
        if await self.org_repo.slug_exists(slug):
            raise ResourceConflictError(
                "Slug already exists",
                code="ORGANIZATION_SLUG_ALREADY_EXISTS",
                data={"slug": slug},
            )

        organization = await self.org_repo.create(
            {
                "name": name,
                "slug": slug,
                "logo": logo,
                "metadata_": {
                    "plan_type": self.TEAM_PLAN,
                    "seats": {"limit": 1},
                },
            }
        )
        await self.commit()

        # create owner member
        member = await self.member_repo.create(
            {
                "user_id": current_user.id,
                "organization_id": organization.id,
                "role": OrgRole.OWNER,
            }
        )
        await self.commit()

        # reload member relationships for serialization
        organization = await self.org_repo.get_with_members(organization.id) or organization
        return self._serialize_org(organization, member.role, include_seats=True)

    async def set_active_organization(
        self,
        organization_id: uuid.UUID,
        current_user: User,
    ) -> Dict:
        """Set the active organization (currently only validates membership and returns org info)."""
        organization = await self.org_repo.get_with_members(organization_id)
        if not organization:
            raise NotFoundError(
                "Organization not found",
                code="ORGANIZATION_NOT_FOUND",
                data={"organization_id": str(organization_id)},
            )

        member = await self._ensure_member(organization_id, current_user.id)
        # if persistence is needed, write to user settings/session here
        return self._serialize_org(organization, member.role, include_seats=True)

    async def get_organization(
        self,
        organization_id: uuid.UUID,
        include_seats: bool,
        current_user: User,
    ) -> Dict:
        """Get organization details."""
        organization = await self.org_repo.get_with_members(organization_id)
        if not organization:
            raise NotFoundError(
                "Organization not found",
                code="ORGANIZATION_NOT_FOUND",
                data={"organization_id": str(organization_id)},
            )

        member = await self._ensure_member(organization_id, current_user.id)
        return self._serialize_org(organization, member.role, include_seats)

    async def update_organization(
        self,
        organization_id: uuid.UUID,
        *,
        name: Optional[str],
        slug: Optional[str],
        logo: Optional[str],
        current_user: User,
    ) -> Dict:
        """Update organization basic info."""
        organization = await self.org_repo.get_with_members(organization_id)
        if not organization:
            raise NotFoundError(
                "Organization not found",
                code="ORGANIZATION_NOT_FOUND",
                data={"organization_id": str(organization_id)},
            )

        member = await self._ensure_member(organization_id, current_user.id)
        self._ensure_admin_or_owner(member)

        update_data = {}
        if name is not None:
            update_data["name"] = name
        if logo is not None:
            update_data["logo"] = logo
        if slug is not None:
            if await self.org_repo.slug_exists(slug, exclude_id=organization.id):
                raise ResourceConflictError(
                    "Slug already exists",
                    code="ORGANIZATION_SLUG_ALREADY_EXISTS",
                    data={"slug": slug},
                )
            update_data["slug"] = slug

        if update_data:
            organization = await self.org_repo.update(organization.id, update_data)  # type: ignore
            await self.commit()

        return self._serialize_org(organization, member.role, include_seats=True)

    async def update_seats(
        self,
        organization_id: uuid.UUID,
        *,
        seats: int,
        current_user: User,
    ) -> Dict:
        """Update seats info."""
        organization = await self.org_repo.get_with_members(organization_id)
        if not organization:
            raise NotFoundError(
                "Organization not found",
                code="ORGANIZATION_NOT_FOUND",
                data={"organization_id": str(organization_id)},
            )

        member = await self._ensure_member(organization_id, current_user.id)
        self._ensure_admin_or_owner(member)

        self._validate_plan_for_seats(organization)
        if seats < 1 or seats > 50:
            raise InvalidRequestError(
                "Seats must be between 1 and 50",
                code="ORGANIZATION_SEATS_INVALID",
                data={"seats": seats},
            )

        current_members = await self.member_repo.count_by_org(organization.id)
        if seats < current_members:
            raise InvalidRequestError(
                "Seats cannot be less than current member count",
                code="ORGANIZATION_SEATS_BELOW_MEMBER_COUNT",
                data={"seats": seats, "member_count": current_members},
            )

        metadata = organization.metadata_ or {}
        seats_config = metadata.get("seats", {}) or {}
        seats_config["limit"] = seats
        metadata["seats"] = seats_config
        organization.metadata_ = metadata

        await self.commit()
        return self._build_seats_info(organization, members_count=current_members)

    # --------------------------------------------------------------------- #
    # members
    # --------------------------------------------------------------------- #
    async def list_members(
        self,
        organization_id: uuid.UUID,
        include_usage: bool,
        current_user: User,
    ) -> List[Dict]:
        """Get member list."""
        organization = await self.org_repo.get_with_members(organization_id)
        if not organization:
            raise NotFoundError(
                "Organization not found",
                code="ORGANIZATION_NOT_FOUND",
                data={"organization_id": str(organization_id)},
            )

        await self._ensure_member(organization_id, current_user.id)
        members = await self.member_repo.list_by_org(organization.id)
        return [self._serialize_member(m, include_usage) for m in members]

    async def invite_member(
        self,
        organization_id: uuid.UUID,
        *,
        email: EmailStr,
        role: str,
        current_user: User,
    ) -> Dict:
        """Invite/add a new member."""
        organization = await self.org_repo.get_with_members(organization_id)
        if not organization:
            raise NotFoundError(
                "Organization not found",
                code="ORGANIZATION_NOT_FOUND",
                data={"organization_id": str(organization_id)},
            )

        inviter = await self._ensure_member(organization_id, current_user.id)
        self._ensure_admin_or_owner(inviter)

        normalized_role = role or OrgRole.MEMBER
        if normalized_role not in self.SUPPORTED_ROLES:
            raise InvalidRequestError(
                "Invalid role",
                code="ORGANIZATION_MEMBER_ROLE_INVALID",
                data={"role": normalized_role},
            )
        if normalized_role == OrgRole.OWNER:
            raise InvalidRequestError(
                "Cannot assign owner when inviting",
                code="ORGANIZATION_OWNER_INVITE_FORBIDDEN",
            )

        invitee = await self.user_repo.get_by_email(email)
        if not invitee:
            raise NotFoundError("User not found", code="USER_NOT_FOUND", data={"email": str(email)})

        existing = await self.member_repo.get_by_user_and_org(invitee.id, organization.id)
        if existing:
            raise ResourceConflictError(
                "User is already a member",
                code="ORGANIZATION_MEMBER_ALREADY_EXISTS",
                data={"user_id": str(invitee.id)},
            )

        seat_info = self._build_seats_info(organization)
        if seat_info["available"] <= 0:
            raise InvalidRequestError(
                "No available seats",
                code="ORGANIZATION_SEATS_UNAVAILABLE",
                data=seat_info,
            )

        member = await self.member_repo.create(
            {
                "user_id": invitee.id,
                "organization_id": organization.id,
                "role": normalized_role,
            }
        )
        await self.commit()

        return self._serialize_member(member, include_usage=False)

    async def get_member(
        self,
        organization_id: uuid.UUID,
        member_id: uuid.UUID,
        include_usage: bool,
        current_user: User,
    ) -> Dict:
        """Get member details."""
        organization = await self.org_repo.get_with_members(organization_id)
        if not organization:
            raise NotFoundError(
                "Organization not found",
                code="ORGANIZATION_NOT_FOUND",
                data={"organization_id": str(organization_id)},
            )

        requester = await self._ensure_member(organization_id, current_user.id)
        target = await self.member_repo.get_with_user(member_id)
        if not target or target.organization_id != organization.id:
            raise NotFoundError(
                "Member not found", code="ORGANIZATION_MEMBER_NOT_FOUND", data={"member_id": str(member_id)}
            )

        if requester.user_id != target.user_id and requester.role not in [OrgRole.OWNER, OrgRole.ADMIN]:
            raise AccessDeniedError("Not allowed to view this member", code="ORGANIZATION_MEMBER_VIEW_FORBIDDEN")

        return self._serialize_member(target, include_usage)

    async def update_member_role(
        self,
        organization_id: uuid.UUID,
        member_id: uuid.UUID,
        *,
        role: str,
        current_user: User,
    ) -> Dict:
        """Update member role."""
        organization = await self.org_repo.get_with_members(organization_id)
        if not organization:
            raise NotFoundError(
                "Organization not found",
                code="ORGANIZATION_NOT_FOUND",
                data={"organization_id": str(organization_id)},
            )

        actor = await self._ensure_member(organization_id, current_user.id)
        target = await self.member_repo.get_with_user(member_id)
        if not target or target.organization_id != organization.id:
            raise NotFoundError(
                "Member not found", code="ORGANIZATION_MEMBER_NOT_FOUND", data={"member_id": str(member_id)}
            )

        if role not in self.SUPPORTED_ROLES:
            raise InvalidRequestError(
                "Invalid role",
                code="ORGANIZATION_MEMBER_ROLE_INVALID",
                data={"role": role},
            )
        if role == OrgRole.OWNER:
            raise InvalidRequestError(
                "Owner role cannot be reassigned", code="ORGANIZATION_OWNER_ROLE_REASSIGN_FORBIDDEN"
            )
        if target.role == OrgRole.OWNER:
            raise AccessDeniedError("Cannot modify owner role", code="ORGANIZATION_OWNER_ROLE_MODIFY_FORBIDDEN")

        # access control: only owner can promote to admin; admins can also demote
        if role == OrgRole.ADMIN and actor.role != OrgRole.OWNER:
            raise AccessDeniedError("Only owner can promote to admin", code="ORGANIZATION_ADMIN_PROMOTE_FORBIDDEN")
        if actor.role not in [OrgRole.OWNER, OrgRole.ADMIN]:
            raise AccessDeniedError(
                "Insufficient permission to update roles", code="ORGANIZATION_MEMBER_ROLE_UPDATE_FORBIDDEN"
            )
        if actor.role == OrgRole.ADMIN and target.role in [OrgRole.ADMIN, OrgRole.OWNER]:
            raise AccessDeniedError(
                "Admin cannot change other admins/owner", code="ORGANIZATION_ADMIN_ROLE_TARGET_FORBIDDEN"
            )

        target.role = role
        await self.commit()

        return self._serialize_member(target, include_usage=False)

    async def remove_member(
        self,
        organization_id: uuid.UUID,
        member_id: uuid.UUID,
        current_user: User,
        *,
        should_reduce_seats: bool = False,
    ) -> bool:
        """Remove a member."""
        organization = await self.org_repo.get_with_members(organization_id)
        if not organization:
            raise NotFoundError(
                "Organization not found",
                code="ORGANIZATION_NOT_FOUND",
                data={"organization_id": str(organization_id)},
            )

        actor = await self._ensure_member(organization_id, current_user.id)
        target = await self.member_repo.get_with_user(member_id)
        if not target or target.organization_id != organization.id:
            raise NotFoundError(
                "Member not found", code="ORGANIZATION_MEMBER_NOT_FOUND", data={"member_id": str(member_id)}
            )

        if target.role == OrgRole.OWNER:
            raise AccessDeniedError("Cannot remove organization owner", code="ORGANIZATION_OWNER_REMOVE_FORBIDDEN")
        if actor.role == OrgRole.ADMIN and target.role in [OrgRole.ADMIN, OrgRole.OWNER]:
            raise AccessDeniedError(
                "Admin cannot remove admins or owner", code="ORGANIZATION_ADMIN_REMOVE_TARGET_FORBIDDEN"
            )
        if actor.role not in [OrgRole.OWNER, OrgRole.ADMIN] and actor.user_id != target.user_id:
            raise AccessDeniedError("Not allowed to remove this member", code="ORGANIZATION_MEMBER_REMOVE_FORBIDDEN")

        members_before = await self.member_repo.count_by_org(organization.id)
        await self.member_repo.delete(target.id)
        members_after = max(members_before - 1, 0)

        if should_reduce_seats:
            metadata = organization.metadata_ or {}
            seats_config = metadata.get("seats", {}) or {}
            current_limit = seats_config.get("limit", members_before)
            new_limit = max(members_after, 1)
            seats_config["limit"] = min(current_limit, max(new_limit, members_after))
            metadata["seats"] = seats_config
            organization.metadata_ = metadata

        await self.commit()
        return True

    # --------------------------------------------------------------------- #
    # Helpers
    # --------------------------------------------------------------------- #
    async def _ensure_member(self, organization_id: uuid.UUID, user_id: str | uuid.UUID) -> Member:
        # user_id can be str (from AuthUser.id) or UUID, convert to str for query
        user_id_str = str(user_id)
        member = await self.member_repo.get_by_user_and_org(user_id_str, organization_id)
        if not member:
            raise AccessDeniedError("No access to this organization", code="ORGANIZATION_ACCESS_DENIED")
        return member  # type: ignore

    def _ensure_admin_or_owner(self, member: Member) -> None:
        if member.role not in [OrgRole.OWNER, OrgRole.ADMIN]:
            raise AccessDeniedError(
                "Only owner or admin can perform this action", code="ORGANIZATION_PERMISSION_DENIED"
            )

    def _validate_plan_for_seats(self, organization: Organization) -> None:
        plan = (organization.metadata_ or {}).get("plan_type", self.TEAM_PLAN)
        if plan != self.TEAM_PLAN:
            raise InvalidRequestError(
                "Seat management is available only for team plan",
                code="ORGANIZATION_PLAN_UNSUPPORTED",
                data={"plan": plan},
            )

    def _serialize_org(self, organization: Organization, role: str, include_seats: bool) -> Dict:
        data = {
            "id": str(organization.id),
            "name": organization.name,
            "slug": organization.slug,
            "logo": organization.logo,
            "metadata": organization.metadata_ or {},
            "org_usage_limit": organization.org_usage_limit,
            "storage_used_bytes": organization.storage_used_bytes,
            "role": role,
            "permissions": self._role_permissions(role),
        }
        if include_seats:
            data["seats"] = self._build_seats_info(organization)
        return data

    def _role_permissions(self, role: str) -> Dict[str, bool]:
        return {
            "manage_org": role in [OrgRole.OWNER, OrgRole.ADMIN],
            "manage_members": role in [OrgRole.OWNER, OrgRole.ADMIN],
            "manage_seats": role in [OrgRole.OWNER, OrgRole.ADMIN],
            "view_usage": True,
        }

    def _build_seats_info(self, organization: Organization, members_count: Optional[int] = None) -> Dict:
        members_total = members_count if members_count is not None else len(organization.members or [])
        metadata = organization.metadata_ or {}
        seats_config = metadata.get("seats", {}) or {}
        limit = seats_config.get("limit")
        if limit is None:
            limit = max(members_total, 1)
        available = max(limit - members_total, 0)
        return {
            "plan": metadata.get("plan_type", self.TEAM_PLAN),
            "limit": limit,
            "used": members_total,
            "available": available,
        }

    def _serialize_member(self, member: Member, include_usage: bool) -> Dict:
        user = member.user
        data = {
            "id": str(member.id),
            "role": member.role,
            "user": {
                "id": str(user.id),
                "email": user.email,
                "name": user.name,
                "image": user.image,
                "email_verified": user.email_verified,
                "is_super_user": user.is_super_user,
            },
            "joined_at": member.created_at.isoformat() if member.created_at else None,
        }
        if include_usage:
            data["usage"] = self._build_member_usage(member)
        return data

    def _build_member_usage(self, member: Member) -> Dict:
        # TODO: implement real usage stats per member
        return {
            "messages": None,
            "storage_bytes": None,
            "_note": "Usage stats not yet implemented",
        }
