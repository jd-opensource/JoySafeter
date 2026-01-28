import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class ArpScanHandler(AbstractHandler):
    """Handler for arp_scan functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["arp-scan"]

    def handle(self, data: Dict) -> Any:
        """Execute arp_scan with enhanced logging"""
        try:
            target = data.get("target", "")
            interface = data.get("interface", "")
            local_network = data.get("local_network", False)
            timeout = data.get("timeout", 500)
            retry = data.get("retry", 3)
            additional_args = data.get("additional_args", "")
            if not target and not local_network:
                logger.warning("🎯 arp-scan called without target parameter")
                return {"error": "Target parameter or local_network flag is required"}
            command = f"arp-scan -t {timeout} -r {retry}"
            if interface:
                command += f" -I {interface}"
            if local_network:
                command += " -l"
            else:
                command += f" {target}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🔍 Starting arp-scan: {target if target else 'local network'}")
            result = execute_command(command)
            logger.info("📊 arp-scan completed")
            return result
        except Exception as e:
            logger.error(f"💥 Error in arp-scan endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
