import uuid
from typing import Optional

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import ConductorAgent
from app.models.secret import ConductorSecret
from app.schemas.secret import CreateSecretRequest, UpdateSecretRequest
from app.utils.datetime import utc_now


class SecretService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_secret(self, req: CreateSecretRequest) -> ConductorSecret:
        # Purge any soft-deleted row with the same name before inserting
        await self.db.execute(
            delete(ConductorSecret).where(
                and_(
                    ConductorSecret.name == req.name,
                    ConductorSecret.deleted_at.is_not(None),
                )
            )
        )
        secret = ConductorSecret(name=req.name, data=req.data)
        self.db.add(secret)
        await self.db.commit()
        await self.db.refresh(secret)
        return secret

    async def get_secret(self, secret_id: uuid.UUID) -> Optional[ConductorSecret]:
        result = await self.db.execute(
            select(ConductorSecret).where(
                and_(
                    ConductorSecret.id == secret_id,
                    ConductorSecret.deleted_at.is_(None),
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_secret_by_name(self, name: str) -> Optional[ConductorSecret]:
        result = await self.db.execute(
            select(ConductorSecret).where(
                and_(
                    ConductorSecret.name == name,
                    ConductorSecret.deleted_at.is_(None),
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_secrets(
        self, limit: int = 20, after_id: Optional[uuid.UUID] = None
    ) -> tuple[list[ConductorSecret], bool]:
        q = select(ConductorSecret).where(ConductorSecret.deleted_at.is_(None))
        if after_id:
            q = q.where(ConductorSecret.id < after_id)
        q = q.order_by(ConductorSecret.created_at.desc()).limit(limit + 1)
        result = await self.db.execute(q)
        secrets = list(result.scalars().all())
        has_more = len(secrets) > limit
        return secrets[:limit], has_more

    async def update_secret(
        self, secret_id: uuid.UUID, req: UpdateSecretRequest
    ) -> Optional[ConductorSecret]:
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
        """Physical DELETE FROM conductor_secrets WHERE id = :id."""
        await self.db.execute(
            delete(ConductorSecret).where(ConductorSecret.id == secret_id)
        )
        await self.db.commit()

    async def secret_is_referenced(self, name: str) -> bool:
        """Check if any agent has secret_ref = name AND deleted_at IS NULL."""
        result = await self.db.execute(
            select(ConductorAgent.id).where(
                and_(
                    ConductorAgent.secret_ref == name,
                    ConductorAgent.deleted_at.is_(None),
                )
            ).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def secret_is_referenced_by_agent(self, name: str) -> Optional[str]:
        """Return the name of the first agent referencing this secret, or None."""
        result = await self.db.execute(
            select(ConductorAgent.name).where(
                and_(
                    ConductorAgent.secret_ref == name,
                    ConductorAgent.deleted_at.is_(None),
                )
            ).limit(1)
        )
        return result.scalar_one_or_none()
