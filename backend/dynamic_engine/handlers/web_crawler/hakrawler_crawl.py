import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class HakrawlerHandler(AbstractHandler):
    """Handler for hakrawler functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["hakrawler"]

    def handle(self, data: Dict) -> Any:
        try:
            url = data.get("url", "")
            depth = data.get("depth", 2)
            forms = data.get("forms", True)
            robots = data.get("robots", True)
            sitemap = data.get("sitemap", True)
            wayback = data.get("wayback", False)
            additional_args = data.get("additional_args", "")
            if not url:
                logger.warning("🕷️ Hakrawler called without URL parameter")
                return {"error": "URL parameter is required"}
            command = f"echo '{url}' | hakrawler -d {depth}"
            if forms:
                command += " -s"  # Show sources (includes forms)
            if robots or sitemap or wayback:
                command += " -subs"  # Include subdomains for better coverage
            command += " -u"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🕷️ Starting Hakrawler crawling: {url}")
            result = execute_command(command)
            logger.info("📊 Hakrawler crawling completed")
            return result
        except Exception as e:
            logger.error(f"💥 Error in hakrawler endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
