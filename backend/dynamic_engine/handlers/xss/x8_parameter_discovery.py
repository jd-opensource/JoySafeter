import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class X8Handler(AbstractHandler):
    """Handler for x8 functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["x8"]

    def handle(self, data: Dict) -> Any:
        """Execute x8 with enhanced logging"""
        try:
            url = data.get("url", "")
            wordlist = data.get("wordlist", "/usr/share/wordlists/x8/params.txt")
            method = data.get("method", "GET")
            body = data.get("body", "")
            headers = data.get("headers", "")
            additional_args = data.get("additional_args", "")
            if not url:
                logger.warning("🌐 x8 called without URL parameter")
                return {"error": "URL parameter is required"}
            command = f"x8 -u {url} -w {wordlist} -X {method}"
            if body:
                command += f" -b '{body}'"
            if headers:
                command += f" -H '{headers}'"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🔍 Starting x8 parameter discovery: {url}")
            result = execute_command(command)
            logger.info(f"📊 x8 parameter discovery completed for {url}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in x8 endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
