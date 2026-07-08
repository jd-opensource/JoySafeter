import hashlib
import uuid
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_memory import (
    JoySafeterMemory,
    JoySafeterMemoryStore,
    JoySafeterMemoryVersion,
    JoySafeterSessionMemoryStore,
)
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_shared.utils.datetime import utc_now


class PreconditionFailed(Exception):
    pass


class MemoryStoreLimitExceeded(Exception):
    pass


MAX_MEMORIES_PER_STORE = 2000


class MemoryService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # --- Memory Store ---

    async def create_store(
        self, name: str, description: str = "", metadata: Optional[dict] = None, project_id: Optional[str] = None
    ) -> JoySafeterMemoryStore:
        kwargs = dict(name=name, description=description, metadata_=metadata or {})
        if project_id is not None:
            kwargs["project_id"] = project_id
        store = JoySafeterMemoryStore(**kwargs)
        self.db.add(store)
        await self.db.commit()
        await self.db.refresh(store)
        return store

    async def get_store(
        self, store_id: uuid.UUID, project_id: Optional[str] = None, include_archived: bool = False
    ) -> Optional[JoySafeterMemoryStore]:
        conditions = [
            JoySafeterMemoryStore.id == store_id,
        ]
        if not include_archived:
            conditions.append(JoySafeterMemoryStore.archived_at.is_(None))
        if project_id is not None:
            conditions.append(JoySafeterMemoryStore.project_id == project_id)
        result = await self.db.execute(select(JoySafeterMemoryStore).where(and_(*conditions)))
        return result.scalar_one_or_none()

    async def list_stores(
        self,
        limit: int = 20,
        after_id: Optional[uuid.UUID] = None,
        project_id: Optional[str] = None,
        include_archived: bool = False,
    ) -> tuple[list[JoySafeterMemoryStore], bool]:
        q = select(JoySafeterMemoryStore)
        if not include_archived:
            q = q.where(JoySafeterMemoryStore.archived_at.is_(None))
        if project_id is not None:
            q = q.where(JoySafeterMemoryStore.project_id == project_id)
        if after_id:
            q = q.where(JoySafeterMemoryStore.id < after_id)
        q = q.order_by(JoySafeterMemoryStore.created_at.desc()).limit(limit + 1)
        result = await self.db.execute(q)
        stores = list(result.scalars().all())
        has_more = len(stores) > limit
        return stores[:limit], has_more

    async def update_store(
        self,
        store_id: uuid.UUID,
        name: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[dict] = None,
        project_id: Optional[str] = None,
    ) -> Optional[JoySafeterMemoryStore]:
        store = await self.get_store(store_id, project_id=project_id)
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

    async def store_is_referenced_by_sessions(
        self,
        store_id: uuid.UUID,
        project_id: Optional[str] = None,
    ) -> bool:
        conditions = [
            JoySafeterSessionMemoryStore.store_id == store_id,
            JoySafeterSessionMemoryStore.session_id == JoySafeterSession.id,
            JoySafeterSession.archived_at.is_(None),
        ]
        if project_id is not None:
            conditions.append(JoySafeterSession.project_id == project_id)
        result = await self.db.execute(select(JoySafeterSessionMemoryStore.id).where(and_(*conditions)).limit(1))
        return result.scalar_one_or_none() is not None

    async def delete_store(self, store_id: uuid.UUID, project_id: Optional[str] = None) -> bool:
        store = await self.get_store(store_id, project_id=project_id, include_archived=True)
        if not store:
            return False
        if await self.store_is_referenced_by_sessions(store_id, project_id=project_id):
            raise ValueError("Memory store is referenced by one or more active sessions.")
        await self.db.delete(store)
        await self.db.commit()
        return True

    async def archive_store(self, store_id: uuid.UUID, project_id: Optional[str] = None) -> bool:
        store = await self.get_store(store_id, project_id=project_id)
        if not store:
            return False
        if store.archived_at:
            return True
        if await self.store_is_referenced_by_sessions(store_id, project_id=project_id):
            raise ValueError("Memory store is referenced by one or more active sessions.")
        store.archived_at = utc_now()
        await self.db.commit()
        return True

    # --- Memory ---

    async def create_memory(
        self, store_id: uuid.UUID, path: str, content: str = "", session_id: Optional[uuid.UUID] = None
    ) -> JoySafeterMemory:
        await self.db.execute(
            select(JoySafeterMemoryStore.id).where(JoySafeterMemoryStore.id == store_id).with_for_update()
        )
        count_result = await self.db.execute(
            select(func.count()).select_from(JoySafeterMemory).where(JoySafeterMemory.store_id == store_id)
        )
        memory_count = count_result.scalar_one() or 0
        if memory_count >= MAX_MEMORIES_PER_STORE:
            raise MemoryStoreLimitExceeded(f"Memory store has reached the maximum of {MAX_MEMORIES_PER_STORE} memories")

        sha = hashlib.sha256(content.encode()).hexdigest()
        mem = JoySafeterMemory(
            store_id=store_id,
            path=path,
            content=content,
            content_sha256=sha,
            size_bytes=len(content.encode()),
        )
        self.db.add(mem)
        await self.db.flush()

        version = await self._create_version(
            store_id, mem.id, "created", path=path, content=content, sha=sha, size=len(content.encode())
        )
        mem.current_version_id = version.id
        await self.db.commit()
        await self.db.refresh(mem)

        await self._notify_memory_peers(store_id, session_id, "created", path)
        return mem

    async def get_memory(self, store_id: uuid.UUID, memory_id: uuid.UUID) -> Optional[JoySafeterMemory]:
        result = await self.db.execute(
            select(JoySafeterMemory).where(
                and_(JoySafeterMemory.id == memory_id, JoySafeterMemory.store_id == store_id)
            )
        )
        return result.scalar_one_or_none()

    async def get_memory_by_path(self, store_id: uuid.UUID, path: str) -> Optional[JoySafeterMemory]:
        result = await self.db.execute(
            select(JoySafeterMemory).where(and_(JoySafeterMemory.store_id == store_id, JoySafeterMemory.path == path))
        )
        return result.scalar_one_or_none()

    async def upsert_memory_from_agent(
        self,
        store_id: uuid.UUID,
        path: str,
        content: str,
        session_id: Optional[uuid.UUID] = None,
    ) -> JoySafeterMemory:
        existing = await self.get_memory_by_path(store_id, path)
        if existing:
            # Skip update if SHA256 matches (content unchanged)
            new_sha = hashlib.sha256(content.encode()).hexdigest()
            if existing.content_sha256 == new_sha:
                return existing
            updated = await self.update_memory(store_id, existing.id, content, session_id)
            if updated is not None:
                return updated
            # Row vanished between fetch and update (e.g. concurrent delete);
            # fall through and (re)create to honor upsert semantics.
        return await self.create_memory(store_id, path, content, session_id)

    async def list_memories(
        self,
        store_id: uuid.UUID,
        limit: int = 20,
        after_id: Optional[uuid.UUID] = None,
        path_prefix: Optional[str] = None,
        order_by: str = "path",
        order: str = "asc",
    ) -> tuple[list[JoySafeterMemory], bool]:
        q = select(JoySafeterMemory).where(JoySafeterMemory.store_id == store_id)
        if after_id:
            q = q.where(JoySafeterMemory.id < after_id)
        if path_prefix:
            q = q.where(JoySafeterMemory.path.like(path_prefix + "%"))

        # Apply ordering
        order_col = getattr(JoySafeterMemory, order_by, JoySafeterMemory.path)
        if order == "desc":
            q = q.order_by(order_col.desc())
        else:
            q = q.order_by(order_col.asc())

        q = q.limit(limit + 1)
        result = await self.db.execute(q)
        memories = list(result.scalars().all())
        has_more = len(memories) > limit
        return memories[:limit], has_more

    async def update_memory(
        self,
        store_id: uuid.UUID,
        memory_id: uuid.UUID,
        content: str,
        session_id: Optional[uuid.UUID] = None,
        if_sha256: Optional[str] = None,
    ) -> Optional[JoySafeterMemory]:
        mem = await self.get_memory(store_id, memory_id)
        if not mem:
            return None
        if if_sha256 is not None and mem.content_sha256 != if_sha256:
            raise PreconditionFailed(f"SHA256 mismatch: expected {if_sha256}, got {mem.content_sha256}")
        sha = hashlib.sha256(content.encode()).hexdigest()
        mem.content = content
        mem.content_sha256 = sha
        mem.size_bytes = len(content.encode())
        mem.version = (mem.version or 1) + 1
        mem.updated_at = utc_now()

        version = await self._create_version(
            store_id, mem.id, "modified", path=mem.path, content=content, sha=sha, size=len(content.encode())
        )
        mem.current_version_id = version.id
        await self.db.commit()
        await self.db.refresh(mem)

        await self._notify_memory_peers(store_id, session_id, "modified", mem.path)
        return mem

    async def delete_memory(
        self, store_id: uuid.UUID, memory_id: uuid.UUID, session_id: Optional[uuid.UUID] = None
    ) -> bool:
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
        from app.joysafeter_shared.orchestrator_bridge import get_memory_subscribers

        subs = get_memory_subscribers()
        if not subs:
            return

        if session_id:
            await subs.notify_peers(store_id, session_id, change_type, path)
        else:
            await subs.notify_all(store_id, change_type, path)

    # --- Versions ---

    async def is_live_version(self, store_id: uuid.UUID, version_id: uuid.UUID) -> bool:
        """Check if any memory in this store has current_version_id == version_id."""
        result = await self.db.execute(
            select(JoySafeterMemory).where(
                and_(
                    JoySafeterMemory.store_id == store_id,
                    JoySafeterMemory.current_version_id == version_id,
                )
            )
        )
        return result.scalar_one_or_none() is not None

    async def list_versions(
        self,
        store_id: uuid.UUID,
        limit: int = 20,
        after_id: Optional[uuid.UUID] = None,
        memory_id: Optional[uuid.UUID] = None,
        session_id: Optional[uuid.UUID] = None,
        operation: Optional[str] = None,
    ) -> tuple[list[JoySafeterMemoryVersion], bool]:
        q = select(JoySafeterMemoryVersion).where(JoySafeterMemoryVersion.store_id == store_id)
        if after_id:
            q = q.where(JoySafeterMemoryVersion.id < after_id)
        if memory_id is not None:
            q = q.where(JoySafeterMemoryVersion.memory_id == memory_id)
        if session_id is not None:
            q = q.where(JoySafeterMemoryVersion.session_id == session_id)
        if operation is not None:
            q = q.where(JoySafeterMemoryVersion.operation == operation)
        q = q.order_by(JoySafeterMemoryVersion.created_at.desc()).limit(limit + 1)
        result = await self.db.execute(q)
        versions = list(result.scalars().all())
        has_more = len(versions) > limit
        return versions[:limit], has_more

    async def get_version(self, store_id: uuid.UUID, version_id: uuid.UUID) -> Optional[JoySafeterMemoryVersion]:
        result = await self.db.execute(
            select(JoySafeterMemoryVersion).where(
                and_(JoySafeterMemoryVersion.id == version_id, JoySafeterMemoryVersion.store_id == store_id)
            )
        )
        return result.scalar_one_or_none()

    async def redact_version(
        self, store_id: uuid.UUID, version_id: uuid.UUID, redacted_by: Optional[dict] = None
    ) -> bool:
        ver = await self.get_version(store_id, version_id)
        if not ver:
            return False
        ver.content = None
        ver.content_sha256 = None
        ver.content_size_bytes = None
        ver.path = None
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
    ) -> JoySafeterMemoryVersion:
        ver = JoySafeterMemoryVersion(
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
