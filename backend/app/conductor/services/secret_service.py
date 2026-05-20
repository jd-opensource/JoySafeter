import uuid
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.conductor.models.secret import ConductorSecret
from app.conductor.schemas.secret import CreateSecretRequest, UpdateSecretRequest
from app.utils.datetime import utc_now


class SecretService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_secret(self, req: CreateSecretRequest) -> ConductorSecret:
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
