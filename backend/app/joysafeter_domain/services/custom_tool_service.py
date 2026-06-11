"""
CustomTool service: permission checks + quota limits + CRUD.
"""

from __future__ import annotations

import uuid
from typing import Dict, List, Optional

from app.joysafeter_shared.common.app_errors import AccessDeniedError, InvalidRequestError, NotFoundError
from app.joysafeter_domain.models.custom_tool import CustomTool
from app.joysafeter_domain.repositories.custom_tool import CustomToolRepository

from .base import BaseService

MAX_TOOLS_PER_USER = 100


class CustomToolService(BaseService[CustomTool]):
    def __init__(self, db):
        super().__init__(db)
        self.repo = CustomToolRepository(db)

    async def list_tools(self, current_user_id: str) -> List[CustomTool]:
        """Get all tools for the current user."""
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
        """Create a tool."""
        current_count = await self.repo.count_by_user(owner_id)
        if current_count >= MAX_TOOLS_PER_USER:
            raise InvalidRequestError(
                "User custom tool quota exceeded",
                code="CUSTOM_TOOL_QUOTA_EXCEEDED",
                data={"limit": MAX_TOOLS_PER_USER},
            )

        # check if a tool with the same name exists
        existing = await self.repo.get_by(owner_id=owner_id, name=name)
        if existing:
            raise InvalidRequestError(
                "Tool name already exists for this user",
                code="CUSTOM_TOOL_NAME_ALREADY_EXISTS",
                data={"name": name},
            )

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
        """Update a tool."""
        tool = await self.repo.get(tool_id)
        if not tool:
            raise NotFoundError("Custom tool not found", code="CUSTOM_TOOL_NOT_FOUND", data={"tool_id": str(tool_id)})

        # verify ownership
        if tool.owner_id != current_user_id:
            raise AccessDeniedError(
                "You can only update your own tools",
                code="CUSTOM_TOOL_UPDATE_FORBIDDEN",
                data={"tool_id": str(tool_id)},
            )

        if name and name != tool.name:
            existing = await self.repo.get_by(owner_id=current_user_id, name=name)
            if existing:
                raise InvalidRequestError(
                    "Tool name already exists for this user",
                    code="CUSTOM_TOOL_NAME_ALREADY_EXISTS",
                    data={"name": name},
                )
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
        """Delete a tool."""
        tool = await self.repo.get(tool_id)
        if not tool:
            raise NotFoundError("Custom tool not found", code="CUSTOM_TOOL_NOT_FOUND", data={"tool_id": str(tool_id)})

        # verify ownership
        if tool.owner_id != current_user_id:
            raise AccessDeniedError(
                "You can only delete your own tools",
                code="CUSTOM_TOOL_DELETE_FORBIDDEN",
                data={"tool_id": str(tool_id)},
            )

        await self.repo.delete_by_id(tool_id)
        await self.db.commit()
