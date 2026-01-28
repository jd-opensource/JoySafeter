import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class ResponderHandler(AbstractHandler):
    """Handler for responder functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["responder"]

    def handle(self, data: Dict) -> Any:
        """Execute responder with enhanced logging"""
        try:
            interface = data.get("interface", "eth0")
            analyze = data.get("analyze", False)
            wpad = data.get("wpad", True)
            force_wpad_auth = data.get("force_wpad_auth", False)
            fingerprint = data.get("fingerprint", False)
            duration = data.get("duration", 300)  # 5 minutes default
            additional_args = data.get("additional_args", "")
            if not interface:
                logger.warning("🎯 Responder called without interface parameter")
                return {"error": "Interface parameter is required"}
            command = f"timeout {duration} responder -I {interface}"
            if analyze:
                command += " -A"
            if wpad:
                command += " -w"
            if force_wpad_auth:
                command += " -F"
            if fingerprint:
                command += " -f"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🔍 Starting Responder on interface: {interface}")
            result = execute_command(command)
            logger.info("📊 Responder completed")
            return result
        except Exception as e:
            logger.error(f"💥 Error in responder endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
