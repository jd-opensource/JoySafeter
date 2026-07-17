import hashlib
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_api_key import JoySafeterApiKey


class ApiKeyService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_api_key(
        self,
        project_id: str,
        org_id: str,
        name: str,
        created_by: str,
        role: str = "viewer",
    ) -> Tuple[JoySafeterApiKey, str]:
        raw_key = f"cnkey_{uuid.uuid4().hex}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_prefix = raw_key[:16]
        api_key = JoySafeterApiKey(
            id=uuid.uuid4(),
            project_id=project_id,
            org_id=org_id,
            name=name,
            key_hash=key_hash,
            key_prefix=key_prefix,
            created_by=created_by,
            role=role,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(api_key)
        await self.db.commit()
        await self.db.refresh(api_key)
        return api_key, raw_key

    async def get_by_hash(self, key_hash: str) -> Optional[JoySafeterApiKey]:
        result = await self.db.execute(select(JoySafeterApiKey).where(JoySafeterApiKey.key_hash == key_hash))
        return result.scalar_one_or_none()

    async def list_project_keys(self, project_id: str) -> List[JoySafeterApiKey]:
        result = await self.db.execute(
            select(JoySafeterApiKey)
            .where(and_(JoySafeterApiKey.project_id == project_id, JoySafeterApiKey.revoked_at.is_(None)))
            .order_by(JoySafeterApiKey.created_at.desc())
        )
        return list(result.scalars().all())

    async def revoke_key(self, key_id, project_id: str) -> bool:
        result = await self.db.execute(
            select(JoySafeterApiKey).where(
                and_(JoySafeterApiKey.id == key_id, JoySafeterApiKey.project_id == project_id)
            )
        )
        key = result.scalar_one_or_none()
        if not key:
            return False
        key.revoked_at = datetime.now(timezone.utc)
        await self.db.commit()
        return True

    async def touch_last_used(self, key_id) -> None:
        result = await self.db.execute(select(JoySafeterApiKey).where(JoySafeterApiKey.id == key_id))
        key = result.scalar_one_or_none()
        if key:
            key.last_used_at = datetime.now(timezone.utc)
            await self.db.commit()
