import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class AmassHandler(AbstractHandler):
    """Handler for amass functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["amass"]

    def handle(self, data: Dict) -> Any:
        """Execute amass with enhanced logging"""
        try:
            domain = data.get("domain", "")
            mode = data.get("mode", "enum")
            additional_args = data.get("additional_args", "")
            if not domain:
                logger.warning("🌐 Amass called without domain parameter")
                return {"error": "Domain parameter is required"}
            command = f"amass {mode}"
            if mode == "enum":
                command += f" -d {domain}"
            else:
                command += f" -d {domain}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🔍 Starting Amass {mode}: {domain}")
            result = execute_command(command)
            logger.info(f"📊 Amass completed for {domain}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in amass endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
