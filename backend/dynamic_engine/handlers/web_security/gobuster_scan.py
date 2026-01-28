import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class GobusterHandler(AbstractHandler):
    """Handler for gobuster functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["gobuster"]

    def handle(self, data: Dict) -> Any:
        """Execute gobuster with enhanced logging"""
        try:
            url = data.get("url", "")
            mode = data.get("mode", "dir")
            wordlist = data.get("wordlist", "/usr/share/wordlists/dirb/common.txt")
            additional_args = data.get("additional_args", "")
            data.get("use_recovery", True)
            if not url:
                logger.warning("🌐 Gobuster called without URL parameter")
                return {"error": "URL parameter is required"}
            if mode not in ["dir", "dns", "fuzz", "vhost"]:
                logger.warning(f"❌ Invalid gobuster mode: {mode}")
                return {"error": f"Invalid mode: {mode}. Must be one of: dir, dns, fuzz, vhost"}
            command = f"gobuster {mode} -u {url} -w {wordlist}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"📁 Starting Gobuster {mode} scan: {url}")
            # if use_recovery:
            #     tool_params = {
            #         "target": url,
            #         "mode": mode,
            #         "wordlist": wordlist,
            #         "additional_args": additional_args
            #     }
            #     result = execute_command("gobuster", command, tool_params)
            # else:
            result = execute_command(command)
            logger.info(f"📊 Gobuster scan completed for {url}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in gobuster endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
