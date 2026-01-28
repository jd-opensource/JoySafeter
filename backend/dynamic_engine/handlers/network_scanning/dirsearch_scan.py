import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class DirsearchHandler(AbstractHandler):
    """Handler for dirsearch functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["dirsearch"]

    def handle(self, data: Dict) -> Any:
        """Execute dirsearch with enhanced logging"""
        try:
            url = data.get("url", "")
            extensions = data.get("extensions", "php,html,js,txt,xml,json")
            wordlist = data.get("wordlist", "/usr/share/wordlists/dirsearch/common.txt")
            threads = data.get("threads", 30)
            recursive = data.get("recursive", False)
            additional_args = data.get("additional_args", "")
            if not url:
                logger.warning("🌐 Dirsearch called without URL parameter")
                return {"error": "URL parameter is required"}
            command = f"dirsearch -u {url} -e {extensions} -w {wordlist} -t {threads}"
            if recursive:
                command += " -r"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"📁 Starting Dirsearch scan: {url}")
            result = execute_command(command)
            logger.info(f"📊 Dirsearch scan completed for {url}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in dirsearch endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
