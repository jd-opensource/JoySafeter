import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class FierceHandler(AbstractHandler):
    """Handler for fierce functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["fierce"]

    def handle(self, data: Dict) -> Any:
        """Execute fierce with enhanced logging"""
        try:
            domain = data.get("domain", "")
            dns_server = data.get("dns_server", "")
            additional_args = data.get("additional_args", "")
            if not domain:
                logger.warning("🌐 Fierce called without domain parameter")
                return {"error": "Domain parameter is required"}
            command = f"fierce --domain {domain}"
            if dns_server:
                command += f" --dns-servers {dns_server}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🔍 Starting Fierce DNS recon: {domain}")
            result = execute_command(command)
            logger.info(f"📊 Fierce completed for {domain}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in fierce endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
