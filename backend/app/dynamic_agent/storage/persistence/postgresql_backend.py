"""
PostgreSQL persistence backend for production use.

Provides scalable, concurrent-safe database operations for agent storage.
Delegates to specialized DAOs for specific domain logic.

Requirements:
    pip install asyncpg
"""

import json
import os
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import asyncpg
from loguru import logger

from app.dynamic_agent.storage.context_manager import SessionContext
from app.dynamic_agent.storage.persistence.daos.session_dao import SessionDAO
from app.dynamic_agent.storage.persistence.daos.task_dao import TaskDAO
from app.dynamic_agent.storage.persistence.db_manager import DatabaseManager
from app.dynamic_agent.storage.persistence.schema_manager import SchemaManager

if TYPE_CHECKING:
    from app.dynamic_agent.storage.container.context import ContainerContext


class PostgreSQLBackend:
    """PostgreSQL persistence backend for production environments."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        database: str = "agent_storage",
        user: str = "postgres",
        password: str = "",
        min_pool_size: int = 10,
        max_pool_size: int = 20,
    ):
        self.db_manager = DatabaseManager(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            min_pool_size=min_pool_size,
            max_pool_size=max_pool_size,
        )
        self.pool: Optional[asyncpg.Pool] = None
        self.session_dao: Optional[SessionDAO] = None
        self.task_dao: Optional[TaskDAO] = None

    def _ensure_pool(self) -> asyncpg.Pool:
        """Ensure pool is initialized, raise error if not."""
        if self.pool is None:
            raise RuntimeError("Backend must be initialized before use")
        return self.pool

    async def initialize(self):
        """Initialize connection pool, schema, and DAOs."""
        # Initialize pool
        await self.db_manager.initialize()
        self.pool = self.db_manager.get_pool()

        # Initialize Schema
        schema_manager = SchemaManager(self.pool)

        # Check if we need to reset database on startup (e.g. dev environment)
        if os.environ.get("RESET_DATABASE", "").lower() in ("true", "1"):
            logger.warning("RESET_DATABASE env var detected. Resetting database schema...")
            await schema_manager.reset_schema()

        await schema_manager.init_schema()

        # Initialize DAOs
        self.session_dao = SessionDAO(self.pool)
        self.task_dao = TaskDAO(self.pool)

    async def close(self):
        """Close connection pool."""
        await self.db_manager.close()

    # --- Session Operations (Delegated to SessionDAO) ---

    async def save_context(self, context: SessionContext):
        """Save session context."""
        if not self.session_dao:
            raise RuntimeError("Backend not initialized")
        await self.session_dao.save_context(context)

    async def load_context(self, session_id: str):
        """Load session context."""
        if not self.session_dao:
            raise RuntimeError("Backend not initialized")
        return await self.session_dao.load_context(session_id)

    async def add_message(
        self, session_id: str, role: str, content: str, metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """Add a message directly to the database."""
        if not self.session_dao:
            raise RuntimeError("Backend not initialized")
        return await self.session_dao.add_message(session_id, role, content, metadata)

    # --- Task Operations (Delegated to TaskDAO) ---
    # Note: Adapting interface for compatibility

    async def save_task(self, task):
        """Save task state.

        Args:
            task: Task object or dict.
                  The TaskDAO expects creation via create_task or update via update_task.
        """
        if not self.task_dao:
            raise RuntimeError("Backend not initialized")

        # Check if task exists
        existing = await self.task_dao.get_task_by_id(task.task_id)

        if existing:
            # Update
            await self.task_dao.update_task(task_id=task.task_id, status=task.status, completed_at=task.completed_at)
        else:
            # Create
            # We store extra fields in metadata.
            metadata = {
                "tool_name": task.tool_name,
                "parameters": task.parameters,
                "result": task.result,
                "error": task.error,
                "container_id": task.container_id,
            }

            await self.task_dao.create_task(
                session_id=task.session_id, user_input=f"Execute tool: {task.tool_name}", metadata=metadata
            )

    async def load_task(self, task_id: str):
        """Load task state."""
        if not self.task_dao:
            raise RuntimeError("Backend not initialized")

        from uuid import UUID

        task_id_uuid = UUID(task_id) if isinstance(task_id, str) else task_id
        task = await self.task_dao.get_task_by_id(task_id_uuid)
        if not task:
            return None

        return task

    async def get_tasks_by_session(self, session_id: str, status=None) -> List:
        """Get all tasks for a session."""
        if not self.task_dao:
            raise RuntimeError("Backend not initialized")

        tasks, _ = await self.task_dao.get_tasks_by_session(session_id, limit=100)
        return tasks

    # --- Other Operations (Kept inline for now, or TODO: move to DAOs) ---
    # Container, Memory, Snapshot operations can be moved to their own DAOs similarly.
    # For brevity, I'm keeping the remaining methods but they should use self.pool directly.

    # Memory Operations
    async def save_memory(self, memory):
        """Save memory."""
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO memories VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                ON CONFLICT (memory_id) DO UPDATE SET
                    accessed_count = EXCLUDED.accessed_count,
                    last_accessed = EXCLUDED.last_accessed
            """,
                memory.memory_id,
                memory.session_id,
                memory.memory_type.value,
                memory.key,
                json.dumps(memory.value, default=str),
                memory.created_at,
                memory.accessed_count,
                memory.last_accessed,
                memory.importance,
                json.dumps(memory.tags, default=str),
                memory.category,
                json.dumps(memory.related_memories, default=str),
                memory.source,
            )

    async def load_memory(self, session_id: str, key: str):
        """Load memory by key."""
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM memories WHERE session_id = $1 AND key = $2", session_id, key)

            if not row:
                return None

            from app.dynamic_agent.storage.memory_store import Memory, MemoryType

            return Memory(
                memory_id=row["memory_id"],
                session_id=row["session_id"],
                memory_type=MemoryType(row["memory_type"]),
                key=row["key"],
                value=json.loads(row["value"]),
                created_at=row["created_at"],
                accessed_count=row["accessed_count"],
                last_accessed=row["last_accessed"],
                importance=row["importance"],
                tags=json.loads(row["tags"]) if row["tags"] else [],
                category=row["category"],
                related_memories=json.loads(row["related_memories"]) if row["related_memories"] else [],
                source=row["source"],
            )

    # ... (Other methods like search_memories, save_container, save_snapshot need to be kept or moved to DAOs)
    # I will preserve them but ensure they use self.pool from the manager.

    # To save tokens and time, I'm only showing the refactored parts.
    # The user should assume other methods (search_memories, containers, snapshots)
    # remain similar but using self.pool.

    # Crucial: The _init_db is removed as it is replaced by SchemaManager.

    async def search_memories(
        self,
        session_id: str,
        query: Optional[str] = None,
        memory_type=None,
        tags: Optional[List[str]] = None,
        category: Optional[str] = None,
        min_importance: float = 0.0,
        limit: int = 10,
    ) -> List:
        """Search memories with PostgreSQL full-text search."""
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            sql = "SELECT * FROM memories WHERE session_id = $1 AND importance >= $2"
            params = [session_id, min_importance]
            param_count = 2

            if memory_type:
                param_count += 1
                sql += f" AND memory_type = ${param_count}"
                params.append(memory_type.value)

            if category:
                param_count += 1
                sql += f" AND category = ${param_count}"
                params.append(category)

            if query:
                param_count += 1
                sql += f" AND (key ILIKE ${param_count} OR value::text ILIKE ${param_count})"
                params.append(f"%{query}%")

            if tags:
                param_count += 1
                sql += f" AND tags @> ${param_count}::jsonb"
                params.append(json.dumps(tags, default=str))

            sql += f" ORDER BY importance DESC, accessed_count DESC LIMIT ${param_count + 1}"
            params.append(limit)

            rows = await conn.fetch(sql, *params)

            from app.dynamic_agent.storage.memory_store import Memory, MemoryType

            memories = []
            for row in rows:
                memories.append(
                    Memory(
                        memory_id=row["memory_id"],
                        session_id=row["session_id"],
                        memory_type=MemoryType(row["memory_type"]),
                        key=row["key"],
                        value=json.loads(row["value"]),
                        created_at=row["created_at"],
                        accessed_count=row["accessed_count"],
                        last_accessed=row["last_accessed"],
                        importance=row["importance"],
                        tags=json.loads(row["tags"]) if row["tags"] else [],
                        category=row["category"],
                        related_memories=json.loads(row["related_memories"]) if row["related_memories"] else [],
                        source=row["source"],
                    )
                )

            return memories

    async def update_memory_stats(self, memory):
        """Update memory access statistics."""
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE memories
                SET accessed_count = $1, last_accessed = $2
                WHERE memory_id = $3
            """,
                memory.accessed_count,
                memory.last_accessed,
                memory.memory_id,
            )

    async def delete_memory(self, memory_id: str):
        """Delete a memory."""
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM memories WHERE memory_id = $1", memory_id)

    # Container Context Operations
    async def save_container(self, container):
        """Save container context."""
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO container_contexts VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                ON CONFLICT (container_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    working_directory = EXCLUDED.working_directory,
                    installed_tools = EXCLUDED.installed_tools,
                    command_history = EXCLUDED.command_history,
                    cpu_usage = EXCLUDED.cpu_usage,
                    memory_usage = EXCLUDED.memory_usage,
                    last_accessed = EXCLUDED.last_accessed
            """,
                container.container_id,
                container.session_id,
                container.image,
                container.status,
                container.working_directory,
                json.dumps(container.mounted_volumes, default=str),
                json.dumps(container.environment, default=str),
                json.dumps(container.installed_tools, default=str),
                json.dumps(container.command_history, default=str),
                container.cpu_usage,
                container.memory_usage,
                container.created_at,
                container.last_accessed,
            )

    async def load_container(self, container_id: str) -> Optional["ContainerContext"]:
        """Load container context."""
        from app.dynamic_agent.storage.container.context import ContainerContext

        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM container_contexts WHERE container_id = $1", container_id)

            if not row:
                return None

            return ContainerContext(
                container_id=row["container_id"],
                session_id=row["session_id"],
                image=row["image"],
                status=row["status"],
                working_directory=row["working_directory"],
                mounted_volumes=json.loads(row["mounted_volumes"]) if row["mounted_volumes"] else {},
                environment=json.loads(row["environment"]) if row["environment"] else {},
                installed_tools=json.loads(row["installed_tools"]) if row["installed_tools"] else [],
                command_history=json.loads(row["command_history"]) if row["command_history"] else [],
                cpu_usage=row["cpu_usage"],
                memory_usage=row["memory_usage"],
                created_at=row["created_at"],
                last_accessed=row["last_accessed"],
            )

    async def get_container_by_session(self, session_id: str) -> Optional["ContainerContext"]:
        """Get container for a session."""
        from app.dynamic_agent.storage.container.context import ContainerContext

        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM container_contexts WHERE session_id = $1", session_id)

            if not row:
                return None

            return ContainerContext(
                container_id=row["container_id"],
                session_id=row["session_id"],
                image=row["image"],
                status=row["status"],
                working_directory=row["working_directory"],
                mounted_volumes=json.loads(row["mounted_volumes"]) if row["mounted_volumes"] else {},
                environment=json.loads(row["environment"]) if row["environment"] else {},
                installed_tools=json.loads(row["installed_tools"]) if row["installed_tools"] else [],
                command_history=json.loads(row["command_history"]) if row["command_history"] else [],
                cpu_usage=row["cpu_usage"],
                memory_usage=row["memory_usage"],
                created_at=row["created_at"],
                last_accessed=row["last_accessed"],
            )

    # Snapshot Operations
    async def save_snapshot(self, snapshot):
        """Save snapshot."""
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO snapshots VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
                snapshot.snapshot_id,
                snapshot.session_id,
                snapshot.created_at,
                #                todo
                json.dumps(snapshot.context, default=str),
                json.dumps(snapshot.active_tasks, default=str),
                json.dumps(snapshot.container_state, default=str),
                json.dumps(snapshot.memory_state, default=str),
                snapshot.description,
                snapshot.checkpoint_type,
            )

    async def load_snapshot(self, snapshot_id: str):
        """Load snapshot."""
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM snapshots WHERE snapshot_id = $1", snapshot_id)

            if not row:
                return None

            from app.dynamic_agent.storage.snapshot import SessionSnapshot

            return SessionSnapshot(
                snapshot_id=row["snapshot_id"],
                session_id=row["session_id"],
                created_at=row["created_at"],
                context=json.loads(row["context"]),
                active_tasks=json.loads(row["active_tasks"]) if row["active_tasks"] else [],
                container_state=json.loads(row["container_state"]) if row["container_state"] else None,
                memory_state=json.loads(row["memory_state"]) if row["memory_state"] else [],
                description=row["description"],
                checkpoint_type=row["checkpoint_type"],
            )

    async def list_snapshots(self, session_id: str, limit: int = 10) -> List:
        """List snapshots for a session."""
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM snapshots WHERE session_id = $1 ORDER BY created_at DESC LIMIT $2", session_id, limit
            )

            from app.dynamic_agent.storage.snapshot import SessionSnapshot

            snapshots = []
            for row in rows:
                snapshots.append(
                    SessionSnapshot(
                        snapshot_id=row["snapshot_id"],
                        session_id=row["session_id"],
                        created_at=row["created_at"],
                        context=json.loads(row["context"]),
                        active_tasks=json.loads(row["active_tasks"]) if row["active_tasks"] else [],
                        container_state=json.loads(row["container_state"]) if row["container_state"] else None,
                        memory_state=json.loads(row["memory_state"]) if row["memory_state"] else [],
                        description=row["description"],
                        checkpoint_type=row["checkpoint_type"],
                    )
                )

            return snapshots

    async def delete_snapshot(self, snapshot_id: str):
        """Delete a snapshot."""
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM snapshots WHERE snapshot_id = $1", snapshot_id)

    # Container Binding Operations
    async def create_container_binding(
        self,
        binding_id: str,
        user_id: str,
        container_id: str,
        container_name: str,
        image: str,
        mcp_api: str,
        docker_api: str,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Create a new container binding for a user."""
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            now = datetime.utcnow()
            await conn.execute(
                """
                               INSERT INTO container_bindings
                               (binding_id, user_id, session_id, container_id, container_name, image,
                                   docker_api, mcp_api,
                                status, created_at, last_used_at, is_active, metadata)
                               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13) ON CONFLICT (container_id) DO
                               UPDATE SET
                                   session_id = EXCLUDED.session_id,
                                   last_used_at = EXCLUDED.last_used_at,
                                   is_active = EXCLUDED.is_active,
                                   metadata = EXCLUDED.metadata
                               """,
                binding_id,
                user_id,
                session_id,
                container_id,
                container_name,
                image,
                docker_api,
                mcp_api,
                "active",
                now,
                now,
                True,
                json.dumps(metadata or {}),
            )

    async def get_active_container_for_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get the active container for a user (if any)."""
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM container_bindings
                WHERE user_id = $1 AND is_active = TRUE
                ORDER BY last_used_at DESC
                LIMIT 1
            """,
                user_id,
            )

            if row:
                return {
                    "binding_id": row["binding_id"],
                    "user_id": row["user_id"],
                    "session_id": row["session_id"],
                    "container_id": row["container_id"],
                    "container_name": row["container_name"],
                    "image": row["image"],
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "last_used_at": row["last_used_at"],
                    "is_active": row["is_active"],
                    "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                    "docker_api": row["docker_api"],
                    "mcp_api": row["mcp_api"],
                }
            return None

    async def update_container_binding_session(self, container_id: str, session_id: str):
        """Update the session associated with a container binding."""
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE container_bindings
                SET session_id = $1, last_used_at = $2
                WHERE container_id = $3
            """,
                session_id,
                datetime.utcnow(),
                container_id,
            )

    async def update_container_binding_status(self, container_id: str, status: str):
        """Update container binding status."""
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE container_bindings
                SET status = $1, last_used_at = $2
                WHERE container_id = $3
            """,
                status,
                datetime.utcnow(),
                container_id,
            )

    async def deactivate_container_binding(self, container_id: str):
        """Deactivate a container binding."""
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE container_bindings
                SET is_active = FALSE, last_used_at = $1
                WHERE container_id = $2
            """,
                datetime.utcnow(),
                container_id,
            )

    async def deactivate_user_containers(self, user_id: str):
        """Deactivate all containers for a user."""
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE container_bindings
                SET is_active = FALSE, last_used_at = $1
                WHERE user_id = $2
            """,
                datetime.utcnow(),
                user_id,
            )

    async def get_container_binding(self, container_id: str) -> Optional[Dict[str, Any]]:
        """Get container binding by container ID."""
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM container_bindings
                WHERE container_id = $1
            """,
                container_id,
            )

            if row:
                return {
                    "binding_id": row["binding_id"],
                    "user_id": row["user_id"],
                    "session_id": row["session_id"],
                    "container_id": row["container_id"],
                    "container_name": row["container_name"],
                    "image": row["image"],
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "last_used_at": row["last_used_at"],
                    "is_active": row["is_active"],
                    "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                    "docker_api": row["docker_api"],
                    "mcp_api": row["mcp_api"],
                }
            return None

    async def list_user_containers(self, user_id: str, active_only: bool = True) -> List[Dict[str, Any]]:
        """List all containers for a user."""
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            if active_only:
                rows = await conn.fetch(
                    """
                    SELECT * FROM container_bindings
                    WHERE user_id = $1 AND is_active = TRUE
                    ORDER BY last_used_at DESC
                """,
                    user_id,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT * FROM container_bindings
                    WHERE user_id = $1
                    ORDER BY last_used_at DESC
                """,
                    user_id,
                )

            containers = []
            for row in rows:
                containers.append(
                    {
                        "binding_id": row["binding_id"],
                        "user_id": row["user_id"],
                        "session_id": row["session_id"],
                        "container_id": row["container_id"],
                        "container_name": row["container_name"],
                        "image": row["image"],
                        "status": row["status"],
                        "created_at": row["created_at"],
                        "last_used_at": row["last_used_at"],
                        "is_active": row["is_active"],
                        "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                        "docker_api": row["docker_api"],
                        "mcp_api": row["mcp_api"],
                    }
                )
            return containers

    async def delete_container_binding(self, container_id: str):
        """Delete a container binding."""
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM container_bindings
                WHERE container_id = $1
            """,
                container_id,
            )

    async def update_container_binding_service(
        self, container_id: str, docker_api: Optional[str] = None, mcp_api: Optional[str] = None
    ):
        """Update container binding with API endpoints."""
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE container_bindings
                SET docker_api = $1, mcp_api = $2
                WHERE container_id = $3
            """,
                docker_api,
                mcp_api,
                container_id,
            )
