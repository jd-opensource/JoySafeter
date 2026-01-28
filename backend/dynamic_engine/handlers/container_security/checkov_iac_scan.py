import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class CheckovHandler(AbstractHandler):
    """Handler for checkov functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["checkov"]

    def handle(self, data: Dict) -> Any:
        """Execute checkov with enhanced logging"""
        try:
            directory = data.get("directory", ".")
            framework = data.get("framework", "")  # terraform, cloudformation, kubernetes, etc.
            check = data.get("check", "")
            skip_check = data.get("skip_check", "")
            output_format = data.get("output_format", "json")
            additional_args = data.get("additional_args", "")
            command = f"checkov -d {directory}"
            if framework:
                command += f" --framework {framework}"
            if check:
                command += f" --check {check}"
            if skip_check:
                command += f" --skip-check {skip_check}"
            if output_format:
                command += f" --output {output_format}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🔍 Starting Checkov IaC scan: {directory}")
            result = execute_command(command)
            logger.info("📊 Checkov scan completed")
            return result
        except Exception as e:
            logger.error(f"💥 Error in checkov endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
