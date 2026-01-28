import logging
import os
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class MetasploitHandler(AbstractHandler):
    """Handler for metasploit functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["msfconsole"]

    def handle(self, data: Dict) -> Any:
        """Execute metasploit with enhanced logging"""
        try:
            module = data.get("module", "")
            options = data.get("options", {})
            if not module:
                logger.warning("🚀 Metasploit called without module parameter")
                return {"error": "Module parameter is required"}
            resource_content = f"use {module}\n"
            for key, value in options.items():
                resource_content += f"set {key} {value}\n"
            resource_content += "exploit\n"
            resource_file = "/tmp/mcp_msf_resource.rc"
            with open(resource_file, "w") as f:
                f.write(resource_content)
            command = f"msfconsole -q -r {resource_file}"
            logger.info(f"🚀 Starting Metasploit module: {module}")
            result = execute_command(command)
            try:
                os.remove(resource_file)
            except Exception as e:
                logger.warning(f"Error removing temporary resource file: {str(e)}")
            logger.info(f"📊 Metasploit module completed: {module}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in metasploit endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
