import logging
import os
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class GdbHandler(AbstractHandler):
    """Handler for gdb functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["gdb"]

    def handle(self, data: Dict) -> Any:
        """Execute gdb with enhanced logging"""
        try:
            binary = data.get("binary", "")
            commands = data.get("commands", "")
            script_file = data.get("script_file", "")
            additional_args = data.get("additional_args", "")
            if not binary:
                logger.warning("🔧 GDB called without binary parameter")
                return {"error": "Binary parameter is required"}
            command = f"gdb {binary}"
            if script_file:
                command += f" -x {script_file}"
            if commands:
                temp_script = "/tmp/gdb_commands.txt"
                with open(temp_script, "w") as f:
                    f.write(commands)
                command += f" -x {temp_script}"
            if additional_args:
                command += f" {additional_args}"
            command += " -batch"
            logger.info(f"🔧 Starting GDB analysis: {binary}")
            result = execute_command(command)
            if commands and os.path.exists("/tmp/gdb_commands.txt"):
                try:
                    os.remove("/tmp/gdb_commands.txt")
                except Exception:
                    pass
            logger.info(f"📊 GDB analysis completed for {binary}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in gdb endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
