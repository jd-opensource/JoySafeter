import asyncio
import logging
import uuid
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class MemorySessionEntry:
    session_id: uuid.UUID
    sandbox_db_id: uuid.UUID
    mount_name: str
    mount_path: str = ""  # Rust parity: filesystem mount path


class MemoryStoreSubscribers:
    """Tracks which sessions subscribe to each memory store.

    Enables cross-session sync: when one session writes to a shared store,
    other sessions sharing that store can be notified to reload.

    Ported from joysafeter-kernel/src/memory_sync.rs.
    """

    def __init__(self):
        self._inner: dict[uuid.UUID, list[MemorySessionEntry]] = {}
        self._lock = asyncio.Lock()

    async def register(self, store_id: uuid.UUID, entry: MemorySessionEntry) -> None:
        async with self._lock:
            if store_id not in self._inner:
                self._inner[store_id] = []
            # Deduplicate by (session_id, sandbox_db_id) — matches Rust
            for existing in self._inner[store_id]:
                if existing.session_id == entry.session_id and existing.sandbox_db_id == entry.sandbox_db_id:
                    return
            self._inner[store_id].append(entry)

    async def unregister(self, session_id: uuid.UUID, sandbox_db_id: uuid.UUID) -> None:
        """Remove by both session AND sandbox — matches Rust."""
        async with self._lock:
            for entries in self._inner.values():
                entries[:] = [
                    e for e in entries
                    if not (e.session_id == session_id and e.sandbox_db_id == sandbox_db_id)
                ]
            self._inner = {k: v for k, v in self._inner.items() if v}

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
        """Notify peer sessions that a memory file changed."""
        peers = await self.get_peers(store_id, source_session_id)
        return await self._push_memory_update(store_id, peers, change_type, path)

    async def notify_peers_direct(
        self,
        store_mount_name: str,
        relative_path: str,
        content: bytes,
        operation: str,
        sender_sandbox_id: uuid.UUID,
    ) -> int:
        """Notify peer sandboxes — matches Rust (excludes by sandbox_id, caller provides content)."""
        from app.joysafeter_orchestrator.grpc.proto import joysafeter_pb2
        from app.joysafeter_orchestrator.lifespan import get_bridge_registry

        registry = get_bridge_registry()
        if not registry:
            return 0

        notified = 0
        async with self._lock:
            for _store_id, entries in self._inner.items():
                for entry in entries:
                    if entry.sandbox_db_id == sender_sandbox_id:
                        continue
                    if entry.mount_name != store_mount_name:
                        continue
                    bridge = await registry.get(entry.sandbox_db_id)
                    if not bridge:
                        continue
                    try:
                        msg = joysafeter_pb2.OrchestratorMessage(
                            memory_update=joysafeter_pb2.MemoryFileUpdate(
                                store_mount_name=store_mount_name,
                                relative_path=relative_path,
                                content=content,
                                operation=operation,
                            )
                        )
                        await bridge.send_to_runner(msg)
                        notified += 1
                    except Exception as e:
                        logger.warning(
                            "Failed to push MemoryFileUpdate to sandbox %s: %s",
                            entry.sandbox_db_id, e,
                        )

        if notified:
            logger.info(
                "Pushed memory %s to %d peers (mount=%s, path=%s)",
                operation, notified, store_mount_name, relative_path,
            )
        return notified

    async def notify_all(
        self,
        store_id: uuid.UUID,
        change_type: str,
        path: str,
    ) -> int:
        """Notify ALL sessions subscribed to a store (used when API writes with no source session)."""
        async with self._lock:
            entries = list(self._inner.get(store_id, []))
        return await self._push_memory_update(store_id, entries, change_type, path)

    async def _push_memory_update(
        self,
        store_id: uuid.UUID,
        entries: list[MemorySessionEntry],
        change_type: str,
        path: str,
    ) -> int:
        if not entries:
            return 0

        from app.joysafeter_orchestrator.lifespan import get_bridge_registry

        registry = get_bridge_registry()
        if not registry:
            return 0

        content = b""
        operation = "write"
        if change_type == "delete":
            operation = "delete"
        else:
            from app.joysafeter_orchestrator.services import MemoryService
            from app.joysafeter_shared.database import AsyncSessionLocal
            async with AsyncSessionLocal() as db:
                mem_svc = MemoryService(db)
                mem = await mem_svc.get_memory_by_path(store_id, path)
                if mem and mem.content:
                    content = mem.content.encode("utf-8") if isinstance(mem.content, str) else mem.content

        from app.joysafeter_orchestrator.grpc.proto import joysafeter_pb2

        notified = 0
        for peer in entries:
            bridge = await registry.get(peer.sandbox_db_id)
            if bridge and bridge.runner_stream:
                try:
                    update_msg = joysafeter_pb2.OrchestratorMessage(
                        memory_update=joysafeter_pb2.MemoryFileUpdate(
                            store_mount_name=peer.mount_name,
                            relative_path=path,
                            content=content,
                            operation=operation,
                        )
                    )
                    await bridge.runner_stream.write(update_msg)
                    notified += 1
                except Exception as e:
                    logger.warning("Failed to push MemoryFileUpdate to peer %s: %s", peer.session_id, e)

        if notified:
            logger.info(
                "Pushed memory %s to %d peers for store %s (path=%s)",
                operation, notified, store_id, path,
            )
        return notified
