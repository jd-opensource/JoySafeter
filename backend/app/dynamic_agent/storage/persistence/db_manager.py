"""
Database Manager Module.

Handles asyncpg connection pool lifecycle management.
"""

from typing import Optional

import asyncpg
from loguru import logger


class DatabaseManager:
    """Manages PostgreSQL connection pool."""

    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(DatabaseManager, cls).__new__(cls)
        return cls._instance

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        database: str = "agent_storage",
        user: str = "postgres",
        password: str = "",
        min_pool_size: int = 20,
        max_pool_size: int = 50,
    ):
        if not hasattr(self, "pool"):
            self.host = host
            self.port = port
            self.database = database
            self.user = user
            self.password = password
            self.min_pool_size = min_pool_size
            self.max_pool_size = max_pool_size
            self.pool: Optional[asyncpg.Pool] = None

    async def initialize(self):
        """Initialize database connection pool with pre-warming."""
        if self.pool:
            logger.info(f"Database pool already initialized (min={self.min_pool_size}, max={self.max_pool_size})")
            return

        logger.info(
            f"Creating database pool: host={self.host}, port={self.port}, db={self.database}, user={self.user}, min_size={self.min_pool_size}, max_size={self.max_pool_size}"
        )

        try:
            self.pool = await asyncpg.create_pool(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
                min_size=self.min_pool_size,
                max_size=self.max_pool_size,
                command_timeout=60,
                # Add connection lifecycle management
                timeout=30,  # Connection acquisition timeout (seconds)
                max_inactive_connection_lifetime=300,  # Recycle idle connections after 5 minutes
                max_queries=50000,  # Recycle connection after 50000 queries
                # # Enable connection validation
                # configure=lambda conn: conn.add_termination_listener(
                #     lambda conn: logger.debug("Connection terminated")
                # )
            )
            logger.info(
                f"✅ Database connection pool created for {self.database} (min_size={self.min_pool_size}, max_size={self.max_pool_size})"
            )

            # Pre-warm the pool by acquiring min_size connections
            # This prevents runtime latency when connections are first needed
            await self._prewarm_pool()

        except Exception as e:
            logger.error(f"❌ Failed to initialize database pool: {e}")
            raise

    async def _prewarm_pool(self):
        """Pre-warm the connection pool by establishing min_size connections.

        This prevents first-use latency and connection creation storms under high concurrency.
        """
        import asyncio as async_lib

        if self.pool is None:
            raise RuntimeError("Pool must be initialized before pre-warming")

        logger.info(f"Pre-warming connection pool (creating {self.min_pool_size} connections)...")

        async def acquire_and_test(idx: int):
            """Acquire a connection, test it, and hold it until all are ready."""
            if self.pool is None:
                raise RuntimeError("Database pool not initialized")
            conn = None
            try:
                conn = await self.pool.acquire(timeout=10.0)
                # Test the connection with a simple query
                result = await conn.fetchval("SELECT 1")
                if result == 1:
                    logger.debug(f"✓ Pre-warmed connection {idx + 1}/{self.min_pool_size}")
                    return (idx, conn, True)
                else:
                    logger.error(f"✗ Connection {idx + 1} returned unexpected result: {result}")
                    return (idx, None, False)
            except Exception as e:
                logger.error(f"✗ Failed to pre-warm connection {idx + 1}: {e}")
                if conn and self.pool is not None:
                    # Release bad connection back to pool
                    await self.pool.release(conn)
                return (idx, None, False)

        # Acquire connections in parallel
        tasks = [acquire_and_test(i) for i in range(self.min_pool_size)]
        results = await async_lib.gather(*tasks, return_exceptions=True)

        # Release all successfully acquired connections back to the pool
        connections = []
        success_count = 0
        for result in results:
            if isinstance(result, tuple) and len(result) == 3:
                idx, conn, success = result
                if conn:
                    connections.append((idx, conn))
                if success:
                    success_count += 1
            elif isinstance(result, Exception):
                logger.error(f"✗ Exception during pre-warming: {result}")

        # Release all held connections back to pool
        for idx, conn in connections:
            try:
                await self.pool.release(conn)
            except Exception as e:
                logger.error(f"✗ Failed to release connection {idx}: {e}")

        # Verify pool size
        actual_size = self.pool.get_size() if hasattr(self.pool, "get_size") else "unknown"
        logger.info(
            f"✅ Connection pool pre-warmed: {success_count}/{self.min_pool_size} connections ready (actual pool size: {actual_size})"
        )

        if success_count != self.min_pool_size:
            logger.warning(
                f"⚠️  Expected {self.min_pool_size} connections, but only {success_count} were successfully created"
            )
            logger.warning("⚠️  This may cause connection errors under high load")
            logger.warning(
                "⚠️  Check database connection limits, network stability, and PostgreSQL max_connections setting"
            )

    async def close(self):
        """Close database connection pool."""
        if self.pool:
            await self.pool.close()
            self.pool = None
            logger.info("Database connection pool closed")

    def get_pool(self) -> asyncpg.Pool:
        """Get the connection pool."""
        if not self.pool:
            raise RuntimeError("Database pool not initialized. Call initialize() first.")
        return self.pool
