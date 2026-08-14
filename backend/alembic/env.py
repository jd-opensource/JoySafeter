"""
Alembic environment configuration
"""

import asyncio
from logging.config import fileConfig

from dotenv import load_dotenv
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app.joysafeter_shared.config.settings import ENV_FILE

load_dotenv(ENV_FILE, override=False)

from app.joysafeter_domain import models  # noqa: F401,E402 - register SQLAlchemy models
from app.joysafeter_shared.config.settings import settings  # noqa: E402
from app.joysafeter_shared.database import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# For async migrations, use the async URL; for offline migrations, use the sync URL.
# Set the sync URL here (for offline mode); online mode will use the async URL.
# Escape % → %% for configparser interpolation (URL-encoded passwords contain %)
config.set_main_option("sqlalchemy.url", settings.database_url_sync.replace("%", "%%"))

target_metadata = Base.metadata
AUTOGENERATE_IGNORED_TABLES = {"joysafeter_cluster_members"}


def include_object(object_, name: str | None, type_: str, reflected: bool, compare_to) -> bool:
    if type_ == "table" and name in AUTOGENERATE_IGNORED_TABLES:
        return False
    table = getattr(object_, "table", None)
    if table is not None and table.name in AUTOGENERATE_IGNORED_TABLES:
        return False
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    # For async migrations, use the async database URL directly
    connectable = create_async_engine(
        settings.database_url,
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
