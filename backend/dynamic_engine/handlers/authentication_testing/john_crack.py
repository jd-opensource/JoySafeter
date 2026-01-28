import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class JohnHandler(AbstractHandler):
    """Handler for john functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["john"]

    def handle(self, data: Dict) -> Any:
        """Execute john with enhanced logging"""
        try:
            hash_file = data.get("hash_file", "")
            wordlist = data.get("wordlist", "/usr/share/wordlists/rockyou.txt")
            format_type = data.get("format", "")
            additional_args = data.get("additional_args", "")
            if not hash_file:
                logger.warning("🔐 John called without hash_file parameter")
                return {"error": "Hash file parameter is required"}
            command = "john"
            if format_type:
                command += f" --format={format_type}"
            if wordlist:
                command += f" --wordlist={wordlist}"
            if additional_args:
                command += f" {additional_args}"
            command += f" {hash_file}"
            logger.info(f"🔐 Starting John the Ripper: {hash_file}")
            result = execute_command(command)
            logger.info("📊 John the Ripper completed")
            return result
        except Exception as e:
            logger.error(f"💥 Error in john endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
