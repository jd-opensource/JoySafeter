import logging
import os
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class GdbPedaHandler(AbstractHandler):
    """Handler for gdb_peda functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["gdb"]

    def handle(self, data: Dict) -> Any:
        try:
            binary = data.get("binary", "")
            commands = data.get("commands", "")
            attach_pid = data.get("attach_pid", 0)
            core_file = data.get("core_file", "")
            additional_args = data.get("additional_args", "")

            if not binary and not attach_pid and not core_file:
                logger.warning("🔧 GDB-PEDA called without binary, PID, or core file")
                return {"error": "Binary, PID, or core file parameter is required"}

            # Base GDB command with PEDA
            command = "gdb -q"

            if binary:
                command += f" {binary}"

            if core_file:
                command += f" {core_file}"

            if attach_pid:
                command += f" -p {attach_pid}"

            # Create command script
            if commands:
                temp_script = "/tmp/gdb_peda_commands.txt"
                peda_commands = f"""
    source ~/peda/peda.py
    {commands}
    quit
    """
                with open(temp_script, "w") as f:
                    f.write(peda_commands)
                command += f" -x {temp_script}"
            else:
                # Default PEDA initialization
                command += " -ex 'source ~/peda/peda.py' -ex 'quit'"

            if additional_args:
                command += f" {additional_args}"

            target_info = binary or f"PID {attach_pid}" or core_file
            logger.info(f"🔧 Starting GDB-PEDA analysis: {target_info}")
            result = execute_command(command)

            # Cleanup
            if commands and os.path.exists("/tmp/gdb_peda_commands.txt"):
                try:
                    os.remove("/tmp/gdb_peda_commands.txt")
                except Exception:
                    pass

            logger.info("📊 GDB-PEDA analysis completed")
            return result
        except Exception as e:
            logger.error(f"💥 Error in gdb-peda endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
