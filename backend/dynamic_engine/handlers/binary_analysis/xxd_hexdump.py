import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class XxdHandler(AbstractHandler):
    """Handler for xxd functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["xxd"]

    def handle(self, data: Dict) -> Any:
        """Execute xxd with enhanced logging"""
        try:
            file_path = data.get("file_path", "")
            offset = data.get("offset", "0")
            length = data.get("length", "")
            additional_args = data.get("additional_args", "")
            if not file_path:
                logger.warning("🔧 XXD called without file_path parameter")
                return {"error": "File path parameter is required"}
            command = f"xxd -s {offset}"
            if length:
                command += f" -l {length}"
            if additional_args:
                command += f" {additional_args}"
            command += f" {file_path}"
            logger.info(f"🔧 Starting XXD hex dump: {file_path}")
            result = execute_command(command)
            logger.info(f"📊 XXD hex dump completed for {file_path}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in xxd endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
