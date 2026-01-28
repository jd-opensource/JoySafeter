import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class DotdotpwnHandler(AbstractHandler):
    """Handler for dotdotpwn functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["dotdotpwn"]

    def handle(self, data: Dict) -> Any:
        """Execute dotdotpwn with enhanced logging"""
        try:
            target = data.get("target", "")
            module = data.get("module", "http")
            additional_args = data.get("additional_args", "")
            if not target:
                logger.warning("🎯 DotDotPwn called without target parameter")
                return {"error": "Target parameter is required"}
            command = f"dotdotpwn -m {module} -h {target}"
            if additional_args:
                command += f" {additional_args}"
            command += " -b"
            logger.info(f"🔍 Starting DotDotPwn scan: {target}")
            result = execute_command(command)
            logger.info(f"📊 DotDotPwn scan completed for {target}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in dotdotpwn endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
