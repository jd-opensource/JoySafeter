import logging
from pathlib import Path
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class ScoutSuiteHandler(AbstractHandler):
    """Handler for scout_suite functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["scout"]

    def handle(self, data: Dict) -> Any:
        """Execute scout_suite with enhanced logging"""
        try:
            provider = data.get("provider", "aws")  # aws, azure, gcp, aliyun, oci
            profile = data.get("profile", "default")
            report_dir = data.get("report_dir", "/tmp/scout-suite")
            services = data.get("services", "")
            exceptions = data.get("exceptions", "")
            additional_args = data.get("additional_args", "")
            Path(report_dir).mkdir(parents=True, exist_ok=True)
            command = f"scout {provider}"
            if profile and provider == "aws":
                command += f" --profile {profile}"
            if services:
                command += f" --services {services}"
            if exceptions:
                command += f" --exceptions {exceptions}"
            command += f" --report-dir {report_dir}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"☁️  Starting Scout Suite {provider} assessment")
            result = execute_command(command)
            result["report_directory"] = report_dir
            logger.info("📊 Scout Suite assessment completed")
            return result
        except Exception as e:
            logger.error(f"💥 Error in scout-suite endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
