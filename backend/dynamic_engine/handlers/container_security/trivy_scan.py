import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class TrivyHandler(AbstractHandler):
    """Handler for trivy functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["trivy"]

    def handle(self, data: Dict) -> Any:
        """Execute trivy with enhanced logging"""
        try:
            scan_type = data.get("scan_type", "image")  # image, fs, repo
            target = data.get("target", "")
            output_format = data.get("output_format", "json")
            severity = data.get("severity", "")
            output_file = data.get("output_file", "")
            additional_args = data.get("additional_args", "")
            if not target:
                logger.warning("🎯 Trivy called without target parameter")
                return {"error": "Target parameter is required"}
            command = f"trivy {scan_type} {target}"
            if output_format:
                command += f" --format {output_format}"
            if severity:
                command += f" --severity {severity}"
            if output_file:
                command += f" --output {output_file}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🔍 Starting Trivy {scan_type} scan: {target}")
            result = execute_command(command)
            if output_file:
                result["output_file"] = output_file
            logger.info(f"📊 Trivy scan completed for {target}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in trivy endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
