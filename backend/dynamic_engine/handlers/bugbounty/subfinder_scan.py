import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class SubfinderHandler(AbstractHandler):
    """Handler for subfinder functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["subfinder"]

    def handle(self, data: Dict) -> Any:
        """Execute subfinder with enhanced logging"""
        try:
            domain = data.get("domain", "")
            silent = data.get("silent", True)
            all_sources = data.get("all_sources", False)
            additional_args = data.get("additional_args", "")
            if not domain:
                logger.warning("🌐 Subfinder called without domain parameter")
                return {"error": "Domain parameter is required"}
            command = f"subfinder -d {domain}"
            if silent:
                command += " -silent"
            if all_sources:
                command += " -all"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🔍 Starting Subfinder: {domain}")
            result = execute_command(command)
            logger.info(f"📊 Subfinder completed for {domain}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in subfinder endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
