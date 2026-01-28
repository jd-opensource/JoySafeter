"""
Long-term memory storage.

Stores facts, procedures, and episodic memories for agent sessions.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4


class MemoryType(str, Enum):
    """Memory type classification."""

    FACT = "fact"  # Factual knowledge (target info, vulnerabilities)
    PROCEDURE = "procedure"  # Procedural knowledge (successful attack paths)
    EPISODIC = "episodic"  # Episodic memory (session-specific experiences)
    SEMANTIC = "semantic"  # Semantic memory (general security knowledge)


@dataclass
class Memory:
    """Memory unit."""

    memory_id: str
    session_id: str
    memory_type: MemoryType

    # Memory content
    key: str  # namespace/key
    value: Any

    # Metadata
    created_at: datetime
    accessed_count: int = 0
    last_accessed: Optional[datetime] = None

    # Importance score (0-1)
    importance: float = 0.5

    # Tags and categorization
    tags: List[str] = field(default_factory=list)
    category: Optional[str] = None

    # Related information
    related_memories: List[str] = field(default_factory=list)
    source: Optional[str] = None  # Source (tool_result, user_input, inference)


class MemoryStore:
    """Long-term memory storage system."""

    def __init__(self, persistence_backend):
        self.backend = persistence_backend
        self._cache: Dict[str, Memory] = {}

    async def store(
        self,
        session_id: str,
        key: str,
        value: Any,
        memory_type: MemoryType = MemoryType.FACT,
        importance: float = 0.5,
        tags: Optional[List[str]] = None,
        category: Optional[str] = None,
        source: Optional[str] = None,
    ) -> Memory:
        """Store a memory."""
        memory = Memory(
            memory_id=str(uuid4()),
            session_id=session_id,
            memory_type=memory_type,
            key=key,
            value=value,
            created_at=datetime.now(),
            importance=importance,
            tags=tags or [],
            category=category,
            source=source,
        )

        cache_key = f"{session_id}:{key}"
        self._cache[cache_key] = memory
        await self.backend.save_memory(memory)

        return memory

    async def retrieve(self, session_id: str, key: str) -> Optional[Memory]:
        """Retrieve a memory."""
        cache_key = f"{session_id}:{key}"

        # Check cache first
        if cache_key in self._cache:
            memory = self._cache[cache_key]
        else:
            # Load from persistence
            memory = await self.backend.load_memory(session_id, key)
            if memory:
                self._cache[cache_key] = memory

        if memory:
            # Update access statistics
            memory.accessed_count += 1
            memory.last_accessed = datetime.now()
            await self.backend.update_memory_stats(memory)

        return memory

    async def search(
        self,
        session_id: str,
        query: Optional[str] = None,
        memory_type: Optional[MemoryType] = None,
        tags: Optional[List[str]] = None,
        category: Optional[str] = None,
        min_importance: float = 0.0,
        limit: int = 10,
    ) -> List[Memory]:
        """Search memories."""
        result = await self.backend.search_memories(
            session_id=session_id,
            query=query,
            memory_type=memory_type,
            tags=tags,
            category=category,
            min_importance=min_importance,
            limit=limit,
        )
        return result if isinstance(result, list) else []  # type: ignore[return-value]

    async def store_target_info(self, session_id: str, target: str, info: Dict[str, Any]):
        """Store target information."""
        await self.store(
            session_id=session_id,
            key=f"target:{target}",
            value=info,
            memory_type=MemoryType.FACT,
            importance=0.9,
            tags=["target", "reconnaissance"],
            category="target_info",
            source="tool_result",
        )

    async def store_vulnerability(self, session_id: str, target: str, vulnerability: Dict[str, Any]):
        """Store vulnerability discovery."""
        await self.store(
            session_id=session_id,
            key=f"vuln:{target}:{vulnerability.get('type', 'unknown')}",
            value=vulnerability,
            memory_type=MemoryType.FACT,
            importance=1.0,
            tags=["vulnerability", vulnerability.get("severity", "unknown")],
            category="vulnerability",
            source="tool_result",
        )

    async def store_successful_attack_path(self, session_id: str, target: str, attack_chain: List[Dict[str, Any]]):
        """Store successful attack path."""
        await self.store(
            session_id=session_id,
            key=f"attack_path:{target}",
            value=attack_chain,
            memory_type=MemoryType.PROCEDURE,
            importance=0.95,
            tags=["attack_path", "success"],
            category="methodology",
            source="execution_result",
        )

    async def get_target_history(self, session_id: str, target: str) -> Dict[str, Any]:
        """Get complete target history."""
        # Get target info
        target_info = await self.retrieve(session_id, f"target:{target}")

        # Get vulnerabilities
        vulnerabilities = await self.search(session_id=session_id, category="vulnerability", tags=["vulnerability"])

        # Get attack paths
        attack_paths = await self.search(session_id=session_id, category="methodology")

        return {
            "target": target,
            "info": target_info.value if target_info else {},
            "vulnerabilities": [v.value for v in vulnerabilities],
            "attack_paths": [a.value for a in attack_paths],
        }

    async def delete_memory(self, memory_id: str):
        """Delete a memory."""
        await self.backend.delete_memory(memory_id)

        # Remove from cache
        for key, memory in list(self._cache.items()):
            if memory.memory_id == memory_id:
                del self._cache[key]
                break
