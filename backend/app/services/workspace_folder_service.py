"""
文件夹业务逻辑
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy import select

from app.common.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.models.auth import AuthUser as User
from app.models.workspace import WorkspaceFolder, WorkspaceMemberRole
from app.repositories.workspace import WorkspaceMemberRepository, WorkspaceRepository
from app.repositories.workspace_folder import WorkflowFolderRepository

from .base import BaseService

# 文件夹最大深度限制：只能有两层（根目录深度为0，第一层深度为1）
MAX_FOLDER_DEPTH = 1


class FolderService(BaseService[WorkspaceFolder]):
    """文件夹服务"""

    def __init__(self, db):
        super().__init__(db)
        self.folder_repo = WorkflowFolderRepository(db)
        self.workspace_repo = WorkspaceRepository(db)
        self.member_repo = WorkspaceMemberRepository(db)

    # ------------------------------------------------------------------ #
    # 权限校验
    # ------------------------------------------------------------------ #
    async def _get_member_role(self, workspace_id: uuid.UUID, current_user: User) -> Optional[str]:
        workspace = await self.workspace_repo.get(workspace_id)
        if not workspace:
            raise NotFoundException("Workspace not found")
        if current_user.is_superuser or workspace.owner_id == current_user.id:
            return WorkspaceMemberRole.owner
        member = await self.member_repo.get_member(workspace_id, current_user.id)
        return member.role if member else None

    async def _ensure_permission(
        self,
        workspace_id: uuid.UUID,
        current_user: User,
        required: str,
    ) -> str:
        role = await self._get_member_role(workspace_id, current_user)
        if role is None:
            raise ForbiddenException("No access to workspace")

        if required == "read":
            return role

        if required == "write" and role in {
            WorkspaceMemberRole.owner,
            WorkspaceMemberRole.admin,
            WorkspaceMemberRole.member,
        }:
            return role

        if required == "admin" and role in {WorkspaceMemberRole.owner, WorkspaceMemberRole.admin}:
            return role

        raise ForbiddenException("Insufficient workspace permission")

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #
    async def list_folders(self, workspace_id: uuid.UUID, *, current_user: User) -> List[WorkspaceFolder]:
        await self._ensure_permission(workspace_id, current_user, "read")
        result = await self.folder_repo.list_by_workspace(workspace_id)
        return list(result) if result is not None else []

    # ------------------------------------------------------------------ #
    # 树/循环检测辅助
    # ------------------------------------------------------------------ #
    async def _build_children_index(self, workspace_id: uuid.UUID) -> Dict[Optional[uuid.UUID], List[uuid.UUID]]:
        relations = await self.folder_repo.list_relations_by_workspace(workspace_id)
        children: Dict[Optional[uuid.UUID], List[uuid.UUID]] = {}
        for fid, pid in relations:
            children.setdefault(pid, []).append(fid)
        return children

    async def _collect_subtree_ids(self, workspace_id: uuid.UUID, root_id: uuid.UUID) -> List[uuid.UUID]:
        """
        返回 root_id 及其所有后代 folder id（BFS），用于删除/复制。
        只在 workspace 内遍历，避免跨 workspace 的 parentId 造成污染。
        """
        children_index = await self._build_children_index(workspace_id)
        queue: List[uuid.UUID] = [root_id]
        visited: Set[uuid.UUID] = set()
        out: List[uuid.UUID] = []

        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            out.append(current)
            for child_id in children_index.get(current, []):
                if child_id not in visited:
                    queue.append(child_id)

        return out

    async def _would_create_cycle(
        self,
        *,
        workspace_id: uuid.UUID,
        folder_id: uuid.UUID,
        new_parent_id: uuid.UUID,
    ) -> bool:
        """检查是否会创建循环引用"""
        seen: Set[uuid.UUID] = set()
        current: Optional[uuid.UUID] = new_parent_id

        while current is not None:
            if current == folder_id:
                return True
            if current in seen:
                return True
            seen.add(current)

            node = await self.folder_repo.ensure_same_workspace(current, workspace_id)
            current = node.parent_id

        return False

    async def _calculate_depth(self, folder_id: uuid.UUID, workspace_id: uuid.UUID) -> int:
        """
        计算文件夹的深度（从根目录开始，根目录深度为 0）
        """
        depth = 0
        current_id: Optional[uuid.UUID] = folder_id

        while current_id is not None:
            folder = await self.folder_repo.ensure_same_workspace(current_id, workspace_id)
            if folder.parent_id is None:
                break
            depth += 1
            current_id = folder.parent_id
            if depth > MAX_FOLDER_DEPTH:
                break

        return depth

    async def _check_depth_limit(self, parent_id: Optional[uuid.UUID], workspace_id: uuid.UUID) -> None:
        """检查在指定父文件夹下创建子文件夹是否会超过深度限制"""
        if parent_id is None:
            return

        parent_depth = await self._calculate_depth(parent_id, workspace_id)
        if parent_depth >= MAX_FOLDER_DEPTH:
            raise BadRequestException(f"Maximum folder depth ({MAX_FOLDER_DEPTH + 1}) would be exceeded")

    # ------------------------------------------------------------------ #
    # 创建
    # ------------------------------------------------------------------ #
    async def create_folder(
        self,
        *,
        workspace_id: uuid.UUID,
        current_user: User,
        name: str,
        color: Optional[str] = None,
        parent_id: Optional[uuid.UUID] = None,
        is_expanded: bool = False,
    ) -> WorkspaceFolder:
        await self._ensure_permission(workspace_id, current_user, "write")
        await self._check_depth_limit(parent_id, workspace_id)

        if parent_id:
            await self.folder_repo.ensure_same_workspace(parent_id, workspace_id)

        next_sort = (await self.folder_repo.max_sort_order(workspace_id, parent_id)) + 1
        folder = await self.folder_repo.create(
            {
                "name": name.strip(),
                "user_id": current_user.id,
                "workspace_id": workspace_id,
                "parent_id": parent_id,
                "color": color or "#6B7280",
                "is_expanded": is_expanded,
                "sort_order": next_sort,
            }
        )
        await self.commit()
        result = folder
        return result  # type: ignore

    # ------------------------------------------------------------------ #
    # 更新
    # ------------------------------------------------------------------ #
    async def update_folder(
        self,
        folder_id: uuid.UUID,
        *,
        workspace_id: uuid.UUID,
        current_user: User,
        name: Optional[str] = None,
        color: Optional[str] = None,
        is_expanded: Optional[bool] = None,
        parent_id: Optional[uuid.UUID] = None,
    ) -> WorkspaceFolder:
        await self._ensure_permission(workspace_id, current_user, "write")
        folder = await self.folder_repo.ensure_same_workspace(folder_id, workspace_id)

        if parent_id is not None:
            if parent_id == folder.id:
                raise BadRequestException("Folder cannot be its own parent")
            if parent_id:
                await self.folder_repo.ensure_same_workspace(parent_id, workspace_id)
                if await self._would_create_cycle(
                    workspace_id=workspace_id, folder_id=folder.id, new_parent_id=parent_id
                ):
                    raise BadRequestException("Cannot create circular folder reference")
                await self._check_depth_limit(parent_id, workspace_id)

        update_data: Dict[str, object] = {}
        if name is not None:
            update_data["name"] = name.strip()
        if color is not None:
            update_data["color"] = color
        if is_expanded is not None:
            update_data["is_expanded"] = is_expanded
        if parent_id is not None:
            update_data["parent_id"] = parent_id

        if update_data:
            folder = await self.folder_repo.update(folder.id, update_data)  # type: ignore
            await self.commit()
        result = folder
        return result  # type: ignore

    # ------------------------------------------------------------------ #
    # 删除
    # ------------------------------------------------------------------ #
    async def delete_folder(
        self,
        folder_id: uuid.UUID,
        *,
        workspace_id: uuid.UUID,
        current_user: User,
    ) -> int:
        stats = await self.delete_folder_tree(
            folder_id,
            workspace_id=workspace_id,
            current_user=current_user,
        )
        return stats["folders"]

    async def delete_folder_tree(
        self,
        folder_id: uuid.UUID,
        *,
        workspace_id: uuid.UUID,
        current_user: User,
    ) -> Dict[str, int]:
        """递归删除整个 folder 子树（软删除），需要 write 权限（member 及以上）"""
        await self._ensure_permission(workspace_id, current_user, "write")
        await self.folder_repo.ensure_same_workspace(folder_id, workspace_id)

        target_ids = await self._collect_subtree_ids(workspace_id, folder_id)
        deleted_at = datetime.now(timezone.utc)
        for folder_id_to_delete in target_ids:
            await self.folder_repo.update(folder_id_to_delete, {"deleted_at": deleted_at})

        await self.commit()
        return {"folders": len(target_ids), "workflows": 0}

    # ------------------------------------------------------------------ #
    # 复制
    # ------------------------------------------------------------------ #
    async def duplicate_folder(
        self,
        folder_id: uuid.UUID,
        *,
        workspace_id: uuid.UUID,
        current_user: User,
        name: Optional[str] = None,
        parent_id: Optional[uuid.UUID] = None,
        color: Optional[str] = None,
    ) -> WorkspaceFolder:
        source = await self.folder_repo.get(folder_id)
        if not source:
            raise NotFoundException("Folder not found")

        await self._ensure_permission(source.workspace_id, current_user, "read")
        await self._ensure_permission(workspace_id, current_user, "write")

        effective_parent_id: Optional[uuid.UUID]
        if parent_id is not None:
            effective_parent_id = parent_id
        else:
            effective_parent_id = source.parent_id if workspace_id == source.workspace_id else None

        if effective_parent_id:
            await self.folder_repo.ensure_same_workspace(effective_parent_id, workspace_id)

        source_subtree_ids = await self._collect_subtree_ids(source.workspace_id, source.id)
        folders_result = await self.db.execute(
            select(WorkspaceFolder).where(WorkspaceFolder.id.in_(source_subtree_ids))
        )
        source_folders = list(folders_result.scalars().all())
        source_by_id: Dict[uuid.UUID, WorkspaceFolder] = {f.id: f for f in source_folders}
        folder_id_map: Dict[uuid.UUID, uuid.UUID] = {fid: uuid.uuid4() for fid in source_subtree_ids}

        async with self.db.begin():
            new_root_id = folder_id_map[source.id]
            new_root = WorkspaceFolder(
                id=new_root_id,
                name=(name or f"{source.name} 副本").strip(),
                user_id=current_user.id,
                workspace_id=workspace_id,
                parent_id=effective_parent_id,
                color=color or source.color,
                is_expanded=False,
                sort_order=source.sort_order,
            )
            self.db.add(new_root)
            await self.db.flush()

            children_index = await self._build_children_index(source.workspace_id)
            queue: List[Tuple[uuid.UUID, uuid.UUID]] = [(source.id, new_root_id)]

            while queue:
                old_parent_id, new_parent_id = queue.pop(0)
                for old_child_id in children_index.get(old_parent_id, []):
                    if old_child_id not in source_by_id:
                        continue
                    old_child = source_by_id[old_child_id]
                    new_child_id = folder_id_map[old_child_id]

                    self.db.add(
                        WorkspaceFolder(
                            id=new_child_id,
                            name=old_child.name.strip(),
                            user_id=current_user.id,
                            workspace_id=workspace_id,
                            parent_id=new_parent_id,
                            color=old_child.color,
                            is_expanded=False,
                            sort_order=old_child.sort_order,
                        )
                    )
                    queue.append((old_child_id, new_child_id))

            await self.db.flush()

        await self.commit()
        result = await self.folder_repo.get(new_root_id)
        return result  # type: ignore
