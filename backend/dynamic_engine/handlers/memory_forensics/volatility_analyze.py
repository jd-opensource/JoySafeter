import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class VolatilityHandler(AbstractHandler):
    """Handler for volatility functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["volatility"]

    def handle(self, data: Dict) -> Any:
        """Execute volatility with enhanced logging"""
        try:
            memory_file = data.get("memory_file", "")
            plugin = data.get("plugin", "")
            profile = data.get("profile", "")
            additional_args = data.get("additional_args", "")
            if not memory_file:
                logger.warning("🧠 Volatility called without memory_file parameter")
                return {"error": "Memory file parameter is required"}
            if not plugin:
                logger.warning("🧠 Volatility called without plugin parameter")
                return {"error": "Plugin parameter is required"}
            command = f"volatility -f {memory_file}"
            if profile:
                command += f" --profile={profile}"
            command += f" {plugin}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🧠 Starting Volatility analysis: {plugin}")
            result = execute_command(command)
            logger.info("📊 Volatility analysis completed")
            return result
        except Exception as e:
            logger.error(f"💥 Error in volatility endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
