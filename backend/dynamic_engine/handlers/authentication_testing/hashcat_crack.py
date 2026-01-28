import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class HashcatHandler(AbstractHandler):
    """Handler for hashcat functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["hashcat"]

    def handle(self, data: Dict) -> Any:
        """Execute hashcat with enhanced logging"""
        try:
            hash_file = data.get("hash_file", "")
            hash_type = data.get("hash_type", "")
            attack_mode = data.get("attack_mode", "0")
            wordlist = data.get("wordlist", "/usr/share/wordlists/rockyou.txt")
            mask = data.get("mask", "")
            additional_args = data.get("additional_args", "")
            if not hash_file:
                logger.warning("🔐 Hashcat called without hash_file parameter")
                return {"error": "Hash file parameter is required"}
            if not hash_type:
                logger.warning("🔐 Hashcat called without hash_type parameter")
                return {"error": "Hash type parameter is required"}
            command = f"hashcat -m {hash_type} -a {attack_mode} {hash_file}"
            if attack_mode == "0" and wordlist:
                command += f" {wordlist}"
            elif attack_mode == "3" and mask:
                command += f" {mask}"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🔐 Starting Hashcat attack: mode {attack_mode}")
            result = execute_command(command)
            logger.info("📊 Hashcat attack completed")
            return result
        except Exception as e:
            logger.error(f"💥 Error in hashcat endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
