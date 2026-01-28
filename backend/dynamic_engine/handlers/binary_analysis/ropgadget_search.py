import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class RopgadgetHandler(AbstractHandler):
    """Handler for ropgadget functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["ROPgadget"]

    def handle(self, data: Dict) -> Any:
        """Execute ropgadget with enhanced logging"""
        try:
            binary = data.get("binary", "")
            gadget_type = data.get("gadget_type", "")
            additional_args = data.get("additional_args", "")
            if not binary:
                logger.warning("🔧 ROPgadget called without binary parameter")
                return {"error": "Binary parameter is required"}
            command = f"ROPgadget --binary {binary}"
            if gadget_type:
                command += f" --only '{gadget_type}'"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🔧 Starting ROPgadget search: {binary}")
            result = execute_command(command)
            logger.info(f"📊 ROPgadget search completed for {binary}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in ropgadget endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
