import uuid
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.conductor.models.environment import ConductorEnvironment
from app.conductor.schemas.environment import (
    CreateEnvironmentRequest,
    UpdateEnvironmentRequest,
)
from app.utils.datetime import utc_now


class EnvironmentService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_environment(self, req: CreateEnvironmentRequest) -> ConductorEnvironment:
        env = ConductorEnvironment(
            name=req.name,
            description=req.description,
            metadata_=req.metadata,
            config=req.config.model_dump(),
        )
        self.db.add(env)
        await self.db.commit()
        await self.db.refresh(env)
        return env

    async def get_environment(self, env_id: uuid.UUID) -> Optional[ConductorEnvironment]:
        result = await self.db.execute(
            select(ConductorEnvironment).where(
                and_(
                    ConductorEnvironment.id == env_id,
                    ConductorEnvironment.deleted_at.is_(None),
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_environment_by_ref(self, ref: str) -> Optional[ConductorEnvironment]:
        result = await self.db.execute(
            select(ConductorEnvironment).where(
                and_(
                    ConductorEnvironment.name == ref,
                    ConductorEnvironment.deleted_at.is_(None),
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_environments(
        self, limit: int = 20, after_id: Optional[uuid.UUID] = None
    ) -> tuple[list[ConductorEnvironment], bool]:
        q = select(ConductorEnvironment).where(ConductorEnvironment.deleted_at.is_(None))
        if after_id:
            q = q.where(ConductorEnvironment.id < after_id)
        q = q.order_by(ConductorEnvironment.created_at.desc()).limit(limit + 1)
        result = await self.db.execute(q)
        envs = list(result.scalars().all())
        has_more = len(envs) > limit
        return envs[:limit], has_more

    async def update_environment(
        self, env_id: uuid.UUID, req: UpdateEnvironmentRequest
    ) -> Optional[ConductorEnvironment]:
        env = await self.get_environment(env_id)
        if not env:
            return None
        if req.name is not None:
            env.name = req.name
        if req.description is not None:
            env.description = req.description
        if req.metadata is not None:
            env.metadata_ = req.metadata
        if req.config is not None:
            env.config = req.config.model_dump()
        env.updated_at = utc_now()
        await self.db.commit()
        await self.db.refresh(env)
        return env

    async def delete_environment(self, env_id: uuid.UUID) -> bool:
        env = await self.get_environment(env_id)
        if not env:
            return False
        env.deleted_at = utc_now()
        await self.db.commit()
        return True

    async def archive_environment(self, env_id: uuid.UUID) -> bool:
        env = await self.get_environment(env_id)
        if not env:
            return False
        if env.archived_at:
            return True
        env.archived_at = utc_now()
        await self.db.commit()
        return True
