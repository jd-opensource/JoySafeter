import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class RopperHandler(AbstractHandler):
    """Handler for ropper functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["ropper"]

    def handle(self, data: Dict) -> Any:
        """Execute ropper with enhanced logging"""
        try:
            binary = data.get("binary", "")
            gadget_type = data.get("gadget_type", "rop")  # rop, jop, sys, all
            quality = data.get("quality", 1)  # 1-5, higher = better quality
            arch = data.get("arch", "")  # x86, x86_64, arm, etc.
            search_string = data.get("search_string", "")
            additional_args = data.get("additional_args", "")
            if not binary:
                logger.warning("🔧 ropper called without binary parameter")
                return {"error": "Binary parameter is required"}
            command = f"ropper --file {binary}"
            if gadget_type == "rop":
                command += " --rop"
            elif gadget_type == "jop":
                command += " --jop"
            elif gadget_type == "sys":
                command += " --sys"
            elif gadget_type == "all":
                command += " --all"
            if quality > 1:
                command += f" --quality {quality}"
            if arch:
                command += f" --arch {arch}"
            if search_string:
                command += f" --search '{search_string}'"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🔧 Starting ropper analysis: {binary}")
            result = execute_command(command)
            logger.info("📊 ropper analysis completed")
            return result
        except Exception as e:
            logger.error(f"💥 Error in ropper endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
