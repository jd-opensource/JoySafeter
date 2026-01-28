import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class FfufHandler(AbstractHandler):
    """Handler for ffuf functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["ffuf"]

    def handle(self, data: Dict) -> Any:
        """Execute ffuf with enhanced logging"""
        try:
            url = data.get("url", "")
            wordlist = data.get("wordlist", "/usr/share/wordlists/dirb/common.txt")
            mode = data.get("mode", "directory")
            match_codes = data.get("match_codes", "200,204,301,302,307,401,403")
            additional_args = data.get("additional_args", "")
            if not url:
                logger.warning("🌐 FFuf called without URL parameter")
                return {"error": "URL parameter is required"}
            command = "ffuf"
            if mode == "directory":
                command += f" -u {url}/FUZZ -w {wordlist}"
            elif mode == "vhost":
                command += f" -u {url} -H 'Host: FUZZ' -w {wordlist}"
            elif mode == "parameter":
                command += f" -u {url}?FUZZ=value -w {wordlist}"
            else:
                command += f" -u {url} -w {wordlist}"
            command += f" -mc {match_codes}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🔍 Starting FFuf {mode} fuzzing: {url}")
            result = execute_command(command)
            logger.info(f"📊 FFuf fuzzing completed for {url}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in ffuf endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
