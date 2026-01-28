import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class CloudmapperHandler(AbstractHandler):
    """Handler for cloudmapper functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["cloudmapper"]

    def handle(self, data: Dict) -> Any:
        """Execute cloudmapper with enhanced logging"""
        try:
            action = data.get("action", "collect")  # collect, prepare, webserver, find_admins, etc.
            account = data.get("account", "")
            config = data.get("config", "config.json")
            additional_args = data.get("additional_args", "")
            if not account and action != "webserver":
                logger.warning("☁️  CloudMapper called without account parameter")
                return {"error": "Account parameter is required for most actions"}
            command = f"cloudmapper {action}"
            if account:
                command += f" --account {account}"
            if config:
                command += f" --config {config}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"☁️  Starting CloudMapper {action}")
            result = execute_command(command)
            logger.info(f"📊 CloudMapper {action} completed")
            return result
        except Exception as e:
            logger.error(f"💥 Error in cloudmapper endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
