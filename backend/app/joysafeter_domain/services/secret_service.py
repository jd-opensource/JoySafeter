import uuid
from typing import Optional

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.agent import JoySafeterAgent
from app.joysafeter_domain.models.secret import JoySafeterSecret
from app.joysafeter_domain.schemas.secret import CreateSecretRequest, UpdateSecretRequest
from app.joysafeter_shared.utils.datetime import utc_now


class SecretService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_secret(self, req: CreateSecretRequest, project_id: Optional[str] = None) -> JoySafeterSecret:
        # Purge any soft-deleted row with the same name before inserting
        await self.db.execute(
            delete(JoySafeterSecret).where(
                and_(
                    JoySafeterSecret.name == req.name,
                    JoySafeterSecret.deleted_at.is_not(None),
                )
            )
        )
        kwargs = dict(name=req.name, data=req.data)
        if project_id is not None:
            kwargs["project_id"] = project_id
        secret = JoySafeterSecret(**kwargs)
        self.db.add(secret)
        await self.db.commit()
        await self.db.refresh(secret)
        return secret

    async def get_secret(self, secret_id: uuid.UUID) -> Optional[JoySafeterSecret]:
        result = await self.db.execute(
            select(JoySafeterSecret).where(
                and_(
                    JoySafeterSecret.id == secret_id,
                    JoySafeterSecret.deleted_at.is_(None),
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_secret_by_name(
        self, name: str, project_id: Optional[str] = None
    ) -> Optional[JoySafeterSecret]:
        conditions = [
            JoySafeterSecret.name == name,
            JoySafeterSecret.deleted_at.is_(None),
        ]
        if project_id:
            conditions.append(JoySafeterSecret.project_id == project_id)
        result = await self.db.execute(
            select(JoySafeterSecret).where(and_(*conditions))
        )
        return result.scalar_one_or_none()

    async def list_secrets(
        self, limit: int = 20, after_id: Optional[uuid.UUID] = None, project_id: Optional[str] = None
    ) -> tuple[list[JoySafeterSecret], bool]:
        q = select(JoySafeterSecret).where(JoySafeterSecret.deleted_at.is_(None))
        if project_id is not None:
            q = q.where(JoySafeterSecret.project_id == project_id)
        if after_id:
            q = q.where(JoySafeterSecret.id < after_id)
        q = q.order_by(JoySafeterSecret.created_at.desc()).limit(limit + 1)
        result = await self.db.execute(q)
        secrets = list(result.scalars().all())
        has_more = len(secrets) > limit
        return secrets[:limit], has_more

    async def update_secret(
        self, secret_id: uuid.UUID, req: UpdateSecretRequest
    ) -> Optional[JoySafeterSecret]:
        secret = await self.get_secret(secret_id)
        if not secret:
            return None
        secret.data = req.data
        secret.updated_at = utc_now()
        await self.db.commit()
        await self.db.refresh(secret)
        return secret

    async def delete_secret(self, secret_id: uuid.UUID) -> bool:
        secret = await self.get_secret(secret_id)
        if not secret:
            return False
        secret.deleted_at = utc_now()
        await self.db.commit()
        return True

    async def hard_delete_secret(self, secret_id: uuid.UUID) -> None:
        """Physical DELETE FROM joysafeter_secrets WHERE id = :id."""
        await self.db.execute(
            delete(JoySafeterSecret).where(JoySafeterSecret.id == secret_id)
        )
        await self.db.commit()

    async def secret_is_referenced(self, name: str) -> bool:
        """Check if any agent has secret_ref = name AND deleted_at IS NULL."""
        result = await self.db.execute(
            select(JoySafeterAgent.id).where(
                and_(
                    JoySafeterAgent.secret_ref == name,
                    JoySafeterAgent.deleted_at.is_(None),
                )
            ).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def secret_is_referenced_by_agent(self, name: str) -> Optional[str]:
        """Return the name of the first agent referencing this secret, or None."""
        result = await self.db.execute(
            select(JoySafeterAgent.name).where(
                and_(
                    JoySafeterAgent.secret_ref == name,
                    JoySafeterAgent.deleted_at.is_(None),
                )
            ).limit(1)
        )
        return result.scalar_one_or_none()
