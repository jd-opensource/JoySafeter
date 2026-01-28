import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class KatanaHandler(AbstractHandler):
    """Handler for katana functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["katana"]

    def handle(self, data: Dict) -> Any:
        """Execute katana with enhanced logging"""
        try:
            url = data.get("url", "")
            depth = data.get("depth", 3)
            js_crawl = data.get("js_crawl", True)
            form_extraction = data.get("form_extraction", True)
            output_format = data.get("output_format", "json")
            additional_args = data.get("additional_args", "")
            if not url:
                logger.warning("🌐 Katana called without URL parameter")
                return {"error": "URL parameter is required"}
            command = f"katana -u {url} -d {depth}"
            if js_crawl:
                command += " -jc"
            if form_extraction:
                command += " -fx"
            if output_format == "json":
                command += " -jsonl"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"⚔️  Starting Katana crawl: {url}")
            result = execute_command(command)
            logger.info(f"📊 Katana crawl completed for {url}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in katana endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
