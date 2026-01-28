#!/usr/bin/env python3

import logging
import subprocess
import venv
from pathlib import Path

logger = logging.getLogger(__name__)

# Try to import settings, but handle gracefully if not available
try:
    from app.core.settings import settings

    _has_settings = True
except ImportError:
    # Fallback if settings not available (e.g., in standalone scripts)
    _has_settings = False
    _default_index_url = "https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple"


class PythonEnvironmentManager:
    """Manage Python virtual environments and dependencies"""

    def __init__(self, base_dir: str = "/tmp/hexstrike_envs"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(exist_ok=True)

    def create_venv(self, env_name: str) -> Path:
        """Create a new virtual environment"""
        env_path = self.base_dir / env_name
        if not env_path.exists():
            logger.info(f"🐍 Creating virtual environment: {env_name}")
            venv.create(env_path, with_pip=True)
        return env_path

    def install_package(self, env_name: str, package: str) -> bool:
        """Install a package in the specified environment.

        Uses the configured PyPI index URL from settings (default: Tsinghua mirror).
        The index URL can be customized via UV_INDEX_URL or PIP_INDEX_URL environment variable.
        """
        env_path = self.create_venv(env_name)
        pip_path = env_path / "bin" / "pip"

        # Get index URL from settings or use default
        if _has_settings:
            index_url = settings.uv_index_url
        else:
            index_url = _default_index_url

        try:
            # Use --index-url to specify the mirror source
            result = subprocess.run(
                [str(pip_path), "install", "--index-url", index_url, package],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode == 0:
                logger.info(f"📦 Installed package {package} in {env_name} using index {index_url}")
                return True
            else:
                logger.error(f"❌ Failed to install {package}: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"💥 Error installing package {package}: {e}")
            return False

    def get_python_path(self, env_name: str = None) -> str:
        """Get Python executable path for environment.

        If env_name is None or empty, returns system python3.
        """
        if not env_name:
            # Use system python3 when no env specified
            return "python3"
        env_path = self.create_venv(env_name)
        return str(env_path / "bin" / "python")


# Global environment manager
env_manager = PythonEnvironmentManager()
