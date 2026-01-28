import logging
import time
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.file_manager import file_manager

logger = logging.getLogger(__name__)


class GeneratePayloadHandler(AbstractHandler):
    """Handler for generate_payload functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["msfvenom"]

    def handle(self, data: Dict) -> Any:
        """Execute generate_payload with enhanced logging"""
        try:
            payload_type = data.get("type", "buffer")
            size = data.get("size", 1024)
            pattern = data.get("pattern", "A")
            filename = data.get("filename", f"payload_{int(time.time())}")
            if size > 100 * 1024 * 1024:  # 100MB limit
                return {"error": "Payload size too large (max 100MB)"}
            if payload_type == "buffer":
                content = pattern * (size // len(pattern))
            elif payload_type == "cyclic":
                alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                content = ""
                for i in range(size):
                    content += alphabet[i % len(alphabet)]
            elif payload_type == "random":
                import random
                import string

                content = "".join(random.choices(string.ascii_letters + string.digits, k=size))
            else:
                return {"error": "Invalid payload type"}
            # todo
            result = file_manager.create_file(filename, content)
            result["payload_info"] = {"type": payload_type, "size": size, "pattern": pattern}
            logger.info(f"🎯 Generated {payload_type} payload: {filename} ({size} bytes)")
            return result
        except Exception as e:
            logger.error(f"💥 Error generating payload: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
