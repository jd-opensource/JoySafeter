import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class ParamspiderHandler(AbstractHandler):
    """Handler for paramspider functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["paramspider"]

    def handle(self, data: Dict) -> Any:
        """Execute paramspider with enhanced logging"""
        try:
            domain = data.get("domain", "")
            level = data.get("level", 2)
            exclude = data.get("exclude", "png,jpg,gif,jpeg,swf,woff,svg,pdf,css,ico")
            output = data.get("output", "")
            additional_args = data.get("additional_args", "")
            if not domain:
                logger.warning("🌐 ParamSpider called without domain parameter")
                return {"error": "Domain parameter is required"}
            command = f"paramspider -d {domain} -l {level}"
            if exclude:
                command += f" --exclude {exclude}"
            if output:
                command += f" -o {output}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🕷️  Starting ParamSpider mining: {domain}")
            result = execute_command(command)
            logger.info(f"📊 ParamSpider mining completed for {domain}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in paramspider endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
