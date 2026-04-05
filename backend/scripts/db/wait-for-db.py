#!/usr/bin/env python3
"""
Python script to wait for database readiness.
Used in Docker containers to wait for the database service to become available.
"""

import sys
from pathlib import Path

# Ensure sibling modules can be imported
sys.path.insert(0, str(Path(__file__).parent))
from utils import get_db_config, load_env_file, wait_for_db

# Load .env file
env_path = load_env_file()
if env_path:
    print(f"📋 Loaded environment file: {env_path}")


if __name__ == "__main__":
    # Get database config and wait for connection
    config = get_db_config()

    if not wait_for_db(config):
        sys.exit(1)
