import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class Enum4linuxHandler(AbstractHandler):
    """Handler for enum4linux functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["enum4linux"]

    def handle(self, data: Dict) -> Any:
        """Execute enum4linux with enhanced logging"""
        try:
            target = data.get("target", "")
            additional_args = data.get("additional_args", "-a")
            if not target:
                logger.warning("🎯 Enum4linux called without target parameter")
                return {"error": "Target parameter is required"}
            command = f"enum4linux {additional_args} {target}"
            logger.info(f"🔍 Starting Enum4linux: {target}")
            result = execute_command(command)
            logger.info(f"📊 Enum4linux completed for {target}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in enum4linux endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
