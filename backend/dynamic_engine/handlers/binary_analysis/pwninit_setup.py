import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class PwninitHandler(AbstractHandler):
    """Handler for pwninit functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["pwninit"]

    def handle(self, data: Dict) -> Any:
        """Execute pwninit with enhanced logging"""
        try:
            binary = data.get("binary", "")
            libc = data.get("libc", "")
            ld = data.get("ld", "")
            template_type = data.get("template_type", "python")  # python, c
            additional_args = data.get("additional_args", "")
            if not binary:
                logger.warning("🔧 pwninit called without binary parameter")
                return {"error": "Binary parameter is required"}
            command = f"pwninit --bin {binary}"
            if libc:
                command += f" --libc {libc}"
            if ld:
                command += f" --ld {ld}"
            if template_type:
                command += f" --template {template_type}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🔧 Starting pwninit setup: {binary}")
            result = execute_command(command)
            logger.info("📊 pwninit setup completed")
            return result
        except Exception as e:
            logger.error(f"💥 Error in pwninit endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
