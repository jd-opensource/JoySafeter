import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class WaybackurlsHandler(AbstractHandler):
    """Handler for waybackurls functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["waybackurls"]

    def handle(self, data: Dict) -> Any:
        """Execute waybackurls with enhanced logging"""
        try:
            domain = data.get("domain", "")
            get_versions = data.get("get_versions", False)
            no_subs = data.get("no_subs", False)
            additional_args = data.get("additional_args", "")
            if not domain:
                logger.warning("🌐 Waybackurls called without domain parameter")
                return {"error": "Domain parameter is required"}
            command = f"waybackurls {domain}"
            if get_versions:
                command += " --get-versions"
            if no_subs:
                command += " --no-subs"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🕰️  Starting Waybackurls discovery: {domain}")
            result = execute_command(command)
            logger.info(f"📊 Waybackurls discovery completed for {domain}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in waybackurls endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
