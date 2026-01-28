#!/usr/bin/env python3
"""
HexStrike AI - Logging Configuration Module
Centralized logging setup with fallback handling
"""

import logging
import sys

from .config import LOG_FILE, LOG_FORMAT, LOG_LEVEL


def setup_logging():
    """Configure logging with fallback for permission issues"""
    try:
        logging.basicConfig(
            level=getattr(logging, LOG_LEVEL.upper()),
            format=LOG_FORMAT,
            handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_FILE)],
        )
    except PermissionError:
        # Fallback to console-only logging if file creation fails
        logging.basicConfig(
            level=getattr(logging, LOG_LEVEL.upper()), format=LOG_FORMAT, handlers=[logging.StreamHandler(sys.stdout)]
        )

    return logging.getLogger(__name__)


# Initialize logger
logger = setup_logging()
