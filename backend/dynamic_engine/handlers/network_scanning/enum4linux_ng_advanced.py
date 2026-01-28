import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class Enum4linuxNgHandler(AbstractHandler):
    """Handler for enum4linux_ng functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["enum4linux-ng"]

    def handle(self, data: Dict) -> Any:
        """Execute enum4linux_ng with enhanced logging"""
        try:
            target = data.get("target", "")
            username = data.get("username", "")
            password = data.get("password", "")
            domain = data.get("domain", "")
            shares = data.get("shares", True)
            users = data.get("users", True)
            groups = data.get("groups", True)
            policy = data.get("policy", True)
            additional_args = data.get("additional_args", "")
            if not target:
                logger.warning("🎯 Enum4linux-ng called without target parameter")
                return {"error": "Target parameter is required"}
            command = f"enum4linux-ng {target}"
            if username:
                command += f" -u {username}"
            if password:
                command += f" -p {password}"
            if domain:
                command += f" -d {domain}"
            enum_options = []
            if shares:
                enum_options.append("S")
            if users:
                enum_options.append("U")
            if groups:
                enum_options.append("G")
            if policy:
                enum_options.append("P")
            if enum_options:
                command += f" -A {','.join(enum_options)}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🔍 Starting Enum4linux-ng: {target}")
            result = execute_command(command)
            logger.info(f"📊 Enum4linux-ng completed for {target}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in enum4linux-ng endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
