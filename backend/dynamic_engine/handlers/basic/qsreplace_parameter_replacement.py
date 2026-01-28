import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class QsreplaceHandler(AbstractHandler):
    """Handler for qsreplace functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["qsreplace"]

    def handle(self, data: Dict) -> Any:
        """Execute qsreplace with enhanced logging"""
        try:
            urls = data.get("urls", "")
            replacement = data.get("replacement", "FUZZ")
            additional_args = data.get("additional_args", "")
            if not urls:
                logger.warning("🌐 qsreplace called without URLs")
                return {"error": "URLs parameter is required"}
            command = f"echo '{urls}' | qsreplace '{replacement}'"
            if additional_args:
                command += f" {additional_args}"
            logger.info("🔄 Starting qsreplace parameter replacement")
            result = execute_command(command)
            logger.info("📊 qsreplace parameter replacement completed")
            return result
        except Exception as e:
            logger.error(f"💥 Error in qsreplace endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
