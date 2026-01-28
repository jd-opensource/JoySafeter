import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class NcConnectHandler(AbstractHandler):
    """
    Netcat connection handler.
    Connects to remote hosts and ports, supports sending/receiving data.
    Ideal for CTF pwn challenges and network interaction.
    """

    def __init__(self, config: Dict):
        super().__init__(config)

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["nc"]

    def handle(self, data: Dict) -> Any:
        """Connect to remote host using netcat"""
        try:
            host = data.get("host", "")
            port = data.get("port", 0)
            send_data = data.get("data", "")
            timeout = data.get("timeout", 10)
            udp = data.get("udp", False)

            if not host:
                logger.warning("🔌 nc_connect called without host")
                return {"error": "Host parameter is required"}

            if not port:
                logger.warning("🔌 nc_connect called without port")
                return {"error": "Port parameter is required"}

            # Build nc command
            command = "nc"

            # Add verbose flag
            command += " -v"

            # Add timeout
            command += f" -w {timeout}"

            # Add UDP flag if needed
            if udp:
                command += " -u"

            # Add host and port
            command += f" {host} {port}"

            # If we have data to send, pipe it
            if send_data:
                # Escape special characters
                escaped_data = send_data.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$")
                command = f'echo -e "{escaped_data}" | {command}'

            logger.info(f"🔌 Connecting to {host}:{port} {'(UDP)' if udp else '(TCP)'}")
            result = execute_command(command, timeout=timeout + 5)

            logger.info(f"📊 nc connection completed for {host}:{port}")
            result["host"] = host
            result["port"] = port
            result["protocol"] = "UDP" if udp else "TCP"
            return result

        except Exception as e:
            logger.error(f"💥 Error in nc_connect: {str(e)}")
            return {"error": f"Connection error: {str(e)}"}
