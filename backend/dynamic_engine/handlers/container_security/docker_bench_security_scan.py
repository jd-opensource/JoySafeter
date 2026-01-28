import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class DockerBenchSecurityHandler(AbstractHandler):
    """Handler for docker_bench_security functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["docker-bench"]

    def handle(self, data: Dict) -> Any:
        """Execute docker_bench_security with enhanced logging"""
        try:
            checks = data.get("checks", "")  # Specific checks to run
            exclude = data.get("exclude", "")  # Checks to exclude
            output_file = data.get("output_file", "/tmp/docker-bench-results.json")
            additional_args = data.get("additional_args", "")
            command = "docker-bench-security"
            if checks:
                command += f" -c {checks}"
            if exclude:
                command += f" -e {exclude}"
            if output_file:
                command += f" -l {output_file}"
            if additional_args:
                command += f" {additional_args}"
            logger.info("🐳 Starting Docker Bench Security assessment")
            result = execute_command(command)
            result["output_file"] = output_file
            logger.info("📊 Docker Bench Security completed")
            return result
        except Exception as e:
            logger.error(f"💥 Error in docker-bench-security endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
