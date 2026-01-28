"""
CustomTool 服务：权限校验 + 配额限制 + CRUD
"""

from __future__ import annotations

import uuid
from typing import Dict, List, Optional

from app.common.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.models.custom_tool import CustomTool
from app.repositories.custom_tool import CustomToolRepository

from .base import BaseService

MAX_TOOLS_PER_USER = 100


class CustomToolService(BaseService[CustomTool]):
    def __init__(self, db):
        super().__init__(db)
        self.repo = CustomToolRepository(db)

    async def list_tools(self, current_user_id: str) -> List[CustomTool]:
        """获取当前用户的所有工具"""
        return await self.repo.list_by_user(current_user_id)  # type: ignore

    async def create_tool(
        self,
        owner_id: str,
        name: str,
        code: str,
        schema: Dict,
        runtime: str = "python",
        enabled: bool = True,
    ) -> CustomTool:
        """创建工具"""
        current_count = await self.repo.count_by_user(owner_id)
        if current_count >= MAX_TOOLS_PER_USER:
            raise BadRequestException("User custom tool quota exceeded")

        # 检查同名工具是否存在
        existing = await self.repo.get_by(owner_id=owner_id, name=name)
        if existing:
            raise BadRequestException("Tool name already exists for this user")

        tool = CustomTool(
            owner_id=owner_id,
            name=name,
            code=code,
            schema=schema or {},
            runtime=runtime or "python",
            enabled=enabled,
        )
        self.db.add(tool)
        await self.db.commit()
        await self.db.refresh(tool)
        return tool

    async def update_tool(
        self,
        tool_id: uuid.UUID,
        current_user_id: str,
        *,
        name: Optional[str] = None,
        code: Optional[str] = None,
        schema: Optional[Dict] = None,
        runtime: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> CustomTool:
        """更新工具"""
        tool = await self.repo.get(tool_id)
        if not tool:
            raise NotFoundException("Custom tool not found")

        # 验证所有权
        if tool.owner_id != current_user_id:
            raise ForbiddenException("You can only update your own tools")

        if name and name != tool.name:
            existing = await self.repo.get_by(owner_id=current_user_id, name=name)
            if existing:
                raise BadRequestException("Tool name already exists for this user")
            tool.name = name
        if code is not None:
            tool.code = code
        if schema is not None:
            tool.schema = schema
        if runtime is not None:
            tool.runtime = runtime
        if enabled is not None:
            tool.enabled = enabled

        await self.db.commit()
        await self.db.refresh(tool)
        return tool  # type: ignore

    async def delete_tool(self, tool_id: uuid.UUID, current_user_id: str) -> None:
        """删除工具"""
        tool = await self.repo.get(tool_id)
        if not tool:
            raise NotFoundException("Custom tool not found")

        # 验证所有权
        if tool.owner_id != current_user_id:
            raise ForbiddenException("You can only delete your own tools")

        await self.repo.delete_by_id(tool_id)
        await self.db.commit()
