import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class DnsenumHandler(AbstractHandler):
    """Handler for dnsenum functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["dnsenum"]

    def handle(self, data: Dict) -> Any:
        """Execute dnsenum with enhanced logging"""
        try:
            domain = data.get("domain", "")
            dns_server = data.get("dns_server", "")
            wordlist = data.get("wordlist", "")
            additional_args = data.get("additional_args", "")
            if not domain:
                logger.warning("🌐 DNSenum called without domain parameter")
                return {"error": "Domain parameter is required"}
            command = f"dnsenum {domain}"
            if dns_server:
                command += f" --dnsserver {dns_server}"
            if wordlist:
                command += f" --file {wordlist}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🔍 Starting DNSenum: {domain}")
            result = execute_command(command)
            logger.info(f"📊 DNSenum completed for {domain}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in dnsenum endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
