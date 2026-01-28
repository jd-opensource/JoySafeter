import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class Volatility3Handler(AbstractHandler):
    """Handler for volatility3 functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["vol3"]

    def handle(self, data: Dict) -> Any:
        """Execute volatility3 with enhanced logging"""
        try:
            memory_file = data.get("memory_file", "")
            plugin = data.get("plugin", "")
            output_file = data.get("output_file", "")
            additional_args = data.get("additional_args", "")
            if not memory_file:
                logger.warning("🧠 Volatility3 called without memory_file parameter")
                return {"error": "Memory file parameter is required"}
            if not plugin:
                logger.warning("🧠 Volatility3 called without plugin parameter")
                return {"error": "Plugin parameter is required"}
            command = f"vol.py -f {memory_file} {plugin}"
            if output_file:
                command += f" -o {output_file}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🧠 Starting Volatility3 analysis: {plugin}")
            result = execute_command(command)
            logger.info("📊 Volatility3 analysis completed")
            return result
        except Exception as e:
            logger.error(f"💥 Error in volatility3 endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
