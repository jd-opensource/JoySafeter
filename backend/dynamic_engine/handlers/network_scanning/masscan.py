import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class NmapHandler(AbstractHandler):
    """
    Arbitrary shell command
    """

    def __init__(self, config: Dict):
        super().__init__(config)

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["masscan"]

    def handle(self, data: Dict) -> Any:
        try:
            target = data.get("target", "")
            ports = data.get("ports", "1-65535")
            rate = data.get("rate", 1000)
            interface = data.get("interface", "")
            router_mac = data.get("router_mac", "")
            source_ip = data.get("source_ip", "")
            banners = data.get("banners", False)
            additional_args = data.get("additional_args", "")

            if not target:
                logger.warning("🎯 Masscan called without target parameter")
                return {"error": "Target parameter is required"}

            command = f"masscan {target} -p{ports} --rate={rate}"

            if interface:
                command += f" -e {interface}"

            if router_mac:
                command += f" --router-mac {router_mac}"

            if source_ip:
                command += f" --source-ip {source_ip}"

            if banners:
                command += " --banners"

            if additional_args:
                command += f" {additional_args}"

            logger.info(f"🚀 Starting Masscan: {target} at rate {rate}")
            result = execute_command(command)
            logger.info(f"📊 Masscan completed for {target}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in masscan endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
