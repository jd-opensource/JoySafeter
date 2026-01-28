import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class DalfoxHandler(AbstractHandler):
    """Handler for dalfox functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["dalfox"]

    def handle(self, data: Dict) -> Any:
        """Execute dalfox with enhanced logging"""
        try:
            url = data.get("url", "")
            pipe_mode = data.get("pipe_mode", False)
            blind = data.get("blind", False)
            mining_dom = data.get("mining_dom", True)
            mining_dict = data.get("mining_dict", True)
            custom_payload = data.get("custom_payload", "")
            additional_args = data.get("additional_args", "")
            if not url and not pipe_mode:
                logger.warning("🌐 Dalfox called without URL parameter")
                return {"error": "URL parameter is required"}
            if pipe_mode:
                command = "dalfox pipe"
            else:
                command = f"dalfox url {url}"
            if blind:
                command += " --blind"
            if mining_dom:
                command += " --mining-dom"
            if mining_dict:
                command += " --mining-dict"
            if custom_payload:
                command += f" --custom-payload '{custom_payload}'"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🎯 Starting Dalfox XSS scan: {url if url else 'pipe mode'}")
            result = execute_command(command)
            logger.info("📊 Dalfox XSS scan completed")
            return result
        except Exception as e:
            logger.error(f"💥 Error in dalfox endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
