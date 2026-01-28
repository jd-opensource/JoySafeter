import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class HttpxHandler(AbstractHandler):
    """Handler for httpx functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["httpx"]

    def handle(self, data: Dict) -> Any:
        """Execute httpx with enhanced logging"""
        try:
            target = data.get("target", "")
            probe = data.get("probe", True)
            tech_detect = data.get("tech_detect", False)
            status_code = data.get("status_code", False)
            content_length = data.get("content_length", False)
            title = data.get("title", False)
            web_server = data.get("web_server", False)
            threads = data.get("threads", 50)
            additional_args = data.get("additional_args", "")
            if not target:
                logger.warning("🌐 httpx called without target parameter")
                return {"error": "Target parameter is required"}
            command = f"httpx -l {target} -t {threads}"
            if probe:
                command += " -probe"
            if tech_detect:
                command += " -tech-detect"
            if status_code:
                command += " -sc"
            if content_length:
                command += " -cl"
            if title:
                command += " -title"
            if web_server:
                command += " -server"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🌍 Starting httpx probe: {target}")
            result = execute_command(command)
            logger.info(f"📊 httpx probe completed for {target}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in httpx endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
