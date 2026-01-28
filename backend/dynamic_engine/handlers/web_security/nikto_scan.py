import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class NiktoHandler(AbstractHandler):
    """Handler for nikto functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["nikto"]

    def handle(self, data: Dict) -> Any:
        """Execute nikto with enhanced logging"""
        try:
            target = data.get("target", "")
            additional_args = data.get("additional_args", "")
            if not target:
                logger.warning("🎯 Nikto called without target parameter")
                return {"error": "Target parameter is required"}
            command = f"nikto -h {target}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🔬 Starting Nikto scan: {target}")
            result = execute_command(command)
            logger.info(f"📊 Nikto scan completed for {target}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in nikto endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
