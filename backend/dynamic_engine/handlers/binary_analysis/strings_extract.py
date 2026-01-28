import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class StringsHandler(AbstractHandler):
    """Handler for strings functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["strings"]

    def handle(self, data: Dict) -> Any:
        """Execute strings with enhanced logging"""
        try:
            file_path = data.get("file_path", "")
            min_len = data.get("min_len", 4)
            additional_args = data.get("additional_args", "")
            if not file_path:
                logger.warning("🔧 Strings called without file_path parameter")
                return {"error": "File path parameter is required"}
            command = f"strings -n {min_len}"
            if additional_args:
                command += f" {additional_args}"
            command += f" {file_path}"
            logger.info(f"🔧 Starting Strings extraction: {file_path}")
            result = execute_command(command)
            logger.info(f"📊 Strings extraction completed for {file_path}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in strings endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
