"""Memory port — type-safe interface for memory persistence in core/."""

from __future__ import annotations

from typing import Any, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class MemoryPort(Protocol):
    """Port for memory CRUD operations.

    Implemented by: services/memory_service.py (MemoryService)
    Used by: core/agent/memory/manager.py (MemoryManager)
    """

    async def get_user_memories(self, user_id: Optional[str] = None) -> List[Any]: ...
    async def upsert_user_memory(self, memory: Any) -> Any: ...
    async def delete_user_memories(self, memory_ids: List[str], user_id: Optional[str] = None) -> None: ...
    async def delete_user_memory(self, memory_id: str, user_id: Optional[str] = None) -> Any: ...
    async def clear_memories(self) -> Any: ...
