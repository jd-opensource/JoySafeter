import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.utils.python_env import env_manager

logger = logging.getLogger(__name__)


class InstallPythonPackageHandler(AbstractHandler):
    """Handler for install_python_package functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    # todo
    def handle(self, data: Dict) -> Any:
        """Execute install_python_package with enhanced logging"""
        try:
            package = data.get("package", "")
            env_name = data.get("env_name", "default")
            if not package:
                return {"error": "Package name is required"}
            logger.info(f"📦 Installing Python package: {package} in env {env_name}")
            success = env_manager.install_package(env_name, package)
            if success:
                return {"success": True, "message": f"Package {package} installed successfully", "env_name": env_name}
            else:
                return {"success": False, "error": f"Failed to install package {package}"}
        except Exception as e:
            logger.error(f"💥 Error installing Python package: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
