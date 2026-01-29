import os
from typing import Any, Dict, Optional

from app.dynamic_agent.infra.docker import UnifiedDockerManager
from app.dynamic_agent.storage import PostgreSQLBackend
from app.dynamic_agent.storage.container.binding import ContainerBindingInfo, ContainerBindingManager
from app.dynamic_agent.storage.container.context import ContainerContextManager
from app.dynamic_agent.storage.context_manager import ContextManager, SessionContext
from app.dynamic_agent.storage.memory.compression import ContextCompressor, ContextPruner
from app.dynamic_agent.storage.memory.snapshot import SnapshotManager
from app.dynamic_agent.storage.memory.store import MemoryStore
from app.dynamic_agent.storage.session.task import TaskStateManager, TaskStatus


class StorageManager:
    """Unified storage manager - Facade pattern for all storage operations."""

    def __init__(self, backend: PostgreSQLBackend, docker_manager: Optional[UnifiedDockerManager], llm_provider=None):
        # Initialize backend
        self.backend = backend
        self.docker_manager = docker_manager

        # Initialize managers
        self.context = ContextManager(self.backend)
        self.tasks = TaskStateManager(self.backend)
        self.memory = MemoryStore(self.backend)

        # Container binding manager (always available)
        self.container_bindings = ContainerBindingManager(self.backend)

        # HTTP proxy for cross-host container service calls
        # self.http_proxy = ContainerHttpProxy(self.backend)
        # self.service_registry = ContainerServiceRegistry(self.backend)

        self.containers: Optional[ContainerContextManager] = (
            ContainerContextManager(docker_manager, self.backend) if docker_manager else None
        )

        self.snapshots = SnapshotManager(self.context, self.tasks, self.containers, self.memory, self.backend)

        self.compressor = ContextCompressor(llm_provider)
        self.pruner = ContextPruner(self.memory)

    async def initialize_session(
        self,
        user_id: str,
        session_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        auto_create_container: bool = True,
    ) -> SessionContext:
        """
        Initialize new session with automatic checkpoint and optional container.

        Args:
            user_id: User ID
            session_id: Session ID
            metadata: Session metadata
            auto_create_container: Automatically get or create container for user

        Returns:
            SessionContext instance
        """
        # Create session context
        context = await self.context.create_session(user_id, session_id, metadata)

        if auto_create_container:
            container_info = await self.get_container_info(session_id, user_id)
            if container_info:
                context.container_info = container_info
                await self.context.update_session(context)

        return context

    async def get_container_info(self, session_id: str, user_id: str) -> Optional[ContainerBindingInfo]:
        # Get or create container for user (if docker_manager available)
        if not self.docker_manager:
            return None

        docker_image = os.environ.get("DOCKER_IMAGE")
        docker_command = os.environ.get("DOCKER_START_MCP_COMMAND")

        if not docker_image or not docker_command:
            return None

        container_info: ContainerBindingInfo = await self.container_bindings.get_or_create_container(
            user_id=user_id,
            session_id=session_id,
            docker_manager=self.docker_manager,
            image=docker_image,
            command=docker_command,
        )

        return container_info

    async def get_session_state(self, session_id: str) -> Dict[str, Any]:
        """Get complete session state."""
        context = await self.context.get_session(session_id)
        if not context:
            return {}

        tasks = await self.tasks.get_session_tasks(session_id)
        memories = await self.memory.search(session_id, limit=20)

        state: Dict[str, Any] = {
            "context": context,
            "active_tasks": [t for t in tasks if t.status == TaskStatus.RUNNING],
            "completed_tasks": [t for t in tasks if t.status == TaskStatus.COMPLETED],
            "recent_memories": memories,
            "scenario": context.scenario,
        }

        if context.container_info:
            state["container_id"] = context.container_info.container_id

        return state

    async def cleanup_session(self, session_id: str, archive: bool = True):
        """Clean up session with optional archiving."""
        if archive:
            # Create final snapshot
            await self.snapshots.create_snapshot(session_id, description="Session archived", checkpoint_type="manual")

        # Prune low-value data
        await self.pruner.prune_session(session_id)

        # Clear from memory
        await self.context.clear_session(session_id)
