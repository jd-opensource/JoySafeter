"""
组织与成员服务
"""

import uuid
from typing import Dict, List, Optional

from pydantic import EmailStr

from app.common.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.models.auth import AuthUser as User
from app.models.organization import Member, Organization
from app.repositories.organization import MemberRepository, OrganizationRepository
from app.repositories.user import UserRepository

from .base import BaseService


class OrganizationService(BaseService[Organization]):
    """组织及成员相关业务"""

    ROLE_OWNER = "owner"
    ROLE_ADMIN = "admin"
    ROLE_MEMBER = "member"
    TEAM_PLAN = "team"
    SUPPORTED_ROLES = {ROLE_OWNER, ROLE_ADMIN, ROLE_MEMBER}

    def __init__(self, db):
        super().__init__(db)
        self.org_repo = OrganizationRepository(db)
        self.member_repo = MemberRepository(db)
        self.user_repo = UserRepository(db)

    # --------------------------------------------------------------------- #
    # 组织
    # --------------------------------------------------------------------- #
    async def create_organization(
        self,
        *,
        name: str,
        slug: str,
        logo: Optional[str],
        current_user: User,
    ) -> Dict:
        """创建组织并将当前用户设为 owner"""
        if await self.org_repo.slug_exists(slug):
            raise ConflictException("Slug already exists")

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

        # 创建 owner 成员
        member = await self.member_repo.create(
            {
                "user_id": current_user.id,
                "organization_id": organization.id,
                "role": self.ROLE_OWNER,
            }
        )
        await self.commit()

        # 重新加载成员关系便于序列化
        organization = await self.org_repo.get_with_members(organization.id) or organization
        return self._serialize_org(organization, member.role, include_seats=True)

    async def set_active_organization(
        self,
        organization_id: uuid.UUID,
        current_user: User,
    ) -> Dict:
        """设置当前活跃组织（目前仅校验成员身份并返回组织信息）"""
        organization = await self.org_repo.get_with_members(organization_id)
        if not organization:
            raise NotFoundException("Organization not found")

        member = await self._ensure_member(organization_id, current_user.id)
        # 如果有持久化需求，可在此处写入用户设置/会话
        return self._serialize_org(organization, member.role, include_seats=True)

    async def get_organization(
        self,
        organization_id: uuid.UUID,
        include_seats: bool,
        current_user: User,
    ) -> Dict:
        """获取组织详情"""
        organization = await self.org_repo.get_with_members(organization_id)
        if not organization:
            raise NotFoundException("Organization not found")

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
        """更新组织基础信息"""
        organization = await self.org_repo.get_with_members(organization_id)
        if not organization:
            raise NotFoundException("Organization not found")

        member = await self._ensure_member(organization_id, current_user.id)
        self._ensure_admin_or_owner(member)

        update_data = {}
        if name is not None:
            update_data["name"] = name
        if logo is not None:
            update_data["logo"] = logo
        if slug is not None:
            if await self.org_repo.slug_exists(slug, exclude_id=organization.id):
                raise ConflictException("Slug already exists")
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
        """更新 seats 信息"""
        organization = await self.org_repo.get_with_members(organization_id)
        if not organization:
            raise NotFoundException("Organization not found")

        member = await self._ensure_member(organization_id, current_user.id)
        self._ensure_admin_or_owner(member)

        self._validate_plan_for_seats(organization)
        if seats < 1 or seats > 50:
            raise BadRequestException("Seats must be between 1 and 50")

        current_members = await self.member_repo.count_by_org(organization.id)
        if seats < current_members:
            raise BadRequestException("Seats cannot be less than current member count")

        metadata = organization.metadata_ or {}
        seats_config = metadata.get("seats", {}) or {}
        seats_config["limit"] = seats
        metadata["seats"] = seats_config
        organization.metadata_ = metadata

        await self.commit()
        return self._build_seats_info(organization, members_count=current_members)

    # --------------------------------------------------------------------- #
    # 成员
    # --------------------------------------------------------------------- #
    async def list_members(
        self,
        organization_id: uuid.UUID,
        include_usage: bool,
        current_user: User,
    ) -> List[Dict]:
        """获取成员列表"""
        organization = await self.org_repo.get_with_members(organization_id)
        if not organization:
            raise NotFoundException("Organization not found")

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
        """邀请/添加新成员"""
        organization = await self.org_repo.get_with_members(organization_id)
        if not organization:
            raise NotFoundException("Organization not found")

        inviter = await self._ensure_member(organization_id, current_user.id)
        self._ensure_admin_or_owner(inviter)

        normalized_role = role or self.ROLE_MEMBER
        if normalized_role not in self.SUPPORTED_ROLES:
            raise BadRequestException("Invalid role")
        if normalized_role == self.ROLE_OWNER:
            raise BadRequestException("Cannot assign owner when inviting")

        invitee = await self.user_repo.get_by_email(email)
        if not invitee:
            raise NotFoundException("User not found")

        existing = await self.member_repo.get_by_user_and_org(invitee.id, organization.id)
        if existing:
            raise ConflictException("User is already a member")

        seat_info = self._build_seats_info(organization)
        if seat_info["available"] <= 0:
            raise BadRequestException("No available seats")

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
        """获取成员详情"""
        organization = await self.org_repo.get_with_members(organization_id)
        if not organization:
            raise NotFoundException("Organization not found")

        requester = await self._ensure_member(organization_id, current_user.id)
        target = await self.member_repo.get_with_user(member_id)
        if not target or target.organization_id != organization.id:
            raise NotFoundException("Member not found")

        if requester.user_id != target.user_id and requester.role not in [self.ROLE_OWNER, self.ROLE_ADMIN]:
            raise ForbiddenException("Not allowed to view this member")

        return self._serialize_member(target, include_usage)

    async def update_member_role(
        self,
        organization_id: uuid.UUID,
        member_id: uuid.UUID,
        *,
        role: str,
        current_user: User,
    ) -> Dict:
        """更新成员角色"""
        organization = await self.org_repo.get_with_members(organization_id)
        if not organization:
            raise NotFoundException("Organization not found")

        actor = await self._ensure_member(organization_id, current_user.id)
        target = await self.member_repo.get_with_user(member_id)
        if not target or target.organization_id != organization.id:
            raise NotFoundException("Member not found")

        if role not in self.SUPPORTED_ROLES:
            raise BadRequestException("Invalid role")
        if role == self.ROLE_OWNER:
            raise BadRequestException("Owner role cannot be reassigned")
        if target.role == self.ROLE_OWNER:
            raise ForbiddenException("Cannot modify owner role")

        # 权限控制：只有 owner 可以提升为 admin，其余变更 admin 也可以降级
        if role == self.ROLE_ADMIN and actor.role != self.ROLE_OWNER:
            raise ForbiddenException("Only owner can promote to admin")
        if actor.role not in [self.ROLE_OWNER, self.ROLE_ADMIN]:
            raise ForbiddenException("Insufficient permission to update roles")
        if actor.role == self.ROLE_ADMIN and target.role in [self.ROLE_ADMIN, self.ROLE_OWNER]:
            raise ForbiddenException("Admin cannot change other admins/owner")

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
        """移除成员"""
        organization = await self.org_repo.get_with_members(organization_id)
        if not organization:
            raise NotFoundException("Organization not found")

        actor = await self._ensure_member(organization_id, current_user.id)
        target = await self.member_repo.get_with_user(member_id)
        if not target or target.organization_id != organization.id:
            raise NotFoundException("Member not found")

        if target.role == self.ROLE_OWNER:
            raise ForbiddenException("Cannot remove organization owner")
        if actor.role == self.ROLE_ADMIN and target.role in [self.ROLE_ADMIN, self.ROLE_OWNER]:
            raise ForbiddenException("Admin cannot remove admins or owner")
        if actor.role not in [self.ROLE_OWNER, self.ROLE_ADMIN] and actor.user_id != target.user_id:
            raise ForbiddenException("Not allowed to remove this member")

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
            raise ForbiddenException("No access to this organization")
        return member  # type: ignore

    def _ensure_admin_or_owner(self, member: Member) -> None:
        if member.role not in [self.ROLE_OWNER, self.ROLE_ADMIN]:
            raise ForbiddenException("Only owner or admin can perform this action")

    def _validate_plan_for_seats(self, organization: Organization) -> None:
        plan = (organization.metadata_ or {}).get("plan_type", self.TEAM_PLAN)
        if plan != self.TEAM_PLAN:
            raise BadRequestException("Seat management is available only for team plan")

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
            "manage_org": role in [self.ROLE_OWNER, self.ROLE_ADMIN],
            "manage_members": role in [self.ROLE_OWNER, self.ROLE_ADMIN],
            "manage_seats": role in [self.ROLE_OWNER, self.ROLE_ADMIN],
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
        # TODO: 根据实际业务补充使用量统计
        return {
            "messages": 0,
            "storage_bytes": 0,
        }
