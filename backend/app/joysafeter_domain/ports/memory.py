"""Memory port — type-safe interface for memory persistence in core/."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class MemoryPort(Protocol):
    """Port for memory CRUD operations.

    Implemented by: services/memory_service.py (MemoryService)
    Used by: core/agent/memory/manager.py (MemoryManager)
    """

    async def get_user_memories(
        self,
        *,
        user_id: str,
        agent_id: str | None = None,
        team_id: str | None = None,
        topics: list[str] | None = None,
        search_content: str | None = None,
        limit: int | None = None,
        page: int | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
        deserialize: bool | None = True,
    ) -> Any: ...
    async def upsert_user_memory(self, memory: Any) -> Any: ...
    async def delete_user_memories(self, memory_ids: list[str], user_id: str) -> None: ...
    async def delete_user_memory(self, memory_id: str, user_id: str) -> Any: ...
    async def clear_memories(self) -> Any: ...
