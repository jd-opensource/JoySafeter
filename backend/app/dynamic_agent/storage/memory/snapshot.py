"""
Session snapshot and recovery.

Provides checkpoint and rollback capabilities for agent sessions.
"""

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4


@dataclass
class SessionSnapshot:
    """Session snapshot for recovery."""

    snapshot_id: str
    session_id: str
    created_at: datetime

    # Snapshot content
    context: Dict[str, Any]
    active_tasks: Dict[str, Any]
    container_state: Dict[str, Any]
    memory_state: Dict[str, Any]

    # Snapshot metadata
    description: Optional[str] = None
    checkpoint_type: str = "manual"  # manual, auto, pre_action


class SnapshotManager:
    """Snapshot manager for session recovery."""

    def __init__(self, context_manager, task_manager, container_manager, memory_store, persistence_backend):
        self.context_manager = context_manager
        self.task_manager = task_manager
        self.container_manager = container_manager
        self.memory_store = memory_store
        self.backend = persistence_backend

    async def create_snapshot(
        self, session_id: str, description: Optional[str] = None, checkpoint_type: str = "manual"
    ) -> SessionSnapshot:
        """Create session snapshot."""
        # Collect current state
        context = await self.context_manager.get_session(session_id)
        tasks = await self.task_manager.get_session_tasks(session_id)

        # Container state
        container_state = {}
        if context and context:
            container_ctx = await self.container_manager.get_container_context(context.container_id)
            if container_ctx:
                container_state = asdict(container_ctx)

        # Memory state (only high-importance memories)
        memories = await self.memory_store.search(session_id=session_id, min_importance=0.7, limit=50)
        memory_state = {"memories": [asdict(m) for m in memories]}

        snapshot = SessionSnapshot(
            snapshot_id=str(uuid4()),
            session_id=session_id,
            created_at=datetime.now(),
            context=asdict(context) if context else {},
            active_tasks={t.task_id: asdict(t) for t in tasks},
            container_state=container_state,
            memory_state=memory_state,
            description=description,
            checkpoint_type=checkpoint_type,
        )

        await self.backend.save_snapshot(snapshot)
        return snapshot

    async def restore_snapshot(self, snapshot_id: str) -> bool:
        """Restore session to snapshot state."""
        snapshot = await self.backend.load_snapshot(snapshot_id)
        if not snapshot:
            return False

        # Restore context
        from app.dynamic_agent.storage.context_manager import SessionContext

        context = SessionContext(**snapshot.context)
        await self.context_manager.update_session(context)

        # Restore task states
        for task_data in snapshot.active_tasks.values():
            from app.dynamic_agent.storage.session.task import TaskState, TaskStatus

            # Convert status string to enum
            task_data["status"] = TaskStatus(task_data["status"])
            # Convert datetime strings
            for field in ["created_at", "started_at", "completed_at"]:
                if task_data.get(field):
                    task_data[field] = datetime.fromisoformat(task_data[field])
            task = TaskState(**task_data)
            await self.task_manager.backend.save_task(task)

        # Restore memories
        for mem_data in snapshot.memory_state.get("memories", []):
            from app.dynamic_agent.storage.memory.store import Memory, MemoryType

            # Convert memory_type string to enum
            mem_data["memory_type"] = MemoryType(mem_data["memory_type"])
            # Convert datetime strings
            mem_data["created_at"] = datetime.fromisoformat(mem_data["created_at"])
            if mem_data.get("last_accessed"):
                mem_data["last_accessed"] = datetime.fromisoformat(mem_data["last_accessed"])
            memory = Memory(**mem_data)
            await self.memory_store.backend.save_memory(memory)

        return True

    async def list_snapshots(self, session_id: str, limit: int = 10) -> List[SessionSnapshot]:
        """List session snapshots."""
        result = await self.backend.list_snapshots(session_id, limit)
        return result if isinstance(result, list) else []  # type: ignore[return-value]

    async def auto_checkpoint(self, session_id: str, action: str):
        """Create automatic checkpoint before critical action."""
        await self.create_snapshot(
            session_id=session_id, description=f"Auto checkpoint before: {action}", checkpoint_type="pre_action"
        )

    async def delete_snapshot(self, snapshot_id: str):
        """Delete a snapshot."""
        # Note: Implement in backend if needed
        pass
