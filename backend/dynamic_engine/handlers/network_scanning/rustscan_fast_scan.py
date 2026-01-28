import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class RustscanHandler(AbstractHandler):
    """Handler for rustscan functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["rustscan"]

    def handle(self, data: Dict) -> Any:
        """Execute rustscan with enhanced logging"""
        try:
            target = data.get("target", "")
            ports = data.get("ports", "")
            ulimit = data.get("ulimit", 5000)
            batch_size = data.get("batch_size", 4500)
            timeout = data.get("timeout", 1500)
            scripts = data.get("scripts", "")
            additional_args = data.get("additional_args", "")
            if not target:
                logger.warning("🎯 Rustscan called without target parameter")
                return {"error": "Target parameter is required"}
            command = f"rustscan -a {target} --ulimit {ulimit} -b {batch_size} -t {timeout}"
            if ports:
                command += f" -p {ports}"
            if scripts:
                command += " -- -sC -sV"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"⚡ Starting Rustscan: {target}")
            result = execute_command(command)
            logger.info(f"📊 Rustscan completed for {target}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in rustscan endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
