#!/usr/bin/env python3
"""
Database data cleanup script
Deletes all table data while preserving table structure (for test environment resets)
"""

import os
import sys
from pathlib import Path

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# Ensure sibling modules can be imported
sys.path.insert(0, str(Path(__file__).parent))
from utils import get_db_config, load_env_file, print_db_info, wait_for_db

# Load .env file
env_path = load_env_file()
if env_path:
    print(f"📋 Loaded environment file: {env_path}")


def get_all_tables(conn, schema="public"):
    """Get all table names"""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = %s
        ORDER BY tablename;
    """,
        (schema,),
    )
    tables = [row[0] for row in cursor.fetchall()]
    cursor.close()
    return tables


def truncate_all_tables(conn, schema="public"):
    """Truncate all tables"""
    cursor = conn.cursor()
    tables = get_all_tables(conn, schema)

    if not tables:
        print("ℹ️  No tables in the database")
        cursor.close()
        return True

    print(f"📋 Found {len(tables)} tables")

    try:
        print("🗑️  Truncating table data...")
        table_names = [sql.Identifier(table) for table in tables]
        truncate_sql = sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(sql.SQL(", ").join(table_names))

        cursor.execute(truncate_sql)
        if not conn.isolation_level == ISOLATION_LEVEL_AUTOCOMMIT:
            conn.commit()

        print(f"✅ Successfully truncated {len(tables)} tables")
        cursor.close()
        return True

    except Exception as e:
        print(f"❌ Failed to truncate tables: {e}")
        if not conn.isolation_level == ISOLATION_LEVEL_AUTOCOMMIT:
            conn.rollback()
        cursor.close()
        return False


def clean_database_data(config, schema: str = "public"):
    """Clean database data"""
    try:
        conn = psycopg2.connect(
            host=config["host"],
            port=config["port"],
            user=config["user"],
            password=config["password"],
            database=config["db_name"],
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)

        if not truncate_all_tables(conn, schema):
            return False

        conn.close()
        return True

    except Exception as e:
        print(f"❌ Failed to clean database: {e}")
        return False


def main():
    """Main function"""
    # Get database config
    config = get_db_config()
    schema = os.getenv("POSTGRES_SCHEMA", "public")

    print("=" * 60)
    print("🗑️  Database Data Cleanup")
    print("=" * 60)
    print_db_info(config)
    print(f"Schema: {schema}")
    print("=" * 60)
    print()
    print("⚠️  Warning: this will delete all table data while preserving table structure!")
    print()

    if os.getenv("FORCE_CLEAN") != "true":
        response = input("Continue? (yes/no): ").strip().lower()
        if response not in ["yes", "y"]:
            print("❌ Operation cancelled")
            sys.exit(0)

    if not wait_for_db(config):
        print("❌ Cannot connect to database, cleanup failed")
        sys.exit(1)

    if not clean_database_data(config, schema):
        print("❌ Database cleanup failed")
        sys.exit(1)

    print("=" * 60)
    print("✅ Database data cleanup complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
