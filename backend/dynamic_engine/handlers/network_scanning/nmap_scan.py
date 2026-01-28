import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class NmapHandler(AbstractHandler):
    """
    Arbitrary shell command
    """

    def __init__(self, config: Dict):
        super().__init__(config)

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["nmap"]

    def handle(self, data: Dict) -> Any:
        """Execute nmap scan with enhanced logging, caching, and intelligent error handling"""
        try:
            target = data.get("target", "")
            scan_type = data.get("scan_type", "-sCV")
            ports = data.get("ports", "")
            additional_args = data.get("additional_args", "-T4 -Pn")

            if not target:
                logger.warning("🎯 Nmap called without target parameter")
                return {"error": "Target parameter is required"}

            command = f"nmap {scan_type}"

            if ports:
                command += f" -p {ports}"

            if additional_args:
                command += f" {additional_args}"

            command += f" {target}"

            logger.info(f"🔍 Starting Nmap scan: {target}")
            result = execute_command(command)

            logger.info(f"📊 Nmap scan completed for {target}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in nmap endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
