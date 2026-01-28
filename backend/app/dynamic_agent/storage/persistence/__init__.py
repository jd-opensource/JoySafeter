"""
Persistence layer for agent storage.

Uses PostgreSQL as the production-ready backend with:
- Synchronous psycopg2 driver (more stable with VPN)
- ThreadPoolExecutor for async compatibility
- JSONB indexing for performance
- Full-text search capabilities
- ACID compliance
"""

# Use psycopg2 driver for VPN stability
from .postgresql_backend import PostgreSQLBackend

__all__ = ["PostgreSQLBackend"]
