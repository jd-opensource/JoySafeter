"""工作空间服务"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from app.common.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.common.pagination import PageResult, PaginationParams
from app.models.access_control import PermissionType, WorkspaceInvitation, WorkspaceInvitationStatus
from app.models.auth import AuthUser as User
from app.models.workspace import Workspace, WorkspaceMemberRole, WorkspaceType
from app.repositories.workspace import (
    WorkspaceInvitationRepository,
    WorkspaceMemberRepository,
    WorkspaceRepository,
)
from app.services.email_service import EmailService

from .base import BaseService


class WorkspaceService(BaseService[Workspace]):
    """工作空间业务逻辑"""

    def __init__(self, db):
        super().__init__(db)
        self.workspace_repo = WorkspaceRepository(db)
        self.member_repo = WorkspaceMemberRepository(db)
        self.invitation_repo = WorkspaceInvitationRepository(db)
        self.email_service = EmailService()

    async def _serialize_workspace(self, workspace: Workspace, current_user: User) -> Dict:
        """序列化 workspace，对齐旧项目 camelCase 字段命名"""
        role = await self._get_role(workspace, current_user)
        return {
            "id": str(workspace.id),
            "name": workspace.name,
            "description": workspace.description,
            "ownerId": str(workspace.owner_id),
            "status": workspace.status.value,
            "type": workspace.type.value if hasattr(workspace.type, "value") else workspace.type,
            "settings": workspace.settings or {},
            "allowPersonalApiKeys": workspace.allow_personal_api_keys,
            "createdAt": workspace.created_at,
            "updatedAt": workspace.updated_at,
            "role": role.value if isinstance(role, WorkspaceMemberRole) else role,
        }

    async def _get_role(self, workspace: Workspace, current_user: User) -> WorkspaceMemberRole | str | None:
        if current_user.is_superuser:
            return WorkspaceMemberRole.owner
        if workspace.owner_id == current_user.id:
            return WorkspaceMemberRole.owner
        member = await self.member_repo.get_member(workspace.id, current_user.id)
        return member.role if member else None

    async def _ensure_member(self, workspace_id: uuid.UUID, current_user: User) -> WorkspaceMemberRole:
        workspace = await self.workspace_repo.get(workspace_id)
        if not workspace:
            raise NotFoundException("Workspace not found")
        if current_user.is_superuser or workspace.owner_id == current_user.id:
            return WorkspaceMemberRole.owner
        member = await self.member_repo.get_member(workspace_id, current_user.id)
        if not member:
            raise ForbiddenException("No access to workspace")
        return member.role  # type: ignore

    async def get_user_role(self, workspace_id: uuid.UUID, current_user: User) -> Optional[WorkspaceMemberRole]:
        """
        获取用户在工作空间中的角色（复用 _ensure_member 逻辑，但不抛异常）

        Returns:
            用户角色，如果用户不是成员则返回 None
        """
        try:
            # 复用现有的 _ensure_member 方法，它已经处理了所有情况（超级用户、所有者、普通成员）
            return await self._ensure_member(workspace_id, current_user)
        except (NotFoundException, ForbiddenException):
            # 如果用户不是成员，返回 None 而不是抛异常（因为这是查询方法，不是验证方法）
            return None

    def _ensure_admin_role(self, role: WorkspaceMemberRole):
        if role not in {WorkspaceMemberRole.owner, WorkspaceMemberRole.admin}:
            raise ForbiddenException("Admin permission required")

    async def list_workspaces(self, current_user: User) -> List[Dict]:
        workspaces = await self.workspace_repo.list_for_user(current_user.id)
        return [await self._serialize_workspace(ws, current_user) for ws in workspaces]

    async def ensure_personal_workspace(self, current_user: User) -> Workspace:
        """确保用户有个人空间，如果没有则创建一个"""
        workspaces = await self.workspace_repo.list_for_user(current_user.id)
        personal_workspace = None
        for ws in workspaces:
            if ws.type == WorkspaceType.personal and ws.owner_id == current_user.id:
                personal_workspace = ws
                break

        if not personal_workspace:
            personal_workspace = await self._create_personal_workspace(current_user)
            await self.commit()

        return personal_workspace

    async def _create_personal_workspace(self, current_user: User) -> Workspace:
        """创建个人空间"""
        ws = await self.workspace_repo.create(
            {
                "name": "个人空间",
                "description": "个人空间",
                "owner_id": current_user.id,
                "allow_personal_api_keys": True,
                "type": WorkspaceType.personal,
            }
        )
        await self.member_repo.create(
            {"workspace_id": ws.id, "user_id": current_user.id, "role": WorkspaceMemberRole.owner}
        )
        return ws  # type: ignore

    async def create_workspace(
        self,
        *,
        name: str,
        description: Optional[str],
        current_user: User,
        workspace_type: WorkspaceType = WorkspaceType.team,
    ) -> Dict:
        """创建工作空间（默认创建团队工作空间）"""
        datetime.utcnow()
        workspace = await self.workspace_repo.create(
            {
                "name": name,
                "description": description,
                "owner_id": current_user.id,
                "allow_personal_api_keys": True,
                "type": workspace_type,
            }
        )
        await self.member_repo.create(
            {"workspace_id": workspace.id, "user_id": current_user.id, "role": WorkspaceMemberRole.owner}
        )

        await self.commit()
        return await self._serialize_workspace(workspace, current_user)

    async def get_workspace(self, workspace_id: uuid.UUID, current_user: User) -> Dict:
        workspace = await self.workspace_repo.get(workspace_id)
        if not workspace:
            raise NotFoundException("Workspace not found")
        await self._ensure_member(workspace_id, current_user)
        return await self._serialize_workspace(workspace, current_user)

    async def update_workspace(
        self,
        workspace_id: uuid.UUID,
        *,
        name: Optional[str],
        description: Optional[str],
        allow_personal_api_keys: Optional[bool],
        settings: Optional[dict],
        current_user: User,
    ) -> Dict:
        role = await self._ensure_member(workspace_id, current_user)
        self._ensure_admin_role(role)

        workspace = await self.workspace_repo.get(workspace_id)
        if not workspace:
            raise NotFoundException("Workspace not found")

        update_data: Dict[str, Any] = {}
        if name is not None:
            update_data["name"] = name
        if description is not None:
            update_data["description"] = description
        if allow_personal_api_keys is not None:
            update_data["allow_personal_api_keys"] = allow_personal_api_keys
        if settings is not None:
            merged_settings = workspace.settings or {}
            merged_settings.update(settings)
            update_data["settings"] = merged_settings

        if update_data:
            updated_workspace = await self.workspace_repo.update(workspace_id, update_data)  # type: ignore
            await self.commit()
            # 提交后重新刷新以确保获取数据库中的最新数据
            await self.db.refresh(updated_workspace)
            workspace = updated_workspace
        else:
            # 如果没有更新数据，重新获取以确保数据最新
            workspace = await self.workspace_repo.get(workspace_id)

        # 确保返回最新的序列化数据
        return await self._serialize_workspace(workspace, current_user)

    async def delete_workspace(
        self,
        workspace_id: uuid.UUID,
        *,
        delete_templates: bool,
        current_user: User,
    ) -> bool:
        role = await self._ensure_member(workspace_id, current_user)
        self._ensure_admin_role(role)

        # 检查是否为个人空间，个人空间不允许删除
        workspace = await self.workspace_repo.get(workspace_id)
        if not workspace:
            raise NotFoundException("Workspace not found")

        if workspace.type == WorkspaceType.personal:
            raise BadRequestException("个人空间不允许删除")

        deleted = await self.workspace_repo.delete(workspace_id)
        await self.commit()
        # 模板删除逻辑预留，当前模型中未挂载模板实体
        return bool(deleted) if deleted is not None else False

    async def duplicate_workspace(
        self,
        workspace_id: uuid.UUID,
        *,
        name: Optional[str],
        current_user: User,
    ) -> Dict:
        """复制工作空间"""
        # 获取源工作空间
        source_workspace = await self.workspace_repo.get(workspace_id)
        if not source_workspace:
            raise NotFoundException("Workspace not found")

        # 确保用户有权限访问源工作空间
        await self._ensure_member(workspace_id, current_user)

        # 检查是否为个人空间，个人空间不允许复制
        if source_workspace.type == WorkspaceType.personal:
            raise BadRequestException("个人空间不允许复制")

        # 生成新名称
        new_name = name or f"{source_workspace.name} (Copy)"

        # 创建新工作空间
        new_workspace = await self.workspace_repo.create(
            {
                "name": new_name,
                "description": source_workspace.description,
                "owner_id": current_user.id,
                "allow_personal_api_keys": source_workspace.allow_personal_api_keys,
                "type": WorkspaceType.team,  # 复制的都是团队空间
                "settings": source_workspace.settings.copy() if source_workspace.settings else None,
            }
        )

        # 将当前用户添加为新工作空间的拥有者
        await self.member_repo.create(
            {"workspace_id": new_workspace.id, "user_id": current_user.id, "role": WorkspaceMemberRole.owner}
        )

        await self.commit()
        return await self._serialize_workspace(new_workspace, current_user)

    # ------------------------------------------------------------------ #
    # 邀请
    # ------------------------------------------------------------------ #
    async def create_invitation(
        self,
        *,
        workspace_id: uuid.UUID,
        email: str,
        role: str,
        permission: PermissionType,
        current_user: User,
    ) -> Dict:
        member_role = await self._ensure_member(workspace_id, current_user)
        self._ensure_admin_role(member_role)

        if role not in WorkspaceMemberRole._value2member_map_:
            raise BadRequestException("Invalid role")

        from app.repositories.auth_user import AuthUserRepository

        user_repo = AuthUserRepository(self.db)
        invitee = await user_repo.get_by_email(email.lower())

        if invitee:
            existing_member = await self.member_repo.get_member(workspace_id, invitee.id)
            if existing_member:
                raise BadRequestException(
                    f"User with email {email} is already a member of this workspace. 该用户已经是工作空间成员"
                )

        token = uuid.uuid4().hex
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)

        invitation = await self.invitation_repo.create(
            {
                "workspace_id": workspace_id,
                "email": email,
                "inviter_id": current_user.id,
                "role": role,
                "status": WorkspaceInvitationStatus.pending,
                "token": token,
                "permissions": permission,
                "expires_at": expires_at,
            }
        )
        await self.commit()

        # 获取工作空间名称用于通知
        workspace = await self.workspace_repo.get(workspace_id)
        workspace_name = workspace.name if workspace else "Unknown"

        # 可选：发送邮件通知（忽略失败但记录日志）
        # 现在主要依赖登录后的系统通知，邮件作为可选的通知方式
        invite_link = f"{self.email_service.frontend_url}/workspace/invitations/accept?token={token}"
        subject = "工作空间邀请"
        html = f"""
        <p>您被邀请加入工作空间。</p>
        <p>请登录系统查看邀请通知并接受邀请。</p>
        <p>或点击链接直接接受：<a href="{invite_link}">{invite_link}</a></p>
        """
        try:
            await self.email_service.send_email(email, subject, html)
        except Exception:
            # 不阻断流程，邮件发送失败不影响邀请创建
            pass

        invitation_data = {
            "id": str(invitation.id),
            "workspaceId": str(invitation.workspace_id),
            "workspaceName": workspace_name,
            "email": invitation.email,
            "role": invitation.role,
            "status": invitation.status.value,
            "token": invitation.token,
            "inviterName": current_user.name,
            "inviterEmail": current_user.email,
            "expiresAt": invitation.expires_at.isoformat() if invitation.expires_at else None,
            "createdAt": invitation.created_at.isoformat() if invitation.created_at else None,
            "updatedAt": invitation.updated_at.isoformat() if invitation.updated_at else None,
        }

        # 推送 WebSocket 通知给被邀请人（如果已注册）
        if invitee:
            try:
                from app.websocket.notification_manager import NotificationType, notification_manager

                await notification_manager.send_to_user(
                    invitee.id,
                    {
                        "type": NotificationType.INVITATION_RECEIVED.value,
                        "data": invitation_data,
                    },
                )
            except Exception as e:
                # 不阻断流程，通知失败不影响邀请创建
                from loguru import logger

                logger.warning(f"Failed to send WebSocket notification: {e}")

        return invitation_data

    async def list_invitations(self, current_user: User) -> List[Dict]:
        """
        获取当前用户所有 workspace 的邀请列表。
        对齐旧项目：返回用户有权限访问的 workspace 下的所有邀请。
        """
        workspaces = await self.workspace_repo.list_for_user(current_user.id)
        if not workspaces:
            return []

        workspace_ids = [ws.id for ws in workspaces]
        invitations = await self.invitation_repo.list_by_workspaces(workspace_ids)

        return [
            {
                "id": str(inv.id),
                "workspaceId": str(inv.workspace_id),
                "email": inv.email,
                "inviterId": str(inv.inviter_id),
                "role": inv.role,
                "status": inv.status.value if hasattr(inv.status, "value") else inv.status,
                "permissions": inv.permissions.value if hasattr(inv.permissions, "value") else inv.permissions,
                "token": inv.token,
                "expiresAt": inv.expires_at,
                "createdAt": inv.created_at,
                "updatedAt": inv.updated_at,
            }
            for inv in invitations
        ]

    async def list_pending_invitations_for_user(self, current_user: User) -> List[Dict]:
        """获取当前用户待处理的工作空间邀请

        优化：使用 selectinload 一次性加载关联数据，避免 N+1 查询问题
        """
        from sqlalchemy.orm import selectinload

        # 使用 eager loading 一次性加载 workspace 和 inviter 关联
        query = (
            select(WorkspaceInvitation)
            .options(
                selectinload(WorkspaceInvitation.workspace),
                selectinload(WorkspaceInvitation.inviter),
            )
            .where(
                WorkspaceInvitation.email == current_user.email.lower(),
                WorkspaceInvitation.status == WorkspaceInvitationStatus.pending,
                WorkspaceInvitation.expires_at > datetime.now(timezone.utc),
            )
            .order_by(WorkspaceInvitation.created_at.desc())
        )
        result = await self.db.execute(query)
        invitations = result.scalars().all()

        return [
            {
                "id": str(inv.id),
                "workspaceId": str(inv.workspace_id),
                "workspaceName": inv.workspace.name if inv.workspace else None,
                "email": inv.email,
                "inviterId": str(inv.inviter_id),
                "inviterName": inv.inviter.name if inv.inviter else None,
                "inviterEmail": inv.inviter.email if inv.inviter else None,
                "role": inv.role,
                "status": inv.status.value,
                "permissions": inv.permissions.value if hasattr(inv.permissions, "value") else inv.permissions,
                "expiresAt": inv.expires_at.isoformat() if inv.expires_at else None,
                "createdAt": inv.created_at.isoformat() if inv.created_at else None,
            }
            for inv in invitations
            if inv.workspace  # 过滤掉已删除的工作空间
        ]

    async def list_all_invitations_for_user(self, current_user: User) -> List[Dict]:
        """获取当前用户所有的工作空间邀请（包括已处理的）- 已废弃，使用分页版本

        优化：使用 selectinload 一次性加载关联数据，避免 N+1 查询问题
        """
        from sqlalchemy.orm import selectinload

        # 使用 eager loading 一次性加载关联数据
        query = (
            select(WorkspaceInvitation)
            .options(
                selectinload(WorkspaceInvitation.workspace),
                selectinload(WorkspaceInvitation.inviter),
            )
            .where(WorkspaceInvitation.email == current_user.email.lower())
            .order_by(WorkspaceInvitation.created_at.desc())
        )
        result = await self.db.execute(query)
        invitations = result.scalars().all()

        now = datetime.now(timezone.utc)
        return [
            {
                "id": str(inv.id),
                "workspaceId": str(inv.workspace_id),
                "workspaceName": inv.workspace.name if inv.workspace else None,
                "email": inv.email,
                "inviterId": str(inv.inviter_id),
                "inviterName": inv.inviter.name if inv.inviter else None,
                "inviterEmail": inv.inviter.email if inv.inviter else None,
                "role": inv.role,
                "status": inv.status.value,
                "permissions": inv.permissions.value if hasattr(inv.permissions, "value") else inv.permissions,
                "expiresAt": inv.expires_at.isoformat() if inv.expires_at else None,
                "createdAt": inv.created_at.isoformat() if inv.created_at else None,
                "isExpired": inv.expires_at < now if inv.expires_at else False,
            }
            for inv in invitations
            if inv.workspace  # 过滤掉已删除的工作空间
        ]

    async def list_all_invitations_for_user_paginated(
        self, current_user: User, pagination: PaginationParams, status: Optional[str] = None
    ) -> PageResult:
        """获取当前用户所有的工作空间邀请（支持分页和状态筛选）

        优化：使用 selectinload 一次性加载关联数据，避免 N+1 查询问题
        """
        from sqlalchemy import and_, or_
        from sqlalchemy.orm import selectinload

        from app.common.pagination import PageResult, Paginator

        # 构建基础查询，使用 eager loading
        query = (
            select(WorkspaceInvitation)
            .options(
                selectinload(WorkspaceInvitation.workspace),
                selectinload(WorkspaceInvitation.inviter),
            )
            .where(WorkspaceInvitation.email == current_user.email.lower())
        )

        # 状态筛选
        now = datetime.now(timezone.utc)
        if status == "pending":
            # 待处理：状态为pending且未过期（expires_at为None或未过期）
            query = query.where(WorkspaceInvitation.status == WorkspaceInvitationStatus.pending).where(
                or_(WorkspaceInvitation.expires_at.is_(None), WorkspaceInvitation.expires_at > now)
            )
        elif status == "processed":
            # 已处理：状态不是pending或已过期
            query = query.where(
                or_(
                    WorkspaceInvitation.status != WorkspaceInvitationStatus.pending,
                    and_(WorkspaceInvitation.expires_at.isnot(None), WorkspaceInvitation.expires_at <= now),
                )
            )
        elif status:
            # 特定状态筛选（accepted, rejected等）
            try:
                status_enum = WorkspaceInvitationStatus(status)
                query = query.where(WorkspaceInvitation.status == status_enum)
            except ValueError:
                # 无效的状态值，忽略筛选
                pass

        # 排序
        query = query.order_by(WorkspaceInvitation.created_at.desc())

        # 使用分页器
        paginator = Paginator(self.db)
        page_result = await paginator.paginate(query, pagination)

        # 转换结果（关联数据已通过 eager loading 加载，无需额外查询）
        result_list = [
            {
                "id": str(inv.id),
                "workspaceId": str(inv.workspace_id),
                "workspaceName": inv.workspace.name if inv.workspace else None,
                "email": inv.email,
                "inviterId": str(inv.inviter_id),
                "inviterName": inv.inviter.name if inv.inviter else None,
                "inviterEmail": inv.inviter.email if inv.inviter else None,
                "role": inv.role,
                "status": inv.status.value,
                "permissions": inv.permissions.value if hasattr(inv.permissions, "value") else inv.permissions,
                "expiresAt": inv.expires_at.isoformat() if inv.expires_at else None,
                "createdAt": inv.created_at.isoformat() if inv.created_at else None,
                "isExpired": inv.expires_at < now if inv.expires_at else False,
            }
            for inv in page_result.items
            if inv.workspace  # 过滤掉已删除的工作空间
        ]

        return PageResult(
            items=result_list,
            total=page_result.total,
            page=page_result.page,
            page_size=page_result.page_size,
            pages=page_result.pages,
        )

    async def get_invitation_by_token(self, token: str) -> Dict:
        """根据 token 获取邀请信息"""
        invitation = await self.invitation_repo.get_by_token(token)
        if not invitation:
            raise NotFoundException("Invitation not found")

        # 检查是否过期
        if invitation.expires_at < datetime.now(timezone.utc):
            raise BadRequestException("Invitation has expired")

        # 检查状态
        if invitation.status != WorkspaceInvitationStatus.pending:
            raise BadRequestException(f"Invitation has been {invitation.status.value}")

        # 获取工作空间信息
        workspace = await self.workspace_repo.get(invitation.workspace_id)
        if not workspace:
            raise NotFoundException("Workspace not found")

        # 获取邀请人信息
        from app.repositories.auth_user import AuthUserRepository

        user_repo = AuthUserRepository(self.db)
        inviter = await user_repo.get_by(id=invitation.inviter_id)

        return {
            "id": str(invitation.id),
            "workspaceId": str(invitation.workspace_id),
            "workspaceName": workspace.name,
            "email": invitation.email,
            "inviterId": str(invitation.inviter_id),
            "inviterName": inviter.name if inviter else None,
            "inviterEmail": inviter.email if inviter else None,
            "role": invitation.role,
            "status": invitation.status.value,
            "permissions": invitation.permissions.value,
            "expiresAt": invitation.expires_at.isoformat() if invitation.expires_at else None,
            "createdAt": invitation.created_at.isoformat() if invitation.created_at else None,
        }

    async def accept_invitation(self, invitation_id: uuid.UUID, current_user: User) -> Dict:
        """接受工作空间邀请（通过邀请ID）"""
        invitation = await self.invitation_repo.get(invitation_id)
        if not invitation:
            raise NotFoundException("Invitation not found")

        # 检查是否过期
        if invitation.expires_at < datetime.now(timezone.utc):
            raise BadRequestException("Invitation has expired")

        # 检查状态
        if invitation.status != WorkspaceInvitationStatus.pending:
            raise BadRequestException(f"Invitation has been {invitation.status.value}")

        # 检查邮箱是否匹配
        if invitation.email.lower() != current_user.email.lower():
            raise ForbiddenException("This invitation is not for your email address")

        # 检查用户是否已经是成员
        existing_member = await self.member_repo.get_member(invitation.workspace_id, current_user.id)
        if existing_member:
            # 如果已经是成员，只更新邀请状态
            await self.invitation_repo.update_status(invitation.id, WorkspaceInvitationStatus.accepted)
            await self.commit()
            raise BadRequestException("You are already a member of this workspace")

        # 创建成员记录
        role = WorkspaceMemberRole(invitation.role)
        await self.member_repo.create(
            {
                "workspace_id": invitation.workspace_id,
                "user_id": current_user.id,
                "role": role,
            }
        )

        # 更新邀请状态
        await self.invitation_repo.update_status(invitation.id, WorkspaceInvitationStatus.accepted)
        await self.commit()

        # 获取工作空间信息
        workspace = await self.workspace_repo.get(invitation.workspace_id)

        # 推送 WebSocket 通知给邀请人
        try:
            from app.websocket.notification_manager import NotificationType, notification_manager

            await notification_manager.send_to_user(
                str(invitation.inviter_id),
                {
                    "type": NotificationType.INVITATION_ACCEPTED.value,
                    "data": {
                        "invitationId": str(invitation.id),
                        "workspaceId": str(invitation.workspace_id),
                        "workspaceName": workspace.name if workspace else None,
                        "acceptedByName": current_user.name,
                        "acceptedByEmail": current_user.email,
                    },
                },
            )
        except Exception as e:
            from loguru import logger

            logger.warning(f"Failed to send WebSocket notification: {e}")

        return {
            "success": True,
            "workspace": await self._serialize_workspace(workspace, current_user),
            "message": "Invitation accepted successfully",
        }

    async def accept_invitation_by_token(self, token: str, current_user: User) -> Dict:
        """接受工作空间邀请（通过token，用于邮件链接）"""
        invitation = await self.invitation_repo.get_by_token(token)
        if not invitation:
            raise NotFoundException("Invitation not found")
        return await self.accept_invitation(invitation.id, current_user)

    async def reject_invitation(self, invitation_id: uuid.UUID, current_user: User) -> Dict:
        """拒绝工作空间邀请"""
        invitation = await self.invitation_repo.get(invitation_id)
        if not invitation:
            raise NotFoundException("Invitation not found")

        # 检查邮箱是否匹配
        if invitation.email.lower() != current_user.email.lower():
            raise ForbiddenException("This invitation is not for your email address")

        # 检查状态
        if invitation.status != WorkspaceInvitationStatus.pending:
            raise BadRequestException(f"Invitation has been {invitation.status.value}")

        # 获取工作空间信息（用于通知）
        workspace = await self.workspace_repo.get(invitation.workspace_id)

        # 更新邀请状态
        await self.invitation_repo.update_status(invitation.id, WorkspaceInvitationStatus.rejected)
        await self.commit()

        # 推送 WebSocket 通知给邀请人
        try:
            from app.websocket.notification_manager import NotificationType, notification_manager

            await notification_manager.send_to_user(
                str(invitation.inviter_id),
                {
                    "type": NotificationType.INVITATION_REJECTED.value,
                    "data": {
                        "invitationId": str(invitation.id),
                        "workspaceId": str(invitation.workspace_id),
                        "workspaceName": workspace.name if workspace else None,
                        "rejectedByEmail": current_user.email,
                    },
                },
            )
        except Exception as e:
            from loguru import logger

            logger.warning(f"Failed to send WebSocket notification: {e}")

        return {
            "success": True,
            "message": "Invitation rejected successfully",
        }

    # ------------------------------------------------------------------ #
    # 成员管理
    # ------------------------------------------------------------------ #
    async def list_members(
        self,
        workspace_id: uuid.UUID,
        current_user: User,
    ) -> List[Dict]:
        """获取工作空间成员列表"""
        workspace = await self.workspace_repo.get(workspace_id)
        if not workspace:
            raise NotFoundException("Workspace not found")

        # 确保用户有权限访问
        await self._ensure_member(workspace_id, current_user)

        # 获取所有成员（包含拥有者）
        members = await self.member_repo.list_by_workspace(workspace_id)

        # 添加拥有者到成员列表（如果拥有者不在成员表中）
        owner_in_members = any(m.user_id == workspace.owner_id for m in members)
        if not owner_in_members:
            from app.repositories.auth_user import AuthUserRepository

            user_repo = AuthUserRepository(self.db)
            owner = await user_repo.get_by(id=workspace.owner_id)
            if owner:
                # 创建虚拟成员对象用于序列化
                class OwnerMember:
                    def __init__(self):
                        self.user_id = owner.id
                        self.role = WorkspaceMemberRole.owner
                        self.user = owner
                        self.created_at = workspace.created_at
                        self.updated_at = workspace.updated_at

                owner_member = OwnerMember()
                members.insert(0, owner_member)

        # 序列化成员
        result = []
        for member in members:
            user = member.user if hasattr(member, "user") and member.user else None
            if not user:
                # 如果成员没有用户信息，跳过
                continue

            result.append(
                {
                    "id": str(member.user_id),
                    "userId": str(member.user_id),
                    "workspaceId": str(workspace_id),
                    "email": user.email,
                    "name": user.name,
                    "role": member.role.value if hasattr(member.role, "value") else member.role,
                    "isOwner": workspace.owner_id == member.user_id,
                    "createdAt": member.created_at if hasattr(member, "created_at") else None,
                    "updatedAt": member.updated_at if hasattr(member, "updated_at") else None,
                }
            )

        return result

    async def list_members_paginated(
        self,
        workspace_id: uuid.UUID,
        current_user: User,
        pagination: PaginationParams,
    ) -> PageResult:
        """获取工作空间成员列表（分页）"""
        from app.common.pagination import PageResult

        workspace = await self.workspace_repo.get(workspace_id)
        if not workspace:
            raise NotFoundException("Workspace not found")

        await self._ensure_member(workspace_id, current_user)

        members = await self.member_repo.list_by_workspace(workspace_id)

        owner_in_members = any(m.user_id == workspace.owner_id for m in members)
        if not owner_in_members:
            from app.repositories.auth_user import AuthUserRepository

            user_repo = AuthUserRepository(self.db)
            owner = await user_repo.get_by(id=workspace.owner_id)
            if owner:

                class OwnerMember:
                    def __init__(self):
                        self.user_id = owner.id
                        self.role = WorkspaceMemberRole.owner
                        self.user = owner
                        self.created_at = workspace.created_at
                        self.updated_at = workspace.updated_at

                owner_member = OwnerMember()
                members.insert(0, owner_member)

        result = []
        for member in members:
            user = member.user if hasattr(member, "user") and member.user else None
            if not user:
                continue

            result.append(
                {
                    "id": str(member.user_id),
                    "userId": str(member.user_id),
                    "workspaceId": str(workspace_id),
                    "email": user.email,
                    "name": user.name,
                    "role": member.role.value if hasattr(member.role, "value") else member.role,
                    "isOwner": workspace.owner_id == member.user_id,
                    "createdAt": member.created_at.isoformat()
                    if hasattr(member, "created_at") and member.created_at
                    else None,
                    "updatedAt": member.updated_at.isoformat()
                    if hasattr(member, "updated_at") and member.updated_at
                    else None,
                }
            )

        total = len(result)
        pages = (total + pagination.page_size - 1) // pagination.page_size if pagination.page_size > 0 else 0
        start = pagination.offset
        end = start + pagination.page_size
        paginated_items = result[start:end]

        return PageResult(
            items=paginated_items,
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
            pages=pages,
        )

    async def update_member_role(
        self,
        workspace_id: uuid.UUID,
        target_user_id: str,
        new_role: WorkspaceMemberRole,
        current_user: User,
    ) -> Dict:
        """更新成员角色"""
        workspace = await self.workspace_repo.get(workspace_id)
        if not workspace:
            raise NotFoundException("Workspace not found")

        # 确保当前用户是 admin
        current_role = await self._ensure_member(workspace_id, current_user)
        self._ensure_admin_role(current_role)

        # 获取目标成员
        target_member = await self.member_repo.get_member(workspace_id, target_user_id)
        if not target_member:
            raise NotFoundException("User not found in workspace")

        # 不能修改拥有者的角色
        if workspace.owner_id == target_user_id:
            raise BadRequestException("Cannot change owner role")

        # 如果修改的是 admin，检查是否是最后一个 admin
        if target_member.role in {WorkspaceMemberRole.owner, WorkspaceMemberRole.admin}:
            admin_count = await self.member_repo.count_admins(workspace_id)
            if admin_count <= 1 and new_role not in {WorkspaceMemberRole.owner, WorkspaceMemberRole.admin}:
                raise BadRequestException("Cannot remove the last admin from a workspace")

        # 更新角色
        updated_member = await self.member_repo.update_member_role(workspace_id, target_user_id, new_role)
        await self.commit()

        # 返回更新后的成员信息
        from app.repositories.auth_user import AuthUserRepository

        user_repo = AuthUserRepository(self.db)
        user = await user_repo.get_by(id=target_user_id)

        return {
            "id": str(target_user_id),
            "userId": str(target_user_id),
            "workspaceId": str(workspace_id),
            "email": user.email if user else "",
            "name": user.name if user else "",
            "role": new_role.value if hasattr(new_role, "value") else new_role,
            "isOwner": False,
            "createdAt": updated_member.created_at.isoformat()
            if updated_member and hasattr(updated_member, "created_at") and updated_member.created_at
            else None,
            "updatedAt": updated_member.updated_at.isoformat()
            if updated_member and hasattr(updated_member, "updated_at") and updated_member.updated_at
            else None,
        }

    async def remove_member(
        self,
        *,
        workspace_id: uuid.UUID,
        target_user_id: uuid.UUID,
        current_user: User,
    ) -> bool:
        """
        移除 workspace 成员。
        对齐旧项目逻辑：
        - admin 可以移除任何成员（除了自己是最后一个 admin）
        - 普通成员只能移除自己
        """
        workspace = await self.workspace_repo.get(workspace_id)
        if not workspace:
            raise NotFoundException("Workspace not found")

        # 获取目标用户的成员记录
        target_member = await self.member_repo.get_member(workspace_id, str(target_user_id))
        if not target_member:
            raise NotFoundException("User not found in workspace")

        # 获取当前用户的角色
        current_role = await self._get_role(workspace, current_user)
        is_admin = current_role in {WorkspaceMemberRole.owner, WorkspaceMemberRole.admin}
        is_self = str(target_user_id) == current_user.id

        if not is_admin and not is_self:
            raise ForbiddenException("Insufficient permissions")

        # 如果移除自己且是 admin，检查是否是最后一个 admin
        if is_self and target_member.role in {WorkspaceMemberRole.owner, WorkspaceMemberRole.admin}:
            admin_count = await self.member_repo.count_admins(workspace_id)
            if admin_count <= 1:
                raise BadRequestException("Cannot remove the last admin from a workspace")

        # 执行删除
        await self.member_repo.delete_member(workspace_id, str(target_user_id))
        await self.commit()
        return True
