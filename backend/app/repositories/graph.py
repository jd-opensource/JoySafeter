"""
Graph 相关 Repository
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.graph import AgentGraph, GraphEdge, GraphNode

from .base import BaseRepository


class GraphRepository(BaseRepository[AgentGraph]):
    """Agent Graph Repository"""

    def __init__(self, db: AsyncSession):
        super().__init__(AgentGraph, db)

    async def list_by_user(self, user_id: str) -> List[AgentGraph]:
        """根据用户ID获取所有图"""
        query = select(AgentGraph).where(AgentGraph.user_id == user_id)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_by_workspace(self, workspace_id: uuid.UUID) -> List[AgentGraph]:
        """根据工作空间ID获取所有图"""
        # workspace_id field not in database, return empty list
        return []

    async def list_by_parent(self, parent_id: uuid.UUID) -> List[AgentGraph]:
        """根据父图ID获取子图列表"""
        query = select(AgentGraph).where(AgentGraph.parent_id == parent_id)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_by_user_with_filters(
        self,
        user_id: str,
        parent_id: Optional[uuid.UUID] = None,
        workspace_id: Optional[uuid.UUID] = None,
    ) -> List[AgentGraph]:
        """
        根据用户ID获取图列表，支持额外的过滤条件

        Args:
            user_id: 用户ID（必需）
            parent_id: 父图ID（可选，用于过滤子图）
            workspace_id: 工作空间ID（可选，用于过滤工作空间下的图）

        Returns:
            符合条件的图列表，按更新时间倒序排列（最新的在前）
        """
        query = select(AgentGraph).where(AgentGraph.user_id == user_id)

        # 添加 parent_id 过滤（如果提供）
        if parent_id is not None:
            query = query.where(AgentGraph.parent_id == parent_id)

        # 添加 workspace_id 过滤（如果提供）
        if workspace_id is not None:
            query = query.where(AgentGraph.workspace_id == workspace_id)

        # 按更新时间倒序排列（最新的在前），如果更新时间相同则按ID倒序排列以确保排序稳定
        query = query.order_by(AgentGraph.updated_at.desc(), AgentGraph.id.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())


class GraphNodeRepository(BaseRepository[GraphNode]):
    """Graph Node Repository"""

    def __init__(self, db: AsyncSession):
        super().__init__(GraphNode, db)

    async def list_by_graph(self, graph_id: uuid.UUID) -> List[GraphNode]:
        """根据图ID获取所有节点"""
        query = select(GraphNode).where(GraphNode.graph_id == graph_id)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def delete_by_graph(self, graph_id: uuid.UUID) -> int:
        """删除图的所有节点"""
        stmt = delete(GraphNode).where(GraphNode.graph_id == graph_id)
        result = await self.db.execute(stmt)
        return getattr(result, "rowcount", 0) or 0

    async def delete_by_ids(self, graph_id: uuid.UUID, node_ids: List[uuid.UUID]) -> int:
        """批量删除节点"""
        if not node_ids:
            return 0
        stmt = delete(GraphNode).where(
            and_(
                GraphNode.graph_id == graph_id,
                GraphNode.id.in_(node_ids),
            )
        )
        result = await self.db.execute(stmt)
        return getattr(result, "rowcount", 0) or 0


class GraphEdgeRepository(BaseRepository[GraphEdge]):
    """Graph Edge Repository"""

    def __init__(self, db: AsyncSession):
        super().__init__(GraphEdge, db)

    async def list_by_graph(self, graph_id: uuid.UUID) -> List[GraphEdge]:
        """根据图ID获取所有边"""
        query = select(GraphEdge).where(GraphEdge.graph_id == graph_id)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def delete_by_graph(self, graph_id: uuid.UUID) -> int:
        """删除图的所有边"""
        stmt = delete(GraphEdge).where(GraphEdge.graph_id == graph_id)
        result = await self.db.execute(stmt)
        return getattr(result, "rowcount", 0) or 0

    async def delete_by_node_ids(self, graph_id: uuid.UUID, node_ids: List[uuid.UUID]) -> int:
        """删除与指定节点相关的所有边"""
        if not node_ids:
            return 0
        stmt = delete(GraphEdge).where(
            and_(
                GraphEdge.graph_id == graph_id,
                or_(
                    GraphEdge.source_node_id.in_(node_ids),
                    GraphEdge.target_node_id.in_(node_ids),
                ),
            )
        )
        result = await self.db.execute(stmt)
        return getattr(result, "rowcount", 0) or 0
