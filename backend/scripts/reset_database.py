#!/usr/bin/env python3
"""
Database reset script
Drops all tables and re-initializes the database
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app import models  # noqa: F401, E402 - Ensure all models are imported
from app.core.settings import settings  # noqa: E402


async def drop_all_tables():
    """Drop all tables"""
    print("🗑️  Dropping all tables...")

    # Use sync URL for DDL operations
    engine = create_async_engine(
        settings.database_url,
        echo=False,
    )

    async with engine.begin() as conn:
        # Disable FK checks (PostgreSQL uses CASCADE)
        await conn.execute(text("SET session_replication_role = 'replica';"))

        # Get all table names
        result = await conn.execute(
            text("""
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
        """)
        )
        tables = [row[0] for row in result.fetchall()]

        if tables:
            print(f"📋 Found {len(tables)} tables: {', '.join(tables)}")
            # Drop all tables (CASCADE handles foreign keys automatically)
            for table in tables:
                await conn.execute(text(f'DROP TABLE IF EXISTS "{table}" CASCADE;'))
            print(f"✅ Dropped {len(tables)} tables")
        else:
            print("ℹ️  No tables in the database")

        # Drop all enum types
        result = await conn.execute(
            text("""
            SELECT typname
            FROM pg_type
            WHERE typtype = 'e'
            AND typnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
        """)
        )
        enums = [row[0] for row in result.fetchall()]

        if enums:
            print(f"📋 Found {len(enums)} enum types: {', '.join(enums)}")
            for enum in enums:
                await conn.execute(text(f'DROP TYPE IF EXISTS "{enum}" CASCADE;'))
            print(f"✅ Dropped {len(enums)} enum types")

        # Re-enable FK checks
        await conn.execute(text("SET session_replication_role = 'origin';"))

    await engine.dispose()
    print("✅ Database cleanup complete")


async def run_migrations():
    """Run database migrations"""
    print("\n🚀 Running database migrations...")

    import subprocess

    # Set working directory
    work_dir = project_root

    # Run alembic upgrade head
    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=work_dir,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        print("✅ Database migrations complete")
        if result.stdout:
            print(result.stdout)
        return True
    else:
        print("❌ Database migrations failed")
        if result.stderr:
            print(result.stderr)
        if result.stdout:
            print(result.stdout)
        return False


async def main():
    """Main function"""
    import sys

    print("=" * 50)
    print("🔄 Reset database (drop + rebuild)")
    print("=" * 50)
    print()

    # Check for --force flag
    force = "--force" in sys.argv or "-f" in sys.argv

    if not force:
        # Confirm operation
        print("⚠️  Warning: this will:")
        print("   1. Drop all tables and data")
        print("   2. Drop all enum types")
        print("   3. Re-run database migrations")
        print()

        try:
            response = input("Continue? (yes/no): ")
            if response.lower() not in ["yes", "y"]:
                print("❌ Operation cancelled")
                return
        except EOFError:
            print("❌ Non-interactive environment, please use the --force flag")
            print("   Usage: python scripts/reset_database.py --force")
            sys.exit(1)

    try:
        # 1. Drop all tables
        await drop_all_tables()

        # 2. Run migrations
        success = await run_migrations()

        if success:
            print("\n" + "=" * 50)
            print("✅ Database reset complete!")
            print("=" * 50)
        else:
            print("\n" + "=" * 50)
            print("❌ Database reset failed, please check errors above")
            print("=" * 50)
            sys.exit(1)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
