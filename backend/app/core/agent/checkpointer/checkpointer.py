"""
LangGraph checkpoint management.

Manages persistence of conversation state.
集中管理 checkpointer 的所有逻辑，提供统一的接口。
"""

import os
from typing import TYPE_CHECKING, Optional

from loguru import logger
from psycopg_pool import AsyncConnectionPool

if TYPE_CHECKING:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


class CheckpointerManager:
    """
    集中管理 checkpointer 的全局管理器。

    负责：
    - 全局连接池的生命周期管理
    - 根据配置自动提供 checkpointer 实例
    - 数据库表的初始化
    """

    _pool: Optional[AsyncConnectionPool] = None
    _initialized: bool = False

    @classmethod
    def _get_db_uri(cls) -> str:
        """
        构建数据库连接 URI。

        从环境变量读取 PostgreSQL 连接信息并构建连接字符串。

        Returns:
            str: PostgreSQL 连接 URI，格式为 postgresql://user:password@host:port/database

        Raises:
            ValueError: 如果必需的环境变量未设置
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

        # password 可以为空字符串，所以只检查是否为 None
        password = password or ""

        return f"postgresql://{user}:{password}@{host}:{port}/{database}"

    @classmethod
    async def initialize(cls) -> None:
        """
        应用启动时初始化连接池。

        应该在应用启动时调用一次，通常在 lifespan 中。
        此方法会：
        1. 创建 AsyncConnectionPool 连接池
        2. 打开连接池
        3. 初始化数据库表结构

        Raises:
            ValueError: 如果数据库连接配置无效
            Exception: 如果连接池初始化或数据库表创建失败
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
                open=False,  # 不在构造函数中自动打开
            )
            # 显式打开连接池
            await cls._pool.open()
            cls._initialized = True
            logger.info(
                f"CheckpointerManager initialized | "
                f"pool_size={os.getenv('DB_POOL_MIN_SIZE', 1)}-{os.getenv('DB_POOL_MAX_SIZE', 10)}"
            )

            # 初始化数据库表结构
            await cls._init_db()
        except Exception as e:
            logger.error(f"Failed to initialize CheckpointerManager: {e}")
            # 如果初始化失败，确保清理连接池
            if cls._pool:
                try:
                    await cls._pool.close()
                except Exception:
                    pass
                cls._pool = None
            raise

    @classmethod
    async def _init_db(cls) -> None:
        """
        确保数据库表结构已创建。

        使用 AsyncPostgresSaver 创建必要的数据库表和索引。
        此方法在连接池初始化后自动调用。

        Raises:
            RuntimeError: 如果连接池未初始化
            Exception: 如果数据库表创建失败
        """
        if not cls._pool:
            raise RuntimeError("Pool not initialized. Call initialize() first.")

        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        checkpointer = AsyncPostgresSaver(cls._pool)  # type: ignore[arg-type]
        await checkpointer.setup()
        logger.info("Checkpointer tables ready.")

    @classmethod
    def _get_pool(cls) -> AsyncConnectionPool:
        """
        获取连接池（内部方法）。

        Returns:
            AsyncConnectionPool: 已初始化的连接池实例

        Raises:
            RuntimeError: 如果 CheckpointerManager 未初始化
        """
        if not cls._pool:
            raise RuntimeError(
                "CheckpointerManager not initialized. Call CheckpointerManager.initialize() at application startup."
            )
        return cls._pool

    @classmethod
    def get_checkpointer(cls) -> Optional["AsyncPostgresSaver"]:
        """
        获取 checkpointer 实例。

        每次调用都会创建新的 AsyncPostgresSaver 实例，确保使用最新的连接池状态。

        Returns:
            Optional[AsyncPostgresSaver]: AsyncPostgresSaver 实例或 None

        Raises:
            RuntimeError: 如果 CheckpointerManager 未初始化
        """
        pool = cls._get_pool()
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        return AsyncPostgresSaver(pool)  # type: ignore[arg-type]

    @classmethod
    async def close(cls) -> None:
        """
        应用关闭时关闭连接池。

        应该在应用关闭时调用，通常在 lifespan 中。
        此方法会安全地关闭连接池并清理资源。

        Note:
            即使关闭过程中出现异常，也会确保资源被清理。
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
    """
    统一的 checkpointer 获取接口。

    便捷函数，内部调用 CheckpointerManager.get_checkpointer()。
    自动根据配置返回 checkpointer 或 None。

    Returns:
        Optional[AsyncPostgresSaver]: AsyncPostgresSaver 实例或 None

    Raises:
        RuntimeError: 如果 CheckpointerManager 未初始化
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
        async for checkpoint_tuple in checkpointer.alist(config):
            # checkpoint_tuple: (config, checkpoint, metadata, parent_config)
            # transform to simple dict
            history.append({
                "timestamp": checkpoint_tuple.metadata.get("timestamp") if checkpoint_tuple.metadata else None,
                "node_id": checkpoint_tuple.metadata.get("source") if checkpoint_tuple.metadata else None,
                "state": checkpoint_tuple.checkpoint,
                "config": checkpoint_tuple.config,
                "metadata": checkpoint_tuple.metadata,
            })
    except Exception as e:
        logger.error(f"Failed to fetch history for thread {thread_id}: {e}")
        # Return empty list or re-raise? 
        # For debugger, empty list handling in frontend is better than 500
        return []
        
    return history

