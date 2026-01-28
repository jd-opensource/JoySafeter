import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class ChecksecHandler(AbstractHandler):
    """Handler for checksec functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["checksec"]

    def handle(self, data: Dict) -> Any:
        """Execute checksec with enhanced logging"""
        try:
            binary = data.get("binary", "")
            if not binary:
                logger.warning("🔧 Checksec called without binary parameter")
                return {"error": "Binary parameter is required"}
            command = f"checksec --file={binary}"
            logger.info(f"🔧 Starting Checksec analysis: {binary}")
            result = execute_command(command)
            logger.info(f"📊 Checksec analysis completed for {binary}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in checksec endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
