"""
Database Initialization Script

Initializes the database schema using SchemaManager.
Can optionally reset the database by dropping existing tables.

Usage:
    python init_database.py --host localhost --database agent_storage --reset
"""

import argparse
import asyncio

# Add project root to python path to allow imports
import os
import sys
from typing import Optional

import asyncpg

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../")))

# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
# )
from loguru import logger

from app.dynamic_agent.storage.persistence.schema_manager import SchemaManager


class DatabaseInitializer:
    """Handles database schema initialization."""

    def __init__(self, host: str, port: int, database: str, user: str, password: str):
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        """Connect to database."""
        try:
            self.pool = await asyncpg.create_pool(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
                min_size=1,
                max_size=5,
            )
            logger.info(f"Connected to {self.database} at {self.host}:{self.port}")
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise

    async def disconnect(self):
        """Disconnect from database."""
        if self.pool:
            await self.pool.close()
            logger.info("Disconnected from database")

    async def reset_database(self):
        """Drop all tables to start fresh."""
        if not self.pool:
            raise RuntimeError("Database not connected")

        manager = SchemaManager(self.pool)
        await manager.reset_schema()

        logger.info("Database reset complete.")

    async def initialize_schema(self):
        """Initialize the schema."""
        if not self.pool:
            raise RuntimeError("Database not connected")

        logger.info("Initializing schema...")

        manager = SchemaManager(self.pool)
        await manager.init_schema()

        logger.info("Schema initialization complete.")

    async def run(self, reset: bool = False):
        """Run initialization process."""
        try:
            await self.connect()

            if reset:
                await self.reset_database()

            await self.initialize_schema()

        except Exception as e:
            logger.error(f"❌ Initialization failed: {e}", exc_info=True)
            raise
        finally:
            await self.disconnect()


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Initialize database schema")
    parser.add_argument("--host", default="localhost", help="Database host")
    parser.add_argument("--port", type=int, default=5432, help="Database port")
    parser.add_argument("--database", default="agent_storage", help="Database name")
    parser.add_argument("--user", default="postgres", help="Database user")
    parser.add_argument("--password", default="", help="Database password")
    parser.add_argument("--reset", action="store_true", help="Drop existing tables before initialization")

    args = parser.parse_args()

    initializer = DatabaseInitializer(
        host=args.host, port=args.port, database=args.database, user=args.user, password=args.password
    )

    await initializer.run(reset=args.reset)


if __name__ == "__main__":
    asyncio.run(main())
