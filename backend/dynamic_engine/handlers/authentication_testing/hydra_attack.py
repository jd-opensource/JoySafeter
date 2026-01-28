import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class HydraHandler(AbstractHandler):
    """Handler for hydra functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["hydra"]

    def handle(self, data: Dict) -> Any:
        """Execute hydra with enhanced logging"""
        try:
            target = data.get("target", "")
            service = data.get("service", "")
            username = data.get("username", "")
            username_file = data.get("username_file", "")
            password = data.get("password", "")
            password_file = data.get("password_file", "")
            additional_args = data.get("additional_args", "")
            if not target or not service:
                logger.warning("🎯 Hydra called without target or service parameter")
                return {"error": "Target and service parameters are required"}
            if not (username or username_file) or not (password or password_file):
                logger.warning("🔑 Hydra called without username/password parameters")
                return {"error": "Username/username_file and password/password_file are required"}
            command = "hydra -t 4"
            if username:
                command += f" -l {username}"
            elif username_file:
                command += f" -L {username_file}"
            if password:
                command += f" -p {password}"
            elif password_file:
                command += f" -P {password_file}"
            if additional_args:
                command += f" {additional_args}"
            command += f" {target} {service}"
            logger.info(f"🔑 Starting Hydra attack: {target}:{service}")
            result = execute_command(command)
            logger.info(f"📊 Hydra attack completed for {target}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in hydra endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
