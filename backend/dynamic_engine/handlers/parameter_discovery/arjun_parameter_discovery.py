import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class ArjunHandler(AbstractHandler):
    """Handler for arjun functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["arjun"]

    def handle(self, data: Dict) -> Any:
        """Execute arjun with enhanced logging"""
        try:
            url = data.get("url", "")
            method = data.get("method", "GET")
            wordlist = data.get("wordlist", "")
            delay = data.get("delay", 0)
            threads = data.get("threads", 25)
            stable = data.get("stable", False)
            additional_args = data.get("additional_args", "")
            if not url:
                logger.warning("🌐 Arjun called without URL parameter")
                return {"error": "URL parameter is required"}
            command = f"arjun -u {url} -m {method} -t {threads}"
            if wordlist:
                command += f" -w {wordlist}"
            if delay > 0:
                command += f" -d {delay}"
            if stable:
                command += " --stable"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🎯 Starting Arjun parameter discovery: {url}")
            result = execute_command(command)
            logger.info(f"📊 Arjun parameter discovery completed for {url}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in arjun endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
