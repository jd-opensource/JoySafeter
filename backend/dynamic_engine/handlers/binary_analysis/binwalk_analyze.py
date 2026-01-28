import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class BinwalkHandler(AbstractHandler):
    """Handler for binwalk functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["binwalk"]

    def handle(self, data: Dict) -> Any:
        """Execute binwalk with enhanced logging"""
        try:
            file_path = data.get("file_path", "")
            extract = data.get("extract", False)
            additional_args = data.get("additional_args", "")
            if not file_path:
                logger.warning("🔧 Binwalk called without file_path parameter")
                return {"error": "File path parameter is required"}
            command = "binwalk"
            if extract:
                command += " -e"
            if additional_args:
                command += f" {additional_args}"
            command += f" {file_path}"
            logger.info(f"🔧 Starting Binwalk analysis: {file_path}")
            result = execute_command(command)
            logger.info(f"📊 Binwalk analysis completed for {file_path}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in binwalk endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
