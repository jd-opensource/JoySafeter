import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class KubeHunterHandler(AbstractHandler):
    """Handler for kube_hunter functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["kube-hunter"]

    def handle(self, data: Dict) -> Any:
        """Execute kube_hunter with enhanced logging"""
        try:
            target = data.get("target", "")
            remote = data.get("remote", "")
            cidr = data.get("cidr", "")
            interface = data.get("interface", "")
            active = data.get("active", False)
            report = data.get("report", "json")
            additional_args = data.get("additional_args", "")
            command = "kube-hunter"
            if target:
                command += f" --remote {target}"
            elif remote:
                command += f" --remote {remote}"
            elif cidr:
                command += f" --cidr {cidr}"
            elif interface:
                command += f" --interface {interface}"
            else:
                command += " --pod"
            if active:
                command += " --active"
            if report:
                command += f" --report {report}"
            if additional_args:
                command += f" {additional_args}"
            logger.info("☁️  Starting kube-hunter Kubernetes scan")
            result = execute_command(command)
            logger.info("📊 kube-hunter scan completed")
            return result
        except Exception as e:
            logger.error(f"💥 Error in kube-hunter endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
