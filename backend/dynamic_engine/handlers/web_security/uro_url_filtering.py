import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class UroHandler(AbstractHandler):
    """Handler for uro functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["uro"]

    def handle(self, data: Dict) -> Any:
        """Execute uro with enhanced logging"""
        try:
            urls = data.get("urls", "")
            whitelist = data.get("whitelist", "")
            blacklist = data.get("blacklist", "")
            additional_args = data.get("additional_args", "")
            if not urls:
                logger.warning("🌐 uro called without URLs")
                return {"error": "URLs parameter is required"}
            command = f"echo '{urls}' | uro"
            if whitelist:
                command += f" --whitelist {whitelist}"
            if blacklist:
                command += f" --blacklist {blacklist}"
            if additional_args:
                command += f" {additional_args}"
            logger.info("🔍 Starting uro URL filtering")
            result = execute_command(command)
            logger.info("📊 uro URL filtering completed")
            return result
        except Exception as e:
            logger.error(f"💥 Error in uro endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
