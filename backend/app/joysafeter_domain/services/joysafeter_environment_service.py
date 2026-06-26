import uuid
from typing import Optional

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.schemas.joysafeter_environment import (
    CreateEnvironmentRequest,
    UpdateEnvironmentRequest,
)
from app.joysafeter_shared.utils.datetime import utc_now


class EnvironmentService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_environment(self, req: CreateEnvironmentRequest, project_id: Optional[str] = None) -> JoySafeterEnvironment:
        # Purge any soft-deleted rows with the same name before inserting
        await self.db.execute(
            delete(JoySafeterEnvironment).where(
                and_(
                    JoySafeterEnvironment.name == req.name,
                    JoySafeterEnvironment.deleted_at.is_not(None),
                )
            )
        )
        kwargs = dict(
            name=req.name,
            description=req.description,
            metadata_=req.metadata,
            config=req.config.model_dump(),
        )
        if project_id is not None:
            kwargs["project_id"] = project_id
        env = JoySafeterEnvironment(**kwargs)
        self.db.add(env)
        await self.db.commit()
        await self.db.refresh(env)
        return env

    async def get_environment(self, env_id: uuid.UUID, project_id: Optional[str] = None) -> Optional[JoySafeterEnvironment]:
        conditions = [
            JoySafeterEnvironment.id == env_id,
            JoySafeterEnvironment.deleted_at.is_(None),
        ]
        if project_id is not None:
            conditions.append(JoySafeterEnvironment.project_id == project_id)
        result = await self.db.execute(
            select(JoySafeterEnvironment).where(and_(*conditions))
        )
        return result.scalar_one_or_none()

    async def get_environment_by_ref(self, ref: str, project_id: Optional[str] = None) -> Optional[JoySafeterEnvironment]:
        """If ref starts with 'env_', try to parse as UUID and query by ID.
        Otherwise query by name. Filter deleted_at IS NULL."""
        if ref.startswith("env_"):
            try:
                env_id = uuid.UUID(ref[len("env_"):])
                return await self.get_environment(env_id, project_id=project_id)
            except ValueError:
                pass
        # Fall back to name lookup
        conditions = [
            JoySafeterEnvironment.name == ref,
            JoySafeterEnvironment.deleted_at.is_(None),
        ]
        if project_id is not None:
            conditions.append(JoySafeterEnvironment.project_id == project_id)
        result = await self.db.execute(
            select(JoySafeterEnvironment).where(and_(*conditions))
        )
        return result.scalar_one_or_none()

    async def list_environments(
        self,
        limit: int = 20,
        after_id: Optional[uuid.UUID] = None,
        include_archived: bool = False,
        project_id: Optional[str] = None,
    ) -> tuple[list[JoySafeterEnvironment], bool]:
        q = select(JoySafeterEnvironment).where(JoySafeterEnvironment.deleted_at.is_(None))
        if not include_archived:
            q = q.where(JoySafeterEnvironment.archived_at.is_(None))
        if project_id is not None:
            q = q.where(JoySafeterEnvironment.project_id == project_id)
        if after_id:
            q = q.where(JoySafeterEnvironment.id < after_id)
        q = q.order_by(JoySafeterEnvironment.created_at.desc()).limit(limit + 1)
        result = await self.db.execute(q)
        envs = list(result.scalars().all())
        has_more = len(envs) > limit
        return envs[:limit], has_more

    async def update_environment(
        self,
        env_id: uuid.UUID,
        req: UpdateEnvironmentRequest,
        project_id: Optional[str] = None,
    ) -> Optional[JoySafeterEnvironment]:
        env = await self.get_environment(env_id, project_id=project_id)
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

    async def delete_environment(
        self, env_id: uuid.UUID, project_id: Optional[str] = None
    ) -> bool:
        env = await self.get_environment(env_id, project_id=project_id)
        if not env:
            return False
        env.deleted_at = utc_now()
        await self.db.commit()
        return True

    async def archive_environment(
        self, env_id: uuid.UUID, project_id: Optional[str] = None
    ) -> bool:
        env = await self.get_environment(env_id, project_id=project_id)
        if not env:
            return False
        if env.archived_at:
            return True
        env.archived_at = utc_now()
        await self.db.commit()
        return True

    async def environment_is_referenced_by_sessions(
        self,
        env_name: str,
        env_id: uuid.UUID,
        project_id: Optional[str] = None,
    ) -> bool:
        """Check if any session has environment_ref matching either the name or
        env_<uuid> format AND archived_at IS NULL."""
        env_prefixed = f"env_{env_id}"
        conditions = [
            or_(
                JoySafeterSession.environment_ref == env_name,
                JoySafeterSession.environment_ref == env_prefixed,
            ),
            JoySafeterSession.archived_at.is_(None),
        ]
        if project_id is not None:
            conditions.append(JoySafeterSession.project_id == project_id)
        result = await self.db.execute(
            select(JoySafeterSession.id).where(and_(*conditions)).limit(1)
        )
        return result.scalar_one_or_none() is not None
