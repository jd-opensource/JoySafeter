import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class WpscanHandler(AbstractHandler):
    """Handler for wpscan functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["wpscan"]

    def handle(self, data: Dict) -> Any:
        """Execute wpscan with enhanced logging"""
        try:
            url = data.get("url", "")
            additional_args = data.get("additional_args", "")
            if not url:
                logger.warning("🌐 WPScan called without URL parameter")
                return {"error": "URL parameter is required"}
            command = f"wpscan --url {url}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🔍 Starting WPScan: {url}")
            result = execute_command(command)
            logger.info(f"📊 WPScan completed for {url}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in wpscan endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
