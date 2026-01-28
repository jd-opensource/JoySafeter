import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class GauHandler(AbstractHandler):
    """Handler for gau functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["gau"]

    def handle(self, data: Dict) -> Any:
        """Execute gau with enhanced logging"""
        try:
            domain = data.get("domain", "")
            providers = data.get("providers", "wayback,commoncrawl,otx,urlscan")
            include_subs = data.get("include_subs", True)
            blacklist = data.get("blacklist", "png,jpg,gif,jpeg,swf,woff,svg,pdf,css,ico")
            additional_args = data.get("additional_args", "")
            if not domain:
                logger.warning("🌐 Gau called without domain parameter")
                return {"error": "Domain parameter is required"}
            command = f"gau {domain}"
            if providers != "wayback,commoncrawl,otx,urlscan":
                command += f" --providers {providers}"
            if include_subs:
                command += " --subs"
            if blacklist:
                command += f" --blacklist {blacklist}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"📡 Starting Gau URL discovery: {domain}")
            result = execute_command(command)
            logger.info(f"📊 Gau URL discovery completed for {domain}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in gau endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
