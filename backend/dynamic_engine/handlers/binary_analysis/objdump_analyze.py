import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class ObjdumpHandler(AbstractHandler):
    """Handler for objdump functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["objdump"]

    def handle(self, data: Dict) -> Any:
        """Execute objdump with enhanced logging"""
        try:
            binary = data.get("binary", "")
            disassemble = data.get("disassemble", True)
            additional_args = data.get("additional_args", "")
            if not binary:
                logger.warning("🔧 Objdump called without binary parameter")
                return {"error": "Binary parameter is required"}
            command = "objdump"
            if disassemble:
                command += " -d"
            else:
                command += " -x"
            if additional_args:
                command += f" {additional_args}"
            command += f" {binary}"
            logger.info(f"🔧 Starting Objdump analysis: {binary}")
            result = execute_command(command)
            logger.info(f"📊 Objdump analysis completed for {binary}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in objdump endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
