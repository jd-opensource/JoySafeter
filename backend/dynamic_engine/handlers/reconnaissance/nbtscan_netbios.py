import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class NbtscanHandler(AbstractHandler):
    """Handler for nbtscan functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["nbtscan"]

    def handle(self, data: Dict) -> Any:
        """Execute nbtscan with enhanced logging"""
        try:
            target = data.get("target", "")
            verbose = data.get("verbose", False)
            timeout = data.get("timeout", 2)
            additional_args = data.get("additional_args", "")
            if not target:
                logger.warning("🎯 nbtscan called without target parameter")
                return {"error": "Target parameter is required"}
            command = f"nbtscan -t {timeout}"
            if verbose:
                command += " -v"
            command += f" {target}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🔍 Starting nbtscan: {target}")
            result = execute_command(command)
            logger.info(f"📊 nbtscan completed for {target}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in nbtscan endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
