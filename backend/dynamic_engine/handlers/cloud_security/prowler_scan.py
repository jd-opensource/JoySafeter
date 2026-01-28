import logging
from pathlib import Path
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class ProwlerHandler(AbstractHandler):
    """Handler for prowler functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["prowler"]

    def handle(self, data: Dict) -> Any:
        """Execute prowler with enhanced logging"""
        try:
            provider = data.get("provider", "aws")
            profile = data.get("profile", "default")
            region = data.get("region", "")
            checks = data.get("checks", "")
            output_dir = data.get("output_dir", "/tmp/prowler_output")
            output_format = data.get("output_format", "json")
            additional_args = data.get("additional_args", "")
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            command = f"prowler {provider}"
            if profile:
                command += f" --profile {profile}"
            if region:
                command += f" --region {region}"
            if checks:
                command += f" --checks {checks}"
            command += f" --output-directory {output_dir}"
            command += f" --output-format {output_format}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"☁️  Starting Prowler {provider} security assessment")
            result = execute_command(command)
            result["output_directory"] = output_dir
            logger.info("📊 Prowler assessment completed")
            return result
        except Exception as e:
            logger.error(f"💥 Error in prowler endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
