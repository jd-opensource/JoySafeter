"""
LangGraph checkpoint management.

Manages persistence of conversation state.
Centralize all checkpointer logic and provide a unified interface.
"""

import os
from typing import TYPE_CHECKING, Optional

from loguru import logger
from psycopg_pool import AsyncConnectionPool

if TYPE_CHECKING:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


class CheckpointerManager:
    """Global manager for centralized checkpointer management.

    Responsible for:
    - Global connection pool lifecycle management
    - Providing checkpointer instances based on configuration
    - Database table initialization
    """

    _pool: Optional[AsyncConnectionPool] = None
    _initialized: bool = False

    @classmethod
    def _get_db_uri(cls) -> str:
        """Build the database connection URI.

        Read PostgreSQL connection info from environment variables and build
        the connection string.

        Returns:
            str: PostgreSQL connection URI (postgresql://user:password@host:port/database).

        Raises:
            ValueError: If required environment variables are not set.
        """
        user = os.getenv("POSTGRES_USER")
        password = os.getenv("POSTGRES_PASSWORD")
        host = os.getenv("POSTGRES_HOST", "localhost")
        port = os.getenv("POSTGRES_PORT", "5432")
        database = os.getenv("POSTGRES_DB")

        if not user:
            raise ValueError("POSTGRES_USER environment variable is required")
        if not database:
            raise ValueError("POSTGRES_DB environment variable is required")

        # password can be an empty string, so only check for None
        password = password or ""

        return f"postgresql://{user}:{password}@{host}:{port}/{database}"

    @classmethod
    async def initialize(cls) -> None:
        """Initialize the connection pool at application startup.

        Should be called once at startup, typically in the lifespan handler.
        This method will:
        1. Create an AsyncConnectionPool
        2. Open the pool
        3. Initialize database table schema

        Raises:
            ValueError: If database connection config is invalid.
            Exception: If pool initialization or table creation fails.
        """
        if cls._initialized:
            logger.warning("CheckpointerManager already initialized, skipping")
            return

        try:
            db_uri = cls._get_db_uri()
            cls._pool = AsyncConnectionPool(
                conninfo=db_uri,
                min_size=int(os.getenv("DB_POOL_MIN_SIZE", 1)),
                max_size=int(os.getenv("DB_POOL_MAX_SIZE", 10)),
                kwargs={"autocommit": True, "prepare_threshold": 0},
                open=False,  # do not auto-open in constructor
            )
            # explicitly open the pool
            await cls._pool.open()
            cls._initialized = True
            logger.info(
                f"CheckpointerManager initialized | "
                f"pool_size={os.getenv('DB_POOL_MIN_SIZE', 1)}-{os.getenv('DB_POOL_MAX_SIZE', 10)}"
            )

            # initialize database table schema
            await cls._init_db()
        except Exception as e:
            logger.error(f"Failed to initialize CheckpointerManager: {e}")
            # if initialization fails, ensure the pool is cleaned up
            if cls._pool:
                try:
                    await cls._pool.close()
                except Exception:
                    pass
                cls._pool = None
            raise

    @classmethod
    async def _init_db(cls) -> None:
        """Ensure database table schema is created.

        Use AsyncPostgresSaver to create the necessary tables and indexes.
        Called automatically after pool initialization.

        Raises:
            RuntimeError: If the pool is not initialized.
            Exception: If table creation fails.
        """
        if not cls._pool:
            raise RuntimeError("Pool not initialized. Call initialize() first.")

        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        checkpointer = AsyncPostgresSaver(cls._pool)  # type: ignore[arg-type]
        await checkpointer.setup()
        logger.info("Checkpointer tables ready.")

    @classmethod
    def _get_pool(cls) -> AsyncConnectionPool:
        """Get the connection pool (internal method).

        Returns:
            AsyncConnectionPool: The initialized pool instance.

        Raises:
            RuntimeError: If CheckpointerManager is not initialized.
        """
        if not cls._pool:
            raise RuntimeError(
                "CheckpointerManager not initialized. Call CheckpointerManager.initialize() at application startup."
            )
        return cls._pool

    @classmethod
    def get_checkpointer(cls) -> Optional["AsyncPostgresSaver"]:
        """Get a checkpointer instance.

        Each call creates a new AsyncPostgresSaver instance to ensure
        the latest pool state is used.

        Returns:
            Optional[AsyncPostgresSaver]: An AsyncPostgresSaver instance, or None.

        Raises:
            RuntimeError: If CheckpointerManager is not initialized.
        """
        pool = cls._get_pool()
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        return AsyncPostgresSaver(pool)  # type: ignore[arg-type]

    @classmethod
    async def close(cls) -> None:
        """Close the connection pool at application shutdown.

        Should be called at shutdown, typically in the lifespan handler.
        Safely closes the pool and cleans up resources.

        Note:
            Resources are cleaned up even if an exception occurs during close.
        """
        if cls._pool:
            try:
                await cls._pool.close()
                logger.info("CheckpointerManager connection pool closed")
            except Exception as e:
                logger.error(f"Error closing CheckpointerManager pool: {e}")
            finally:
                cls._pool = None
                cls._initialized = False


def get_checkpointer() -> Optional["AsyncPostgresSaver"]:
    """Unified checkpointer access interface.

    Convenience function that delegates to CheckpointerManager.get_checkpointer().
    Automatically returns a checkpointer or None based on configuration.

    Returns:
        Optional[AsyncPostgresSaver]: An AsyncPostgresSaver instance, or None.

    Raises:
        RuntimeError: If CheckpointerManager is not initialized.
    """
    return CheckpointerManager.get_checkpointer()


async def delete_thread_checkpoints(thread_id: str) -> None:
    """
    Delete all checkpoints for the specified thread.

    Args:
        thread_id: Thread ID.

    Raises:
        RuntimeError: If checkpoint is not enabled or checkpointer is not initialized.
    """
    checkpointer = get_checkpointer()
    if checkpointer is None:
        raise RuntimeError("Checkpoint is not enabled. Enable checkpoint in settings to use this function.")

    try:
        await checkpointer.adelete_thread(thread_id)
        logger.info(f"✅ Deleted checkpoints for thread: {thread_id}")
    except Exception as e:
        logger.error(f"❌ Failed to delete checkpoints for thread {thread_id}: {e}")
        raise


async def get_thread_history(thread_id: str) -> list[dict]:
    """
    Get execution history (checkpoints) for a thread.

    Returns a list of checkpoints ordered by timestamp (descending usually, depends on alist implementation).
    """
    checkpointer = get_checkpointer()
    if not checkpointer:
        return []

    config = {"configurable": {"thread_id": thread_id}}
    history = []

    try:
        from typing import Any, cast

        async for checkpoint_tuple in checkpointer.alist(cast(Any, config)):
            # checkpoint_tuple: (config, checkpoint, metadata, parent_config)
            # transform to simple dict
            history.append(
                {
                    "timestamp": checkpoint_tuple.metadata.get("timestamp") if checkpoint_tuple.metadata else None,
                    "node_id": checkpoint_tuple.metadata.get("source") if checkpoint_tuple.metadata else None,
                    "state": checkpoint_tuple.checkpoint,
                    "config": checkpoint_tuple.config,
                    "metadata": checkpoint_tuple.metadata,
                }
            )
    except Exception as e:
        logger.error(f"Failed to fetch history for thread {thread_id}: {e}")
        # Return empty list or re-raise?
        # For debugger, empty list handling in frontend is better than 500
        return []

    return history
