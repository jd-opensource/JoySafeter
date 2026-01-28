import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class XsserHandler(AbstractHandler):
    """Handler for xsser functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["xsser"]

    def handle(self, data: Dict) -> Any:
        """Execute xsser with enhanced logging"""
        try:
            url = data.get("url", "")
            params_str = data.get("params", "")
            additional_args = data.get("additional_args", "")
            if not url:
                logger.warning("🌐 XSSer called without URL parameter")
                return {"error": "URL parameter is required"}
            command = f"xsser --url '{url}'"
            if params_str:
                command += f" --param='{params_str}'"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🔍 Starting XSSer scan: {url}")
            result = execute_command(command)
            logger.info(f"📊 XSSer scan completed for {url}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in xsser endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
