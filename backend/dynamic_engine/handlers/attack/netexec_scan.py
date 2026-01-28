import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class NetexecHandler(AbstractHandler):
    """Handler for netexec functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["nxc"]

    def handle(self, data: Dict) -> Any:
        """Execute netexec with enhanced logging"""
        try:
            target = data.get("target", "")
            protocol = data.get("protocol", "smb")
            username = data.get("username", "")
            password = data.get("password", "")
            hash_value = data.get("hash", "")
            module = data.get("module", "")
            additional_args = data.get("additional_args", "")
            if not target:
                logger.warning("🎯 NetExec called without target parameter")
                return {"error": "Target parameter is required"}
            command = f"nxc {protocol} {target}"
            if username:
                command += f" -u {username}"
            if password:
                command += f" -p {password}"
            if hash_value:
                command += f" -H {hash_value}"
            if module:
                command += f" -M {module}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🔍 Starting NetExec {protocol} scan: {target}")
            result = execute_command(command)
            logger.info(f"📊 NetExec scan completed for {target}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in netexec endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
