import hashlib
import uuid
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_api_key import JoySafeterApiKey
from app.joysafeter_domain.pagination import apply_created_at_desc_cursor


class ApiKeyRevokeResult(StrEnum):
    REVOKED = "revoked"
    ALREADY_REVOKED = "already_revoked"
    NOT_FOUND = "not_found"


class ApiKeyStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


def api_key_status(api_key: JoySafeterApiKey, *, now: datetime | None = None) -> ApiKeyStatus:
    if api_key.revoked_at is not None:
        return ApiKeyStatus.REVOKED
    current_time = now or datetime.now(timezone.utc)
    if api_key.expires_at is not None and api_key.expires_at <= current_time:
        return ApiKeyStatus.EXPIRED
    return ApiKeyStatus.ACTIVE


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
        expires_at: datetime | None = None,
    ) -> tuple[JoySafeterApiKey, str]:
        created_at = datetime.now(timezone.utc)
        if expires_at is not None:
            if expires_at.utcoffset() is None:
                raise ValueError("expires_at must include a timezone")
            if expires_at <= created_at:
                raise ValueError("expires_at must be in the future")
        raw_key = f"cnkey_{uuid.uuid4().hex}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        api_key = JoySafeterApiKey(
            project_id=project_id,
            org_id=org_id,
            name=name,
            key_hash=key_hash,
            key_prefix=raw_key[:16],
            created_by=created_by,
            role=role,
            created_at=created_at,
            expires_at=expires_at,
        )
        self.db.add(api_key)
        await self.db.flush()
        await self.db.refresh(api_key)
        return api_key, raw_key

    async def list_project_keys_page(
        self,
        project_id: str,
        *,
        limit: int,
        after_id: uuid.UUID | None = None,
    ) -> tuple[list[JoySafeterApiKey], bool]:
        query = select(JoySafeterApiKey).where(JoySafeterApiKey.project_id == project_id)
        query = apply_created_at_desc_cursor(query, JoySafeterApiKey, after_id).limit(limit + 1)
        result = await self.db.execute(query)
        rows = list(result.scalars().all())
        return rows[:limit], len(rows) > limit

    async def revoke_key(self, key_id: uuid.UUID, project_id: str) -> ApiKeyRevokeResult:
        revoked_id = await self.db.scalar(
            update(JoySafeterApiKey)
            .where(
                JoySafeterApiKey.id == key_id,
                JoySafeterApiKey.project_id == project_id,
                JoySafeterApiKey.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(timezone.utc))
            .returning(JoySafeterApiKey.id)
        )
        if revoked_id is not None:
            return ApiKeyRevokeResult.REVOKED
        exists = await self.db.scalar(
            select(JoySafeterApiKey.id).where(
                and_(JoySafeterApiKey.id == key_id, JoySafeterApiKey.project_id == project_id)
            )
        )
        if exists is None:
            return ApiKeyRevokeResult.NOT_FOUND
        return ApiKeyRevokeResult.ALREADY_REVOKED
