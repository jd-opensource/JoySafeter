import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class NmapAdvancedHandler(AbstractHandler):
    """Handler for nmap_advanced functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["nmap"]

    def handle(self, data: Dict) -> Any:
        """Execute nmap_advanced with enhanced logging"""
        try:
            target = data.get("target", "")
            scan_type = data.get("scan_type", "-sS")
            ports = data.get("ports", "")
            timing = data.get("timing", "T4")
            nse_scripts = data.get("nse_scripts", "")
            os_detection = data.get("os_detection", False)
            version_detection = data.get("version_detection", False)
            aggressive = data.get("aggressive", False)
            stealth = data.get("stealth", False)
            additional_args = data.get("additional_args", "")
            if not target:
                logger.warning("🎯 Advanced Nmap called without target parameter")
                return {"error": "Target parameter is required"}
            command = f"nmap {scan_type} {target}"
            if ports:
                command += f" -p {ports}"
            if stealth:
                command += " -T2 -f --mtu 24"
            else:
                command += f" -{timing}"
            if os_detection:
                command += " -O"
            if version_detection:
                command += " -sV"
            if aggressive:
                command += " -A"
            if nse_scripts:
                command += f" --script={nse_scripts}"
            elif not aggressive:
                command += " --script=default,discovery,safe"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🔍 Starting Advanced Nmap: {target}")
            result = execute_command(command)
            logger.info(f"📊 Advanced Nmap completed for {target}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in advanced nmap endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
