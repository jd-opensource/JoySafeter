import logging
import os
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class Radare2Handler(AbstractHandler):
    """Handler for radare2 functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["r2"]

    def handle(self, data: Dict) -> Any:
        """Execute radare2 with enhanced logging"""
        try:
            binary = data.get("binary", "")
            commands = data.get("commands", "")
            additional_args = data.get("additional_args", "")
            if not binary:
                logger.warning("🔧 Radare2 called without binary parameter")
                return {"error": "Binary parameter is required"}
            if commands:
                temp_script = "/tmp/r2_commands.txt"
                with open(temp_script, "w") as f:
                    f.write(commands)
                command = f"r2 -i {temp_script} -q {binary}"
            else:
                command = f"r2 -q {binary}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🔧 Starting Radare2 analysis: {binary}")
            result = execute_command(command)
            # todo rm files
            if commands and os.path.exists("/tmp/r2_commands.txt"):
                try:
                    os.remove("/tmp/r2_commands.txt")
                except Exception:
                    pass
            logger.info(f"📊 Radare2 analysis completed for {binary}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in radare2 endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
