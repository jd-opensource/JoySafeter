"""
Agent Storage Module - Unified context and state management.

Provides:
- Session context management
- Task state tracking
- Container runtime context
- Long-term memory storage
- Snapshot and recovery
- Context compression
- CTF session management

Backend:
- PostgreSQL: Production-ready with async connection pooling, JSONB indexing, and full-text search
"""

import asyncio
from typing import Optional

from langchain_core.language_models import BaseChatModel

from app.dynamic_agent.infra.docker import UnifiedDockerManager
from app.dynamic_agent.storage.config import StorageConfig
from app.dynamic_agent.storage.persistence import PostgreSQLBackend
from app.dynamic_agent.storage.storage_manage import StorageManager

#
# from .container_binding import ContainerBindingManager
# from .context_manager import ContextManager
# from .storage_manage import StorageManager
# from .task_state import TaskStateManager, TaskState, TaskStatus
# from .container_context import ContainerContextManager, ContainerContext
# from .memory_store import MemoryStore, Memory, MemoryType
# from .snapshot import SnapshotManager, SessionSnapshot
# from .context_compression import ContextCompressor, ContextPruner
# from .persistence.postgresql_backend import PostgreSQLBackend
# from .config import StorageConfig
#
# __all__ = [
#     'StorageManager',
#     'TaskStateManager',
#     'TaskState',
#     'TaskStatus',
#     'ContainerContextManager',
#     'ContainerContext',
#     'MemoryStore',
#     'Memory',
#     'MemoryType',
#     'SnapshotManager',
#     'SessionSnapshot',
#     'PostgreSQLBackend',
#     'StorageConfig',
#     'initialize_storage',
#     'get_storage_manager',
# ]
#
# from ..runtime.docker import UnifiedDockerManager

__all__ = [
    "initialize_storage",
    "get_storage_manager",
    "StorageManager",
    "PostgreSQLBackend",
    "StorageConfig",
]


# Application-level singleton for storage management
# Note: This is NOT user/session data - it's an infrastructure component
# managing database connections, context managers, and session-scoped data.
_global_storage: Optional[StorageManager] = None
_storage_lock = asyncio.Lock()


def get_storage_manager() -> StorageManager:
    """
    Get the application-level storage manager singleton.

    Returns:
        StorageManager instance managing infrastructure and session-scoped data.

    Raises:
        RuntimeError: If storage manager not initialized via initialize_storage().

    Note:
        This singleton is justified because:
        1. StorageManager manages infrastructure (DB pools, Docker, LLM)
        2. All session data inside is properly isolated by session_id
        3. Similar to dependency injection containers or application contexts
        4. Must be initialized once at application startup
    """
    global _global_storage
    if _global_storage is None:
        raise RuntimeError("Storage manager not initialized. Call initialize_storage() first.")
    return _global_storage


async def initialize_storage(
    docker_manager: Optional[UnifiedDockerManager],
    llm_provider: BaseChatModel,
    backend: Optional[PostgreSQLBackend] = None,
    config: Optional[StorageConfig] = None,
) -> StorageManager:
    """
    Initialize application-level storage manager with PostgreSQL backend (idempotent).

    This should be called once at application startup. Subsequent calls will
    return the existing instance if already initialized.

    Args:
        docker_manager: Docker manager instance
        llm_provider: LLM provider instance
        backend: Custom PostgreSQL backend instance (optional)
        config: Storage configuration (uses environment variables if not provided)

    Returns:
        StorageManager instance

    Examples:
        # Use PostgreSQL from environment variables
        storage = await initialize_storage(docker_manager, llm_provider)

        # Use custom PostgreSQL backend
        pg_backend = PostgreSQLBackend(
            host="db.example.com",
            database="agent_prod",
            user="agent_user",
            password="secure_password"
        )
        await pg_backend.initialize()
        storage = await initialize_storage(docker_manager, llm_provider, backend=pg_backend)
    """
    global _global_storage

    # Idempotent initialization with async lock
    async with _storage_lock:
        if _global_storage is not None:
            return _global_storage

        # If no backend provided, create one from config
        if backend is None:
            if config is None:
                config = StorageConfig()

            backend_config = config.get_backend_config()

            backend = PostgreSQLBackend(
                host=backend_config["host"],
                port=backend_config["port"],
                database=backend_config["database"],
                user=backend_config["user"],
                password=backend_config["password"],
                min_pool_size=backend_config["min_pool_size"],
                max_pool_size=backend_config["max_pool_size"],
            )
            await backend.initialize()

        _global_storage = StorageManager(backend=backend, docker_manager=docker_manager, llm_provider=llm_provider)
        return _global_storage
