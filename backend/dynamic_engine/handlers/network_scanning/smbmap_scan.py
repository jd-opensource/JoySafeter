import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class SmbmapHandler(AbstractHandler):
    """Handler for smbmap functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["smbmap"]

    def handle(self, data: Dict) -> Any:
        """Execute smbmap with enhanced logging"""
        try:
            target = data.get("target", "")
            username = data.get("username", "")
            password = data.get("password", "")
            domain = data.get("domain", "")
            additional_args = data.get("additional_args", "")
            if not target:
                logger.warning("🎯 SMBMap called without target parameter")
                return {"error": "Target parameter is required"}
            command = f"smbmap -H {target}"
            if username:
                command += f" -u {username}"
            if password:
                command += f" -p {password}"
            if domain:
                command += f" -d {domain}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🔍 Starting SMBMap: {target}")
            result = execute_command(command)
            logger.info(f"📊 SMBMap completed for {target}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in smbmap endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
