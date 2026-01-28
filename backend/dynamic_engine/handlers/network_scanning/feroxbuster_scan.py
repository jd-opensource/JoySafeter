import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class FeroxbusterHandler(AbstractHandler):
    """Handler for feroxbuster functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["feroxbuster"]

    def handle(self, data: Dict) -> Any:
        """Execute feroxbuster with enhanced logging"""
        try:
            url = data.get("url", "")
            wordlist = data.get("wordlist", "/usr/share/wordlists/dirb/common.txt")
            threads = data.get("threads", 10)
            additional_args = data.get("additional_args", "")
            if not url:
                logger.warning("🌐 Feroxbuster called without URL parameter")
                return {"error": "URL parameter is required"}
            command = f"feroxbuster -u {url} -w {wordlist} -t {threads}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🔍 Starting Feroxbuster scan: {url}")
            result = execute_command(command)
            logger.info(f"📊 Feroxbuster scan completed for {url}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in feroxbuster endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
