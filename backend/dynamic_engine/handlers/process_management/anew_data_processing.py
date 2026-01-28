import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class AnewHandler(AbstractHandler):
    """Handler for anew functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["anew"]

    def handle(self, data: Dict) -> Any:
        """Execute anew with enhanced logging"""
        try:
            input_data = data.get("input_data", "")
            output_file = data.get("output_file", "")
            additional_args = data.get("additional_args", "")
            if not input_data:
                logger.warning("📝 Anew called without input data")
                return {"error": "Input data is required"}
            if output_file:
                command = f"echo '{input_data}' | anew {output_file}"
            else:
                command = f"echo '{input_data}' | anew"
            if additional_args:
                command += f" {additional_args}"
            logger.info("📝 Starting anew data processing")
            result = execute_command(command)
            logger.info("📊 anew data processing completed")
            return result
        except Exception as e:
            logger.error(f"💥 Error in anew endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
