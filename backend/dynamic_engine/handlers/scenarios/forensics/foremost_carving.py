import logging
from pathlib import Path
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class ForemostHandler(AbstractHandler):
    """Handler for foremost functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["foremost"]

    def handle(self, data: Dict) -> Any:
        """Execute foremost with enhanced logging"""
        try:
            input_file = data.get("input_file", "")
            output_dir = data.get("output_dir", "/tmp/foremost_output")
            file_types = data.get("file_types", "")
            additional_args = data.get("additional_args", "")
            if not input_file:
                logger.warning("📁 Foremost called without input_file parameter")
                return {"error": "Input file parameter is required"}
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            command = f"foremost -o {output_dir}"
            if file_types:
                command += f" -t {file_types}"
            if additional_args:
                command += f" {additional_args}"
            command += f" {input_file}"
            logger.info(f"📁 Starting Foremost file carving: {input_file}")
            result = execute_command(command)
            result["output_directory"] = output_dir
            logger.info("📊 Foremost carving completed")
            return result
        except Exception as e:
            logger.error(f"💥 Error in foremost endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
