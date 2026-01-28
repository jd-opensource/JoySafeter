import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class TerrascanHandler(AbstractHandler):
    """Handler for terrascan functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["terrascan"]

    def handle(self, data: Dict) -> Any:
        """Execute terrascan with enhanced logging"""
        try:
            scan_type = data.get("scan_type", "all")  # all, terraform, k8s, etc.
            iac_dir = data.get("iac_dir", ".")
            policy_type = data.get("policy_type", "")
            output_format = data.get("output_format", "json")
            severity = data.get("severity", "")
            additional_args = data.get("additional_args", "")
            command = f"terrascan scan -t {scan_type} -d {iac_dir}"
            if policy_type:
                command += f" -p {policy_type}"
            if output_format:
                command += f" -o {output_format}"
            if severity:
                command += f" --severity {severity}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🔍 Starting Terrascan IaC scan: {iac_dir}")
            result = execute_command(command)
            logger.info("📊 Terrascan scan completed")
            return result
        except Exception as e:
            logger.error(f"💥 Error in terrascan endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
