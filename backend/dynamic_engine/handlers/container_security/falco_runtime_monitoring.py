import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class FalcoHandler(AbstractHandler):
    """Handler for falco functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["falco"]

    def handle(self, data: Dict) -> Any:
        """Execute falco with enhanced logging"""
        try:
            config_file = data.get("config_file", "/etc/falco/falco.yaml")
            rules_file = data.get("rules_file", "")
            output_format = data.get("output_format", "json")
            duration = data.get("duration", 60)  # seconds
            additional_args = data.get("additional_args", "")
            command = f"timeout {duration} falco"
            if config_file:
                command += f" --config {config_file}"
            if rules_file:
                command += f" --rules {rules_file}"
            if output_format == "json":
                command += " --json"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🛡️  Starting Falco runtime monitoring for {duration}s")
            result = execute_command(command)
            logger.info("📊 Falco monitoring completed")
            return result
        except Exception as e:
            logger.error(f"💥 Error in falco endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
