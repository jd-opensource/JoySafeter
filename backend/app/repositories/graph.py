"""
Graph 相关 Repository
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.graph import AgentGraph, GraphEdge, GraphNode

from .base import BaseRepository


def _graph_not_deleted(query):
    """Filter out soft-deleted graphs."""
    return query.where(AgentGraph.deleted_at.is_(None))


class GraphRepository(BaseRepository[AgentGraph]):
    """Agent Graph Repository (soft-delete aware)"""

    def __init__(self, db: AsyncSession):
        super().__init__(AgentGraph, db)

    async def get(self, id: uuid.UUID, relations: Optional[List[str]] = None):
        """Get graph by ID; returns None if deleted."""
        query = select(AgentGraph).where(AgentGraph.id == id)
        query = _graph_not_deleted(query)
        if relations:
            for rel in relations:
                if hasattr(AgentGraph, rel):
                    query = query.options(selectinload(getattr(AgentGraph, rel)))
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: str) -> List[AgentGraph]:
        """根据用户ID获取所有图（排除已软删除）"""
        query = select(AgentGraph).where(AgentGraph.user_id == user_id)
        query = _graph_not_deleted(query)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_by_workspace(self, workspace_id: uuid.UUID) -> List[AgentGraph]:
        """根据工作空间ID获取所有图"""
        return []

    async def list_by_parent(self, parent_id: uuid.UUID) -> List[AgentGraph]:
        """根据父图ID获取子图列表（排除已软删除）"""
        query = select(AgentGraph).where(AgentGraph.parent_id == parent_id)
        query = _graph_not_deleted(query)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_by_user_with_filters(
        self,
        user_id: str,
        parent_id: Optional[uuid.UUID] = None,
        workspace_id: Optional[uuid.UUID] = None,
    ) -> List[AgentGraph]:
        """根据用户ID获取图列表（排除已软删除）"""
        query = select(AgentGraph).where(AgentGraph.user_id == user_id)
        query = _graph_not_deleted(query)
        if parent_id is not None:
            query = query.where(AgentGraph.parent_id == parent_id)
        if workspace_id is not None:
            query = query.where(AgentGraph.workspace_id == workspace_id)
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
