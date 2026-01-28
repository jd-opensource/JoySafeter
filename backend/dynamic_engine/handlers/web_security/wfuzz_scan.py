import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class WfuzzHandler(AbstractHandler):
    """Handler for wfuzz functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["wfuzz"]

    def handle(self, data: Dict) -> Any:
        """Execute wfuzz with enhanced logging"""
        try:
            url = data.get("url", "")
            wordlist = data.get("wordlist", "/usr/share/wordlists/dirb/common.txt")
            additional_args = data.get("additional_args", "")
            if not url:
                logger.warning("🌐 Wfuzz called without URL parameter")
                return {"error": "URL parameter is required"}
            command = f"wfuzz -w {wordlist} '{url}'"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🔍 Starting Wfuzz scan: {url}")
            result = execute_command(command)
            logger.info(f"📊 Wfuzz scan completed for {url}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in wfuzz endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
