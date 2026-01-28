#!/usr/bin/env python
"""
Simple server runner script
Handles path setup and starts the FastAPI server
"""

import logging
import os
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

# Also add parent directory so 'backend' module can be imported
parent_dir = backend_dir.parent
sys.path.insert(0, str(parent_dir))

# Set environment variables
os.environ.setdefault("AGENT_HOST", "0.0.0.0")
os.environ.setdefault("AGENT_PORT", "8888")
os.environ.setdefault("AGENT_WORKERS", "1")
os.environ.setdefault("LOG_LEVEL", "INFO")

if __name__ == "__main__":
    import uvicorn

    from app.dynamic_agent.server import app

    logger = logging.getLogger(__name__)

    host = os.getenv("AGENT_HOST", "0.0.0.0")
    port = int(os.getenv("AGENT_PORT", 8888))
    reload = os.getenv("AGENT_RELOAD", "false").lower() == "true"

    logger.info(f"Starting Agent FastAPI Server on {host}:{port}, reload={reload}")
    logger.info(f"API Docs: http://{host}:{port}/docs")

    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=reload,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )
