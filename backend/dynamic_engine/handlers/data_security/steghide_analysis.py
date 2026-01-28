import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class SteghideHandler(AbstractHandler):
    """Handler for steghide functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["steghide"]

    def handle(self, data: Dict) -> Any:
        """Execute steghide with enhanced logging"""
        try:
            action = data.get("action", "extract")  # extract, embed, info
            cover_file = data.get("cover_file", "")
            embed_file = data.get("embed_file", "")
            passphrase = data.get("passphrase", "")
            output_file = data.get("output_file", "")
            additional_args = data.get("additional_args", "")
            if not cover_file:
                logger.warning("🖼️ Steghide called without cover_file parameter")
                return {"error": "Cover file parameter is required"}
            if action == "extract":
                command = f"steghide extract -sf {cover_file}"
                if output_file:
                    command += f" -xf {output_file}"
            elif action == "embed":
                if not embed_file:
                    return {"error": "Embed file required for embed action"}
                command = f"steghide embed -cf {cover_file} -ef {embed_file}"
            elif action == "info":
                command = f"steghide info {cover_file}"
            else:
                return {"error": "Invalid action. Use: extract, embed, info"}
            if passphrase:
                command += f" -p {passphrase}"
            else:
                command += " -p ''"  # Empty passphrase
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🖼️ Starting Steghide {action}: {cover_file}")
            result = execute_command(command)
            logger.info(f"📊 Steghide {action} completed")
            return result
        except Exception as e:
            logger.error(f"💥 Error in steghide endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
