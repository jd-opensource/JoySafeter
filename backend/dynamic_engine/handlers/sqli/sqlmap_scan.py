import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class SqlmapHandler(AbstractHandler):
    """Handler for sqlmap functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["sqlmap"]

    def handle(self, data: Dict) -> Any:
        """Execute sqlmap with enhanced logging"""
        try:
            url = data.get("url", "")
            post_data = data.get("data", "")
            additional_args = data.get("additional_args", "")
            if not url:
                logger.warning("🎯 SQLMap called without URL parameter")
                return {"error": "URL parameter is required"}
            command = f"sqlmap -u {url} --batch"
            if post_data:
                command += f' --data="{post_data}"'
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"💉 Starting SQLMap scan: {url}")
            result = execute_command(command)
            logger.info(f"📊 SQLMap scan completed for {url}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in sqlmap endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
