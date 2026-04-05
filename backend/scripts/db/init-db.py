#!/usr/bin/env python3
"""
Database initialization script
Waits for the database to be ready, creates it if it doesn't exist, then runs Alembic migrations
"""

import os
import subprocess
import sys
from pathlib import Path

import psycopg2
from psycopg2 import sql

# Ensure sibling modules can be imported
sys.path.insert(0, str(Path(__file__).parent))
from utils import get_db_config, load_env_file, print_db_info, wait_for_db

# Load .env file
env_path = load_env_file()
if env_path:
    print(f"📋 Loaded environment file: {env_path}")


def fix_collation_warning(config):
    """Fix PostgreSQL collation version warning"""
    try:
        conn = psycopg2.connect(
            host=config["host"],
            port=config["port"],
            user=config["user"],
            password=config["password"],
            database=config["db_name"],
        )
        conn.autocommit = True
        cursor = conn.cursor()

        # Update collation version info to suppress the warning
        cursor.execute(
            """
            UPDATE pg_database
            SET datcollversion = NULL
            WHERE datname = %s AND datcollversion IS NOT NULL
        """,
            (config["db_name"],),
        )

        if cursor.rowcount > 0:
            print(f"✅ Fixed collation version warning for database {config['db_name']}")

        cursor.close()
        conn.close()
        return True
    except Exception as e:
        # Ignore errors; don't block the main flow
        print(f"⚠️  Error fixing collation warning (can be ignored): {e}")
        return True


def create_database_if_not_exists(config):
    """Create the database if it doesn't exist"""
    try:
        conn = psycopg2.connect(
            host=config["host"],
            port=config["port"],
            user=config["user"],
            password=config["password"],
            database="postgres",
        )
        conn.autocommit = True
        cursor = conn.cursor()

        db_name = config["db_name"]

        # Check if the database exists
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
        exists = cursor.fetchone()

        if not exists:
            print(f"📦 Creating database: {db_name}")
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))
            print(f"✅ Database created successfully: {db_name}")
        else:
            print(f"✅ Database already exists: {db_name}")
            # If the database already exists, try to fix collation warning
            fix_collation_warning(config)

        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Failed to create database: {e}")
        return False


def run_migrations(config):
    """Run Alembic migrations"""
    print("🚀 Running database migrations...")

    # Auto-detect working directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if "/scripts/db" in script_dir or "\\scripts\\db" in script_dir:
        # Local run: backend/scripts/db/init-db.py -> backend/
        work_dir = os.path.dirname(os.path.dirname(script_dir))
    elif script_dir.startswith("/app"):
        # Running inside Docker container
        work_dir = "/app"
    else:
        # Default to current working directory
        work_dir = os.getcwd()

    print(f"📁 Working directory: {work_dir}")

    # Build sync/async URL for alembic and pass via env
    host = config["host"]
    port = config["port"]
    user = config["user"]
    password = config["password"]
    db_name = config["db_name"]

    sync_url = f"postgresql://{user}:{password}@{host}:{port}/{db_name}"

    env = os.environ.copy()
    env["DATABASE_URL"] = sync_url
    env["POSTGRES_HOST"] = host
    env["POSTGRES_PORT"] = str(port)
    env["POSTGRES_USER"] = user
    env["POSTGRES_PASSWORD"] = password
    env["POSTGRES_DB"] = db_name

    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=work_dir,
        env=env,
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
        return False


def run_skill_loader():
    """Run skill loader script"""
    print("📦 Loading skills...")

    # Auto-detect working directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if "/scripts/db" in script_dir or "\\scripts\\db" in script_dir:
        # Local run: backend/scripts/db/init-db.py -> backend/scripts/load_skills.py
        loader_script = os.path.join(os.path.dirname(script_dir), "load_skills.py")
    elif script_dir.startswith("/app"):
        # Running inside Docker container
        loader_script = "/app/scripts/load_skills.py"
    else:
        # Default fallback
        loader_script = "scripts/load_skills.py"

    if not os.path.exists(loader_script):
        print(f"⚠️  Skill loader script not found: {loader_script}")
        return False

    try:
        # Run with current environment variables
        result = subprocess.run([sys.executable, loader_script], capture_output=True, text=True, env=os.environ.copy())

        if result.returncode == 0:
            print("✅ Skills loaded successfully")
            if result.stdout:
                print(result.stdout)
            return True
        else:
            print("❌ Skills loading failed")
            if result.stderr:
                print(result.stderr)
            print(result.stdout)  # Print stdout for debugging
            return False
    except Exception as e:
        print(f"❌ Error running skill loader script: {e}")
        return False


def main():
    """Main function"""
    # Get database config
    config = get_db_config()

    print("=" * 60)
    print("🚀 Starting database initialization")
    print("=" * 60)
    print_db_info(config)
    print("=" * 60)

    # 1. Wait for database to be ready (connect to postgres database)
    postgres_config = config.copy()
    postgres_config["db_name"] = "postgres"
    if not wait_for_db(postgres_config):
        print("❌ Cannot connect to database, initialization failed")
        sys.exit(1)

    # 2. Create database (if it doesn't exist)
    if not create_database_if_not_exists(config):
        print("❌ Database creation failed, initialization failed")
        sys.exit(1)

    # 3. Run migrations
    if not run_migrations(config):
        print("❌ Database migration failed, initialization failed")
        sys.exit(1)

    # 4. Fix collation warning (optional)
    fix_collation_warning(config)

    # 5. Load Skills
    # run_skill_loader()

    print("=" * 60)
    print("✅ Database initialization complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
