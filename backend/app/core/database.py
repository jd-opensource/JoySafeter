"""
数据库配置
"""

from typing import AsyncGenerator

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .settings import settings

# 命名约定
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


# 创建异步引擎
engine = create_async_engine(
    settings.database_url,
    echo=settings.database_echo,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_pre_ping=True,
    pool_recycle=3600,  # 1小时后回收连接
    pool_timeout=30,  # 获取连接超时时间（秒）
    connect_args={
        "server_settings": {
            "application_name": "agent-platform",
        },
        "command_timeout": 60,  # 命令超时时间（秒）
        "timeout": 10,  # 连接超时时间（秒）
    },
)

# 创建异步会话工厂
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

# 向后兼容别名：旧代码使用 AsyncSessionLocal()
# async_sessionmaker 本身是可调用的，调用后返回 AsyncSession
AsyncSessionLocal = async_session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """获取数据库会话

    统一规范（推荐）：
    - 依赖只负责创建/关闭会话，以及在异常时回滚；
    - 业务代码对“写操作”显式调用 commit()/rollback()（或使用 `async with session.begin():`）。

    说明：此前这里会在请求结束时自动 commit，容易造成事务边界不清晰、读请求也产生无意义的 commit。
    """
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            # 若业务层已显式 commit，则可能不在事务中；此处仅在有事务时回滚
            if session.in_transaction():
                await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """初始化数据库表"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """关闭数据库连接"""
    await engine.dispose()
