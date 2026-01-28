import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class MsfvenomHandler(AbstractHandler):
    """Handler for msfvenom functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["msfvenom"]

    def handle(self, data: Dict) -> Any:
        """Execute msfvenom with enhanced logging"""
        try:
            payload = data.get("payload", "")
            format_type = data.get("format", "")
            output_file = data.get("output_file", "")
            encoder = data.get("encoder", "")
            iterations = data.get("iterations", "")
            additional_args = data.get("additional_args", "")
            if not payload:
                logger.warning("🚀 MSFVenom called without payload parameter")
                return {"error": "Payload parameter is required"}
            command = f"msfvenom -p {payload}"
            if format_type:
                command += f" -f {format_type}"
            if output_file:
                command += f" -o {output_file}"
            if encoder:
                command += f" -e {encoder}"
            if iterations:
                command += f" -i {iterations}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🚀 Starting MSFVenom payload generation: {payload}")
            result = execute_command(command)
            logger.info("📊 MSFVenom payload generated")
            return result
        except Exception as e:
            logger.error(f"💥 Error in msfvenom endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
