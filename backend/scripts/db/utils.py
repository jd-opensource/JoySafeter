#!/usr/bin/env python3
"""
Database script utility module
Provides unified database config retrieval and connection waiting functions
"""

import os
import sys
import time
from typing import Optional, TypedDict

import psycopg2
from psycopg2 import OperationalError


class DBConfig(TypedDict):
    """Database config type"""

    user: str
    password: str
    host: str
    port: int
    db_name: str


def load_env_file() -> Optional[str]:
    """
    Load .env file.
    Returns the loaded file path, or None if not loaded.
    """
    try:
        from dotenv import load_dotenv

        # Auto-detect .env file location
        script_dir = os.path.dirname(os.path.abspath(__file__))
        env_paths = [
            os.path.join(script_dir, "../../.env"),  # backend/.env
            "/app/.env",  # Inside Docker container
            ".env",  # Current directory
        ]

        for env_path in env_paths:
            if os.path.exists(env_path):
                load_dotenv(env_path, override=False)
                return env_path
    except ImportError:
        pass

    return None


def get_db_config(require_all: bool = True) -> DBConfig:
    """
    Get database config from environment variables.

    Builds config from POSTGRES_* environment variables.

    Args:
        require_all: Whether all config items must be present; exits on error if missing.

    Returns:
        DBConfig: Database config dictionary
    """
    # Get config from individual environment variables
    is_in_container = os.path.exists("/app")

    if is_in_container:
        host = os.getenv("POSTGRES_HOST", "db")
        port = int(os.getenv("POSTGRES_PORT", "5432"))
    else:
        host = os.getenv("POSTGRES_HOST", "localhost")
        # Local run: prefer POSTGRES_PORT_HOST (Docker mapped port)
        port = int(os.getenv("POSTGRES_PORT_HOST") or os.getenv("POSTGRES_PORT", "5432"))

    # Auto-correct when running locally with container hostname
    if (not is_in_container) and host == "db":
        print("⚠️  Running locally but POSTGRES_HOST=db, auto-switching to localhost")
        host = "localhost"

    user = os.getenv("POSTGRES_USER")
    password = os.getenv("POSTGRES_PASSWORD")
    db_name = os.getenv("POSTGRES_DB")

    # Check that required config is present
    if require_all:
        missing = []
        if not user:
            missing.append("POSTGRES_USER")
        if not password:
            missing.append("POSTGRES_PASSWORD")
        if not db_name:
            missing.append("POSTGRES_DB")

        if missing:
            print(f"❌ Error: the following environment variables are not set: {', '.join(missing)}")
            print("   Please configure database settings in backend/.env")
            sys.exit(1)

    return DBConfig(
        user=user or "",
        password=password or "",
        host=host,
        port=port,
        db_name=db_name or "",
    )


def wait_for_db(
    config: Optional[DBConfig] = None,
    max_retries: int = 30,
    retry_interval: int = 2,
) -> bool:
    """
    Wait for the database connection to become available.

    Args:
        config: Database config; auto-fetched if None.
        max_retries: Maximum number of retries.
        retry_interval: Retry interval in seconds.

    Returns:
        bool: Whether the connection succeeded.
    """
    if config is None:
        config = get_db_config()

    host = config["host"]
    port = config["port"]
    user = config["user"]
    password = config["password"]
    database = config["db_name"]

    print(f"🔍 Waiting for database to be ready ({host}:{port})...")

    for i in range(max_retries):
        try:
            conn = psycopg2.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
                connect_timeout=5,
            )
            conn.close()
            print("✅ Database is ready")
            return True
        except OperationalError as e:
            if i < max_retries - 1:
                print(f"⏳ Attempt {i + 1}/{max_retries}: database not ready, waiting...")
                time.sleep(retry_interval)
            else:
                print(f"❌ Database connection failed: {e}")
                return False

    return False


def print_db_info(config: DBConfig) -> None:
    """Print database config info (password hidden)"""
    print(f"Database host: {config['host']}:{config['port']}")
    print(f"Database user: {config['user']}")
    print(f"Database name: {config['db_name']}")
