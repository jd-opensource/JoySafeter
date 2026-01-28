"""
Graph 部署版本 Repository
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.graph_deployment_version import GraphDeploymentVersion

from .base import BaseRepository


class GraphDeploymentVersionRepository(BaseRepository[GraphDeploymentVersion]):
    """Graph 部署版本 Repository"""

    def __init__(self, db: AsyncSession):
        super().__init__(GraphDeploymentVersion, db)

    async def get_by_graph_and_version(self, graph_id: uuid.UUID, version: int) -> Optional[GraphDeploymentVersion]:
        """获取指定 graph 的指定版本"""
        query = select(GraphDeploymentVersion).where(
            and_(
                GraphDeploymentVersion.graph_id == graph_id,
                GraphDeploymentVersion.version == version,
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_active_version(self, graph_id: uuid.UUID) -> Optional[GraphDeploymentVersion]:
        """获取指定 graph 的活跃版本"""
        query = (
            select(GraphDeploymentVersion)
            .where(
                and_(
                    GraphDeploymentVersion.graph_id == graph_id,
                    GraphDeploymentVersion.is_active,
                )
            )
            .order_by(GraphDeploymentVersion.created_at.desc())
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_by_graph(self, graph_id: uuid.UUID, include_inactive: bool = True) -> List[GraphDeploymentVersion]:
        """获取指定 graph 的所有版本"""
        query = select(GraphDeploymentVersion).where(GraphDeploymentVersion.graph_id == graph_id)

        if not include_inactive:
            query = query.where(GraphDeploymentVersion.is_active)

        query = query.order_by(GraphDeploymentVersion.version.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_by_graph_paginated(
        self,
        graph_id: uuid.UUID,
        page: int = 1,
        page_size: int = 10,
        include_inactive: bool = True,
    ) -> tuple[List[GraphDeploymentVersion], int]:
        """获取指定 graph 的版本（分页）

        Returns:
            tuple: (版本列表, 总数量)
        """
        base_query = select(GraphDeploymentVersion).where(GraphDeploymentVersion.graph_id == graph_id)

        if not include_inactive:
            base_query = base_query.where(GraphDeploymentVersion.is_active)

        # 获取总数
        count_query = select(func.count()).where(GraphDeploymentVersion.graph_id == graph_id)
        if not include_inactive:
            count_query = count_query.where(GraphDeploymentVersion.is_active)
        count_result = await self.db.execute(count_query)
        total = count_result.scalar() or 0

        # 分页查询
        offset = (page - 1) * page_size
        query = base_query.order_by(GraphDeploymentVersion.version.desc()).offset(offset).limit(page_size)

        result = await self.db.execute(query)
        versions = list(result.scalars().all())

        return versions, total

    async def get_next_version_number(self, graph_id: uuid.UUID) -> int:
        """获取下一个版本号"""
        query = select(func.coalesce(func.max(GraphDeploymentVersion.version), 0)).where(
            GraphDeploymentVersion.graph_id == graph_id
        )
        result = await self.db.execute(query)
        max_version = result.scalar() or 0
        return max_version + 1

    async def deactivate_all_versions(self, graph_id: uuid.UUID) -> int:
        """停用指定 graph 的所有版本"""
        stmt = update(GraphDeploymentVersion).where(GraphDeploymentVersion.graph_id == graph_id).values(is_active=False)
        result = await self.db.execute(stmt)
        return getattr(result, "rowcount", 0) or 0

    async def create_version(
        self,
        graph_id: uuid.UUID,
        state: Dict[str, Any],
        created_by: Optional[str] = None,
        name: Optional[str] = None,
    ) -> GraphDeploymentVersion:
        """创建新版本"""
        next_version = await self.get_next_version_number(graph_id)
        await self.deactivate_all_versions(graph_id)

        version_data = {
            "graph_id": graph_id,
            "version": next_version,
            "state": state,
            "is_active": True,
            "created_at": datetime.now(timezone.utc),
        }
        if created_by is not None:
            version_data["created_by"] = created_by
        if name is not None:
            version_data["name"] = name

        instance = GraphDeploymentVersion(**version_data)
        self.db.add(instance)
        await self.db.flush()
        await self.db.refresh(instance)

        return instance

    async def activate_version(self, graph_id: uuid.UUID, version: int) -> Optional[GraphDeploymentVersion]:
        """激活指定版本"""
        await self.deactivate_all_versions(graph_id)

        stmt = (
            update(GraphDeploymentVersion)
            .where(
                and_(
                    GraphDeploymentVersion.graph_id == graph_id,
                    GraphDeploymentVersion.version == version,
                )
            )
            .values(is_active=True)
        )
        await self.db.execute(stmt)
        await self.db.flush()

        return await self.get_by_graph_and_version(graph_id, version)

    async def rename_version(self, graph_id: uuid.UUID, version: int, name: str) -> Optional[GraphDeploymentVersion]:
        """重命名版本"""
        stmt = (
            update(GraphDeploymentVersion)
            .where(
                and_(
                    GraphDeploymentVersion.graph_id == graph_id,
                    GraphDeploymentVersion.version == version,
                )
            )
            .values(name=name)
        )
        await self.db.execute(stmt)
        await self.db.flush()

        return await self.get_by_graph_and_version(graph_id, version)

    async def count_by_graph(self, graph_id: uuid.UUID) -> int:
        """计算指定 graph 的版本数量"""
        query = select(func.count()).where(GraphDeploymentVersion.graph_id == graph_id)
        result = await self.db.execute(query)
        return result.scalar() or 0

    async def delete_by_graph(self, graph_id: uuid.UUID) -> int:
        """删除指定 graph 的所有版本"""
        stmt = delete(GraphDeploymentVersion).where(GraphDeploymentVersion.graph_id == graph_id)
        result = await self.db.execute(stmt)
        return getattr(result, "rowcount", 0) or 0

    async def delete_version(self, graph_id: uuid.UUID, version: int) -> int:
        """删除指定版本"""
        stmt = delete(GraphDeploymentVersion).where(
            and_(
                GraphDeploymentVersion.graph_id == graph_id,
                GraphDeploymentVersion.version == version,
            )
        )
        result = await self.db.execute(stmt)
        return getattr(result, "rowcount", 0) or 0
