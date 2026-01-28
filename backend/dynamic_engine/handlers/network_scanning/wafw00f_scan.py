import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class Wafw00fHandler(AbstractHandler):
    """Handler for wafw00f functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["wafw00f"]

    def handle(self, data: Dict) -> Any:
        """Execute wafw00f with enhanced logging"""
        try:
            target = data.get("target", "")
            additional_args = data.get("additional_args", "")
            if not target:
                logger.warning("🛡️ Wafw00f called without target parameter")
                return {"error": "Target parameter is required"}
            command = f"wafw00f {target}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🛡️ Starting Wafw00f WAF detection: {target}")
            result = execute_command(command)
            logger.info(f"📊 Wafw00f completed for {target}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in wafw00f endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
