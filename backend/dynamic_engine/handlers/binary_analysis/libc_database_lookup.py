import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class LibcDatabaseHandler(AbstractHandler):
    """Handler for libc_database functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return []

    def handle(self, data: Dict) -> Any:
        """Execute libc_database with enhanced logging"""
        try:
            action = data.get("action", "find")  # find, dump, download
            symbols = data.get("symbols", "")  # format: "symbol1:offset1 symbol2:offset2"
            libc_id = data.get("libc_id", "")
            additional_args = data.get("additional_args", "")
            if action == "find" and not symbols:
                logger.warning("🔧 libc-database find called without symbols")
                return {"error": "Symbols parameter is required for find action"}
            if action in ["dump", "download"] and not libc_id:
                logger.warning("🔧 libc-database called without libc_id for dump/download")
                return {"error": "libc_id parameter is required for dump/download actions"}
            base_command = (
                "cd /opt/libc-database 2>/dev/null || cd ~/libc-database 2>/dev/null || echo 'libc-database not found'"
            )
            if action == "find":
                command = f"{base_command} && ./find {symbols}"
            elif action == "dump":
                command = f"{base_command} && ./dump {libc_id}"
            elif action == "download":
                command = f"{base_command} && ./download {libc_id}"
            else:
                return {"error": f"Invalid action: {action}"}
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🔧 Starting libc-database {action}: {symbols or libc_id}")
            result = execute_command(command)
            logger.info(f"📊 libc-database {action} completed")
            return result
        except Exception as e:
            logger.error(f"💥 Error in libc-database endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
