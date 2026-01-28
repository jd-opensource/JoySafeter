import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class KubeBenchHandler(AbstractHandler):
    """Handler for kube_bench functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["kube-bench"]

    def handle(self, data: Dict) -> Any:
        """Execute kube_bench with enhanced logging"""
        try:
            targets = data.get("targets", "")  # master, node, etcd, policies
            version = data.get("version", "")
            config_dir = data.get("config_dir", "")
            output_format = data.get("output_format", "json")
            additional_args = data.get("additional_args", "")
            command = "kube-bench"
            if targets:
                command += f" --targets {targets}"
            if version:
                command += f" --version {version}"
            if config_dir:
                command += f" --config-dir {config_dir}"
            if output_format:
                command += f" --outputfile /tmp/kube-bench-results.{output_format} --json"
            if additional_args:
                command += f" {additional_args}"
            logger.info("☁️  Starting kube-bench CIS benchmark")
            result = execute_command(command)
            logger.info("📊 kube-bench benchmark completed")
            return result
        except Exception as e:
            logger.error(f"💥 Error in kube-bench endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
