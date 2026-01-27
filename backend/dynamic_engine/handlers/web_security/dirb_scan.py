import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class DirbHandler(AbstractHandler):
    """Handler for dirb functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        '''Handler related commands'''
        return ['dirb']

    def handle(self, data: Dict) -> Any:
        """Execute dirb with enhanced logging"""
        try:
            url = data.get("url", "")
            wordlist = data.get("wordlist", "/usr/share/wordlists/dirb/common.txt")
            additional_args = data.get("additional_args", "")
            if not url:
                logger.warning("🌐 Dirb called without URL parameter")
                return {

                    "error": "URL parameter is required"

                }
            command = f"dirb {url} {wordlist}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"📁 Starting Dirb scan: {url}")
            result = execute_command(command)
            logger.info(f"📊 Dirb scan completed for {url}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in dirb endpoint: {str(e)}")
            return {

                "error": f"Server error: {str(e)}"

            }
