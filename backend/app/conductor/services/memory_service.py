import hashlib
import uuid
from typing import Optional

from sqlalchemy import and_, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.conductor.models.memory import (
    ConductorMemory,
    ConductorMemoryStore,
    ConductorMemoryVersion,
    ConductorSessionMemoryStore,
)
from app.utils.datetime import utc_now


class PreconditionFailed(Exception):
    pass


class MemoryService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # --- Memory Store ---

    async def create_store(self, name: str, description: str = "", metadata: Optional[dict] = None) -> ConductorMemoryStore:
        store = ConductorMemoryStore(name=name, description=description, metadata_=metadata or {})
        self.db.add(store)
        await self.db.commit()
        await self.db.refresh(store)
        return store

    async def get_store(self, store_id: uuid.UUID) -> Optional[ConductorMemoryStore]:
        result = await self.db.execute(
            select(ConductorMemoryStore).where(
                and_(ConductorMemoryStore.id == store_id, ConductorMemoryStore.archived_at.is_(None))
            )
        )
        return result.scalar_one_or_none()

    async def list_stores(self, limit: int = 20, after_id: Optional[uuid.UUID] = None) -> tuple[list[ConductorMemoryStore], bool]:
        q = select(ConductorMemoryStore).where(ConductorMemoryStore.archived_at.is_(None))
        if after_id:
            q = q.where(ConductorMemoryStore.id < after_id)
        q = q.order_by(ConductorMemoryStore.created_at.desc()).limit(limit + 1)
        result = await self.db.execute(q)
        stores = list(result.scalars().all())
        has_more = len(stores) > limit
        return stores[:limit], has_more

    async def update_store(self, store_id: uuid.UUID, name: Optional[str] = None, description: Optional[str] = None, metadata: Optional[dict] = None) -> Optional[ConductorMemoryStore]:
        store = await self.get_store(store_id)
        if not store:
            return None
        if name is not None:
            store.name = name
        if description is not None:
            store.description = description
        if metadata is not None:
            store.metadata_ = metadata
        store.updated_at = utc_now()
        await self.db.commit()
        await self.db.refresh(store)
        return store

    async def delete_store(self, store_id: uuid.UUID) -> bool:
        store = await self.get_store(store_id)
        if not store:
            return False
        await self.db.delete(store)
        await self.db.commit()
        return True

    async def archive_store(self, store_id: uuid.UUID) -> bool:
        store = await self.get_store(store_id)
        if not store:
            return False
        if store.archived_at:
            return True
        store.archived_at = utc_now()
        await self.db.commit()
        return True

    # --- Memory ---

    async def create_memory(self, store_id: uuid.UUID, path: str, content: str = "", session_id: uuid.UUID = None) -> ConductorMemory:
        sha = hashlib.sha256(content.encode()).hexdigest()
        mem = ConductorMemory(
            store_id=store_id,
            path=path,
            content=content,
            content_sha256=sha,
            size_bytes=len(content.encode()),
        )
        self.db.add(mem)
        await self.db.flush()

        version = await self._create_version(store_id, mem.id, "created", path=path, content=content, sha=sha, size=len(content.encode()))
        mem.current_version_id = version.id
        await self.db.commit()
        await self.db.refresh(mem)

        await self._notify_memory_peers(store_id, session_id, "created", path)
        return mem

    async def get_memory(self, store_id: uuid.UUID, memory_id: uuid.UUID) -> Optional[ConductorMemory]:
        result = await self.db.execute(
            select(ConductorMemory).where(
                and_(ConductorMemory.id == memory_id, ConductorMemory.store_id == store_id)
            )
        )
        return result.scalar_one_or_none()

    async def get_memory_by_path(self, store_id: uuid.UUID, path: str) -> Optional[ConductorMemory]:
        result = await self.db.execute(
            select(ConductorMemory).where(
                and_(ConductorMemory.store_id == store_id, ConductorMemory.path == path)
            )
        )
        return result.scalar_one_or_none()

    async def upsert_memory_from_agent(
        self,
        store_id: uuid.UUID,
        path: str,
        content: str,
        session_id: Optional[uuid.UUID] = None,
    ) -> ConductorMemory:
        existing = await self.get_memory_by_path(store_id, path)
        if existing:
            return await self.update_memory(store_id, existing.id, content, session_id)
        return await self.create_memory(store_id, path, content, session_id)

    async def list_memories(self, store_id: uuid.UUID, limit: int = 20, after_id: Optional[uuid.UUID] = None) -> tuple[list[ConductorMemory], bool]:
        q = select(ConductorMemory).where(ConductorMemory.store_id == store_id)
        if after_id:
            q = q.where(ConductorMemory.id < after_id)
        q = q.order_by(ConductorMemory.created_at.desc()).limit(limit + 1)
        result = await self.db.execute(q)
        memories = list(result.scalars().all())
        has_more = len(memories) > limit
        return memories[:limit], has_more

    async def update_memory(
        self, store_id: uuid.UUID, memory_id: uuid.UUID, content: str,
        session_id: uuid.UUID = None, if_sha256: Optional[str] = None,
    ) -> Optional[ConductorMemory]:
        mem = await self.get_memory(store_id, memory_id)
        if not mem:
            return None
        if if_sha256 is not None and mem.content_sha256 != if_sha256:
            raise PreconditionFailed(
                f"SHA256 mismatch: expected {if_sha256}, got {mem.content_sha256}"
            )
        sha = hashlib.sha256(content.encode()).hexdigest()
        mem.content = content
        mem.content_sha256 = sha
        mem.size_bytes = len(content.encode())
        mem.updated_at = utc_now()

        version = await self._create_version(store_id, mem.id, "modified", path=mem.path, content=content, sha=sha, size=len(content.encode()))
        mem.current_version_id = version.id
        await self.db.commit()
        await self.db.refresh(mem)

        await self._notify_memory_peers(store_id, session_id, "modified", mem.path)
        return mem

    async def delete_memory(self, store_id: uuid.UUID, memory_id: uuid.UUID, session_id: uuid.UUID = None) -> bool:
        mem = await self.get_memory(store_id, memory_id)
        if not mem:
            return False
        path = mem.path
        await self._create_version(store_id, mem.id, "deleted", path=path)
        await self.db.delete(mem)
        await self.db.commit()

        await self._notify_memory_peers(store_id, session_id, "deleted", path)
        return True

    async def _notify_memory_peers(
        self, store_id: uuid.UUID, session_id: Optional[uuid.UUID], change_type: str, path: str
    ) -> None:
        if not session_id:
            return
        from app.conductor.lifespan import get_memory_subscribers

        subs = get_memory_subscribers()
        if subs:
            await subs.notify_peers(store_id, session_id, change_type, path)

    # --- Versions ---

    async def list_versions(self, store_id: uuid.UUID, limit: int = 20, after_id: Optional[uuid.UUID] = None) -> tuple[list[ConductorMemoryVersion], bool]:
        q = select(ConductorMemoryVersion).where(ConductorMemoryVersion.store_id == store_id)
        if after_id:
            q = q.where(ConductorMemoryVersion.id < after_id)
        q = q.order_by(ConductorMemoryVersion.created_at.desc()).limit(limit + 1)
        result = await self.db.execute(q)
        versions = list(result.scalars().all())
        has_more = len(versions) > limit
        return versions[:limit], has_more

    async def get_version(self, store_id: uuid.UUID, version_id: uuid.UUID) -> Optional[ConductorMemoryVersion]:
        result = await self.db.execute(
            select(ConductorMemoryVersion).where(
                and_(ConductorMemoryVersion.id == version_id, ConductorMemoryVersion.store_id == store_id)
            )
        )
        return result.scalar_one_or_none()

    async def redact_version(self, store_id: uuid.UUID, version_id: uuid.UUID, redacted_by: Optional[dict] = None) -> bool:
        ver = await self.get_version(store_id, version_id)
        if not ver:
            return False
        ver.content = None
        ver.redacted_at = utc_now()
        ver.redacted_by = redacted_by
        await self.db.commit()
        return True

    async def _create_version(
        self,
        store_id: uuid.UUID,
        memory_id: uuid.UUID,
        operation: str,
        path: Optional[str] = None,
        content: Optional[str] = None,
        sha: Optional[str] = None,
        size: Optional[int] = None,
    ) -> ConductorMemoryVersion:
        ver = ConductorMemoryVersion(
            store_id=store_id,
            memory_id=memory_id,
            operation=operation,
            path=path,
            content=content,
            content_sha256=sha,
            content_size_bytes=size,
        )
        self.db.add(ver)
        await self.db.flush()
        return ver
