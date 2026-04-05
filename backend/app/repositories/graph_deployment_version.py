"""
Graph deployment version Repository
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
    """Graph deployment version Repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(GraphDeploymentVersion, db)

    async def get_by_graph_and_version(self, graph_id: uuid.UUID, version: int) -> Optional[GraphDeploymentVersion]:
        """Get a specific version of a graph."""
        query = select(GraphDeploymentVersion).where(
            and_(
                GraphDeploymentVersion.graph_id == graph_id,
                GraphDeploymentVersion.version == version,
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_active_version(self, graph_id: uuid.UUID) -> Optional[GraphDeploymentVersion]:
        """Get the active version of a graph."""
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
        """List all versions of a graph."""
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
        """List versions of a graph (paginated).

        Returns:
            tuple: (version list, total count)
        """
        base_query = select(GraphDeploymentVersion).where(GraphDeploymentVersion.graph_id == graph_id)

        if not include_inactive:
            base_query = base_query.where(GraphDeploymentVersion.is_active)

        # get total count
        count_query = select(func.count()).where(GraphDeploymentVersion.graph_id == graph_id)
        if not include_inactive:
            count_query = count_query.where(GraphDeploymentVersion.is_active)
        count_result = await self.db.execute(count_query)
        total = count_result.scalar() or 0

        # paginated query
        offset = (page - 1) * page_size
        query = base_query.order_by(GraphDeploymentVersion.version.desc()).offset(offset).limit(page_size)

        result = await self.db.execute(query)
        versions = list(result.scalars().all())

        return versions, total

    async def get_next_version_number(self, graph_id: uuid.UUID) -> int:
        """Get the next version number."""
        query = select(func.coalesce(func.max(GraphDeploymentVersion.version), 0)).where(
            GraphDeploymentVersion.graph_id == graph_id
        )
        result = await self.db.execute(query)
        max_version = result.scalar() or 0
        return max_version + 1

    async def deactivate_all_versions(self, graph_id: uuid.UUID) -> int:
        """Deactivate all versions of a graph."""
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
        """Create a new version."""
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
        """Activate a specific version."""
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
        """Rename a version."""
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
        """Count versions for a graph."""
        query = select(func.count()).where(GraphDeploymentVersion.graph_id == graph_id)
        result = await self.db.execute(query)
        return result.scalar() or 0

    async def delete_by_graph(self, graph_id: uuid.UUID) -> int:
        """Delete all versions of a graph."""
        stmt = delete(GraphDeploymentVersion).where(GraphDeploymentVersion.graph_id == graph_id)
        result = await self.db.execute(stmt)
        return getattr(result, "rowcount", 0) or 0

    async def delete_version(self, graph_id: uuid.UUID, version: int) -> int:
        """Delete a specific version."""
        stmt = delete(GraphDeploymentVersion).where(
            and_(
                GraphDeploymentVersion.graph_id == graph_id,
                GraphDeploymentVersion.version == version,
            )
        )
        result = await self.db.execute(stmt)
        return getattr(result, "rowcount", 0) or 0
