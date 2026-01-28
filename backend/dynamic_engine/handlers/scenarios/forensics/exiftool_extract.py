import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class ExiftoolHandler(AbstractHandler):
    """Handler for exiftool functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["exiftool"]

    def handle(self, data: Dict) -> Any:
        """Execute exiftool with enhanced logging"""
        try:
            file_path = data.get("file_path", "")
            output_format = data.get("output_format", "")  # json, xml, csv
            tags = data.get("tags", "")
            additional_args = data.get("additional_args", "")
            if not file_path:
                logger.warning("📷 ExifTool called without file_path parameter")
                return {"error": "File path parameter is required"}
            command = "exiftool"
            if output_format:
                command += f" -{output_format}"
            if tags:
                command += f" -{tags}"
            if additional_args:
                command += f" {additional_args}"
            command += f" {file_path}"
            logger.info(f"📷 Starting ExifTool analysis: {file_path}")
            result = execute_command(command)
            logger.info("📊 ExifTool analysis completed")
            return result
        except Exception as e:
            logger.error(f"💥 Error in exiftool endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
