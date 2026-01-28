"""
Storage configuration management.

PostgreSQL backend configuration with environment variable support.
"""

import os
from typing import Optional


class StorageConfig:
    # !!! used to load conf, do not remove
    from app.dynamic_agent.core.config import conf

    # PostgreSQL configuration
    POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "localhost")
    POSTGRES_PORT: int = int(os.getenv("POSTGRES_PORT", "5432"))
    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "agent_storage")
    POSTGRES_USER: str = os.getenv("POSTGRES_USER", "agent_user")
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "")

    # Connection pool settings
    POSTGRES_MIN_POOL_SIZE: int = int(os.getenv("POSTGRES_MIN_POOL_SIZE", "10"))
    POSTGRES_MAX_POOL_SIZE: int = int(os.getenv("POSTGRES_MAX_POOL_SIZE", "50"))

    # SSL settings
    POSTGRES_SSL: Optional[str] = os.getenv("POSTGRES_SSL", None)  # 'require', 'prefer', 'disable'

    @classmethod
    def get_backend_config(cls) -> dict:
        """Get PostgreSQL backend configuration."""
        return {
            "host": cls.POSTGRES_HOST,
            "port": cls.POSTGRES_PORT,
            "database": cls.POSTGRES_DB,
            "user": cls.POSTGRES_USER,
            "password": cls.POSTGRES_PASSWORD,
            "min_pool_size": cls.POSTGRES_MIN_POOL_SIZE,
            "max_pool_size": cls.POSTGRES_MAX_POOL_SIZE,
            "ssl": cls.POSTGRES_SSL,
        }


# Global configuration instance
config = StorageConfig()
