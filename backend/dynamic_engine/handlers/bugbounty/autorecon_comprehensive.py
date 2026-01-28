import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class AutoreconHandler(AbstractHandler):
    """Handler for autorecon functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["autorecon"]

    def handle(self, data: Dict) -> Any:
        """Execute autorecon with enhanced logging"""
        try:
            target = data.get("target", "")
            output_dir = data.get("output_dir", "/tmp/autorecon")
            port_scans = data.get("port_scans", "top-100-ports")
            service_scans = data.get("service_scans", "default")
            heartbeat = data.get("heartbeat", 60)
            timeout = data.get("timeout", 300)
            additional_args = data.get("additional_args", "")
            if not target:
                logger.warning("🎯 AutoRecon called without target parameter")
                return {"error": "Target parameter is required"}
            command = f"autorecon {target} -o {output_dir} --heartbeat {heartbeat} --timeout {timeout}"
            if port_scans != "default":
                command += f" --port-scans {port_scans}"
            if service_scans != "default":
                command += f" --service-scans {service_scans}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🔄 Starting AutoRecon: {target}")
            result = execute_command(command)
            logger.info(f"📊 AutoRecon completed for {target}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in autorecon endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
