#!/usr/bin/env python3
"""
HexStrike AI - Configuration Module
Centralized configuration management
"""

import importlib.util
import logging
import os
from typing import Any, Callable, Dict, Optional

import yaml

logger = logging.getLogger(__name__)

# API Configuration
API_PORT = int(os.environ.get("PORT", 8888))
API_HOST = os.environ.get("HOST", "127.0.0.1")

# Logging Configuration
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
LOG_FILE = os.environ.get("LOG_FILE", "seclens.log")
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Cache Configuration
CACHE_MAX_SIZE = int(os.environ.get("CACHE_SIZE", 1000))
CACHE_DEFAULT_TTL = int(os.environ.get("CACHE_TTL", 3600))

# Process Pool Configuration
PROCESS_POOL_MIN_WORKERS = int(os.environ.get("MIN_WORKERS", 2))
PROCESS_POOL_MAX_WORKERS = int(os.environ.get("MAX_WORKERS", 20))
PROCESS_POOL_SCALE_THRESHOLD = float(os.environ.get("SCALE_THRESHOLD", 0.8))

# Resource Monitoring
RESOURCE_HISTORY_SIZE = int(os.environ.get("RESOURCE_HISTORY", 100))

# Environment Manager
ENV_BASE_DIR = os.environ.get("ENV_DIR", "/tmp/envs")

# Tool Execution Timeouts (seconds)
DEFAULT_TOOL_TIMEOUT = int(os.environ.get("TOOL_TIMEOUT", 300))
COMMAND_TIMEOUT = int(os.environ.get("COMMAND_TIMEOUT", 300))
LONG_RUNNING_TIMEOUT = int(os.environ.get("LONG_TIMEOUT", 1800))

# Rate Limiting
RATE_LIMIT_REQUESTS = int(os.environ.get("RATE_LIMIT", 100))
RATE_LIMIT_WINDOW = int(os.environ.get("RATE_WINDOW", 60))

# NVD API Configuration
NVD_API_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
NVD_RATE_LIMIT_DELAY = 6  # seconds between requests for unauthenticated access


def get_config() -> Dict[str, Any]:
    """Get all configuration as a dictionary"""
    return {
        "api": {"host": API_HOST, "port": API_PORT},
        "logging": {"level": LOG_LEVEL, "file": LOG_FILE, "format": LOG_FORMAT},
        "cache": {"max_size": CACHE_MAX_SIZE, "default_ttl": CACHE_DEFAULT_TTL},
        "process_pool": {
            "min_workers": PROCESS_POOL_MIN_WORKERS,
            "max_workers": PROCESS_POOL_MAX_WORKERS,
            "scale_threshold": PROCESS_POOL_SCALE_THRESHOLD,
        },
        "timeouts": {"default": DEFAULT_TOOL_TIMEOUT, "long_running": LONG_RUNNING_TIMEOUT},
    }


class ToolOriginConf:
    """Represents a group of related tool files (yaml, md, py)"""

    def __init__(self, base_name: str, base_path: str):
        self.base_name = base_name
        self.base_path = base_path
        self.yaml_file: Optional[str] = None
        self.md_file: Optional[str] = None
        self.py_file: Optional[str] = None
        self.config: Optional[Dict[str, Any]] = None

    def load_config(self) -> bool:
        """Load YAML configuration"""
        if not self.yaml_file:
            logger.warning(f"No YAML config found for {self.base_name}")
            return False

        try:
            with open(self.yaml_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                # YAML files may contain tool name as top-level key
                if isinstance(data, dict) and len(data) == 1:
                    self.config = list(data.values())[0]
                else:
                    self.config = data
                return True
        except Exception as e:
            logger.error(f"Failed to load YAML config for {self.base_name}: {e}")
            return False

    def load_md_content(self) -> Optional[str]:
        """Load MD file content"""
        if not self.md_file or not os.path.exists(self.md_file):
            return None

        try:
            with open(self.md_file, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to load MD file for {self.base_name}: {e}")
            return None

    def load_py_handler(self) -> Optional[Callable]:
        """Load Python handler"""
        if not self.py_file or not os.path.exists(self.py_file):
            return None

        try:
            # Dynamically import Python module
            spec = importlib.util.spec_from_file_location(f"handler_{self.base_name}", self.py_file)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # Find Handler class
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if isinstance(attr, type) and attr_name.endswith("Handler") and attr_name != "AbstractHandler":
                        return attr

                logger.warning(f"No Handler class found in {self.py_file}")
            return None
        except Exception as e:
            logger.error(f"Failed to load Python handler for {self.base_name}: {e}")
            return None

    def __str__(self):
        return f"""<base_path: {self.base_path}>
<base_name: {self.base_name}>
"""
