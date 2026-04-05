#!/usr/bin/env python3
"""
Clear the model_credential and model_instance tables
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.core.settings import settings  # noqa: E402


async def clear_model_tables():
    """Clear the model_credential and model_instance tables"""
    print("🗑️  Clearing model_credential and model_instance tables...")

    engine = create_async_engine(
        settings.database_url,
        echo=False,
    )

    try:
        async with engine.begin() as conn:
            # Get current record counts
            result = await conn.execute(text("SELECT COUNT(*) FROM model_credential"))
            credential_count = result.scalar()

            result = await conn.execute(text("SELECT COUNT(*) FROM model_instance"))
            instance_count = result.scalar()

            print("📊 Current record counts:")
            print(f"   - model_credential: {credential_count} records")
            print(f"   - model_instance: {instance_count} records")

            if credential_count == 0 and instance_count == 0:
                print("ℹ️  Tables are already empty, nothing to clear")
                return

            # Truncate tables (faster than DELETE, resets auto-increment sequences)
            # CASCADE handles foreign key constraints
            await conn.execute(text("TRUNCATE TABLE model_credential CASCADE"))
            print("✅ Cleared model_credential table")

            await conn.execute(text("TRUNCATE TABLE model_instance CASCADE"))
            print("✅ Cleared model_instance table")

            print(f"\n✅ Successfully cleared {credential_count + instance_count} records")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
        raise
    finally:
        await engine.dispose()


async def main():
    """Main function"""
    print("=" * 50)
    print("🔄 Clear model_credential and model_instance tables")
    print("=" * 50)
    print()

    # Check for --force flag
    force = "--force" in sys.argv or "-f" in sys.argv

    if not force:
        # Confirm operation
        print("⚠️  Warning: this will clear all data from the following tables:")
        print("   - model_credential")
        print("   - model_instance")
        print()

        try:
            response = input("Continue? (yes/no): ")
            if response.lower() not in ["yes", "y"]:
                print("❌ Operation cancelled")
                return
        except EOFError:
            print("❌ Non-interactive environment, please use the --force flag")
            print("   Usage: python scripts/clear_model_tables.py --force")
            sys.exit(1)

    try:
        await clear_model_tables()

        print("\n" + "=" * 50)
        print("✅ Operation complete!")
        print("=" * 50)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
