import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class OneGadgetHandler(AbstractHandler):
    """Handler for one_gadget functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["one_gadget"]

    def handle(self, data: Dict) -> Any:
        """Execute one_gadget with enhanced logging"""
        try:
            libc_path = data.get("libc_path", "")
            level = data.get("level", 1)  # 0, 1, 2 for different constraint levels
            additional_args = data.get("additional_args", "")
            if not libc_path:
                logger.warning("🔧 one_gadget called without libc_path parameter")
                return {"error": "libc_path parameter is required"}
            command = f"one_gadget {libc_path} --level {level}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🔧 Starting one_gadget analysis: {libc_path}")
            result = execute_command(command)
            logger.info("📊 one_gadget analysis completed")
            return result
        except Exception as e:
            logger.error(f"💥 Error in one_gadget endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
