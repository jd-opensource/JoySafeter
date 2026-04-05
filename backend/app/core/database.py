"""Database configuration."""

from typing import AsyncGenerator

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .settings import settings

# naming convention
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=convention)


class Base(DeclarativeBase):
    """SQLAlchemy Base"""

    metadata = metadata


# async engine
engine = create_async_engine(
    settings.database_url,
    echo=settings.database_echo,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_pre_ping=True,
    pool_recycle=3600,  # recycle connections after 1 hour
    pool_timeout=30,  # connection acquisition timeout (seconds)
    connect_args={
        "server_settings": {
            "application_name": "agent-platform",
        },
        "command_timeout": 60,  # query timeout (seconds)
        "timeout": 10,  # connection timeout (seconds)
    },
)

# async session factory
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

# Alias: AsyncSessionLocal() is equivalent to async_session_factory()
# async_sessionmaker is callable — calling it returns an AsyncSession
AsyncSessionLocal = async_session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get a database session.

    Convention:
    - This dependency only creates/closes the session and rolls back on exception.
    - Business code must explicitly call commit()/rollback() (or use `async with session.begin():`).
    """
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            # only rollback if still inside a transaction
            if session.in_transaction():
                await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Initialize database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """Close database connections."""
    await engine.dispose()
