import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class MemorySessionEntry:
    session_id: uuid.UUID
    sandbox_db_id: uuid.UUID
    mount_name: str


class MemoryStoreSubscribers:
    """Tracks which sessions subscribe to each memory store.

    Enables cross-session sync: when one session writes to a shared store,
    other sessions sharing that store can be notified to reload.

    Ported from conductor-kernel/src/memory_sync.rs.
    """

    def __init__(self):
        self._inner: dict[uuid.UUID, list[MemorySessionEntry]] = {}
        self._lock = asyncio.Lock()

    async def register(self, store_id: uuid.UUID, entry: MemorySessionEntry) -> None:
        async with self._lock:
            if store_id not in self._inner:
                self._inner[store_id] = []
            self._inner[store_id].append(entry)

    async def unregister_session(self, session_id: uuid.UUID) -> None:
        async with self._lock:
            for entries in self._inner.values():
                entries[:] = [e for e in entries if e.session_id != session_id]
            self._inner = {k: v for k, v in self._inner.items() if v}

    async def get_peers(
        self, store_id: uuid.UUID, exclude_session: uuid.UUID
    ) -> list[MemorySessionEntry]:
        async with self._lock:
            entries = self._inner.get(store_id, [])
            return [e for e in entries if e.session_id != exclude_session]

    async def get_stores_for_session(self, session_id: uuid.UUID) -> list[uuid.UUID]:
        async with self._lock:
            return [
                store_id
                for store_id, entries in self._inner.items()
                if any(e.session_id == session_id for e in entries)
            ]

    async def notify_peers(
        self,
        store_id: uuid.UUID,
        source_session_id: uuid.UUID,
        change_type: str,
        path: str,
    ) -> int:
        """Notify peer sessions that a memory file changed.

        Returns the number of peers notified. The actual notification is sent
        via the SandboxBridge control input channel.
        """
        peers = await self.get_peers(store_id, source_session_id)
        if not peers:
            return 0

        from app.conductor.lifespan import get_bridge_registry
        import json

        registry = get_bridge_registry()
        if not registry:
            return 0

        notified = 0
        for peer in peers:
            bridge = await registry.get(peer.sandbox_db_id)
            if bridge:
                payload = json.dumps({
                    "type": "memory_sync",
                    "store_id": str(store_id),
                    "mount_name": peer.mount_name,
                    "change_type": change_type,
                    "path": path,
                })
                await bridge.send_control_input(f"__conductor_input_v1__:{payload}")
                notified += 1

        if notified:
            logger.debug(
                "Notified %d peers about %s change in store %s (path=%s)",
                notified, change_type, store_id, path,
            )
        return notified
