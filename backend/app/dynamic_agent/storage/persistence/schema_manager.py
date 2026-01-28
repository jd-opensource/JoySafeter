"""
Schema Manager Module.

Defines the optimized database schema and handles initialization.
Uses raw SQL for full control over PostgreSQL features (JSONB, Indexes).
"""

import asyncpg
from loguru import logger


class SchemaManager:
    """Manages database schema creation and updates."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def init_schema(self):
        """Initialize the optimized database schema."""
        async with self.pool.acquire() as conn:
            logger.info("Initializing optimized database schema...")

            # 1. Session Tables (Normalized)
            await self._create_session_tables(conn)

            # 2. Task Execution Tables (New Feature)
            await self._create_task_tables(conn)

            # 3. Container Tables
            await self._create_container_tables(conn)

            # 4. Memory Tables
            await self._create_memory_tables(conn)

            # 5. Snapshot Tables
            await self._create_snapshot_tables(conn)

            # 6. Indexes
            await self._create_indexes(conn)

            logger.info("Schema initialization complete.")

    async def reset_schema(self):
        """Drop all tables to start fresh."""
        tables = [
            # Child tables first
            "execution_steps",
            "session_messages",
            "session_metadata",
            "container_bindings",
            # Core tables
            "tasks",
            "memories",
            "snapshots",
            "container_contexts",
            "session_contexts",
        ]

        async with self.pool.acquire() as conn:
            logger.warning("⚠️  RESETTING SCHEMA: Dropping all tables...")
            for table in tables:
                try:
                    await conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
                    logger.info(f"Dropped table: {table}")
                except Exception as e:
                    logger.warning(f"Error dropping table {table}: {e}")

    async def _create_session_tables(self, conn):
        # Core session info
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS session_contexts (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                container_id TEXT,
                working_directory TEXT,
                scenario TEXT,
                status TEXT DEFAULT 'active'
            )
        """)

        # Session messages (Split from session_contexts for performance)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS session_messages (
                message_id SERIAL PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES session_contexts(session_id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TIMESTAMP NOT NULL DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
                metadata JSONB
            )
        """)

        # Session metadata (Split from session_contexts)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS session_metadata (
                metadata_id SERIAL PRIMARY KEY,
                session_id TEXT NOT NULL UNIQUE REFERENCES session_contexts(session_id) ON DELETE CASCADE,
                metadata JSONB DEFAULT '{}',
                target_info JSONB DEFAULT '{}',
                active_tasks JSONB DEFAULT '[]',
                completed_tasks JSONB DEFAULT '[]',
                updated_at TIMESTAMP NOT NULL DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')
            )
        """)

    async def _create_task_tables(self, conn):
        # Unified Tasks Table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                parent_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
                created_by_step_id UUID,
                level INTEGER NOT NULL DEFAULT 1,
                session_id TEXT NOT NULL REFERENCES session_contexts(session_id) ON DELETE CASCADE,
                message_id INTEGER REFERENCES session_messages(message_id) ON DELETE SET NULL,
                user_input TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                created_at TIMESTAMP NOT NULL DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
                updated_at TIMESTAMP NOT NULL DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
                completed_at TIMESTAMP,
                result_summary TEXT,
                metadata JSONB DEFAULT '{}'
            )
        """)

        # Execution Steps Table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS execution_steps (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                step_type TEXT NOT NULL,
                name TEXT NOT NULL,
                input_data JSONB DEFAULT '{}',
                output_data JSONB,
                status TEXT NOT NULL DEFAULT 'RUNNING',
                start_time TIMESTAMP NOT NULL DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
                end_time TIMESTAMP,
                error_message TEXT,
                agent_trace JSONB,
                created_at TIMESTAMP NOT NULL DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')
            )
        """)

    async def _create_container_tables(self, conn):
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS container_contexts (
                container_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES session_contexts(session_id) ON DELETE CASCADE,
                image TEXT NOT NULL,
                status TEXT NOT NULL,
                working_directory TEXT,
                cpu_usage REAL DEFAULT 0.0,
                memory_usage BIGINT DEFAULT 0,
                created_at TIMESTAMP NOT NULL,
                last_accessed TIMESTAMP NOT NULL
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS container_bindings (
                binding_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                session_id TEXT REFERENCES session_contexts(session_id) ON DELETE SET NULL,
                container_id TEXT NOT NULL UNIQUE,
                container_name TEXT,
                image TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                last_used_at TIMESTAMP NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                metadata JSONB,
                docker_api TEXT,
                mcp_api TEXT
            )
        """)

    async def _create_memory_tables(self, conn):
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                memory_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES session_contexts(session_id) ON DELETE CASCADE,
                memory_type TEXT NOT NULL,
                key TEXT NOT NULL,
                value JSONB NOT NULL,
                created_at TIMESTAMP NOT NULL,
                accessed_count INTEGER DEFAULT 0,
                last_accessed TIMESTAMP,
                importance REAL DEFAULT 0.5,
                tags JSONB,
                category TEXT,
                related_memories JSONB,
                source TEXT
            )
        """)

    async def _create_snapshot_tables(self, conn):
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                snapshot_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES session_contexts(session_id) ON DELETE CASCADE,
                created_at TIMESTAMP NOT NULL,
                description TEXT,
                checkpoint_type TEXT,
                context JSONB,
                active_tasks JSONB,
                container_state JSONB,
                memory_state JSONB
            )
        """)

    async def _create_indexes(self, conn):
        indexes = [
            # Session
            "CREATE INDEX IF NOT EXISTS idx_session_user ON session_contexts(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_session_created ON session_contexts(created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_message_session ON session_messages(session_id)",
            # Tasks & Steps
            "CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_id)",
            "CREATE INDEX IF NOT EXISTS idx_steps_task ON execution_steps(task_id)",
            # Memory
            "CREATE INDEX IF NOT EXISTS idx_memory_session ON memories(session_id)",
            "CREATE INDEX IF NOT EXISTS idx_memory_importance ON memories(importance DESC)",
            # JSONB GIN Indexes
            "CREATE INDEX IF NOT EXISTS idx_memory_value_gin ON memories USING GIN (value)",
            "CREATE INDEX IF NOT EXISTS idx_metadata_gin ON session_metadata USING GIN (metadata)",
        ]

        for index_sql in indexes:
            try:
                await conn.execute(index_sql)
            except Exception as e:
                logger.warning(f"Index creation warning: {e}")
