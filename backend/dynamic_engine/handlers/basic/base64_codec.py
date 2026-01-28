import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class Base64CodecHandler(AbstractHandler):
    """
    Base64 encoding/decoding handler.
    Encodes or decodes Base64 strings.
    Ideal for CTF challenges involving encoded data.
    """

    def __init__(self, config: Dict):
        super().__init__(config)

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return []

    def handle(self, data: Dict) -> Any:
        """Encode or decode Base64"""
        try:
            input_str = data.get("input", "")
            operation = data.get("operation", "").lower()

            if not input_str:
                logger.warning("🔐 base64_codec called without input")
                return {"error": "Input parameter is required"}

            if operation not in ["encode", "decode"]:
                logger.warning(f"🔐 base64_codec called with invalid operation: {operation}")
                return {"error": "Operation must be 'encode' or 'decode'"}

            # Escape special characters for shell
            escaped_input = input_str.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")

            if operation == "encode":
                command = f'echo -n "{escaped_input}" | base64'
                logger.info(f"🔐 Encoding to Base64: {input_str[:30]}...")
            else:
                command = f'echo -n "{escaped_input}" | base64 -d'
                logger.info(f"🔐 Decoding from Base64: {input_str[:30]}...")

            result = execute_command(command, timeout=10)

            logger.info(f"📊 Base64 {operation} completed")
            result["operation"] = operation
            result["input_preview"] = input_str[:50] + ("..." if len(input_str) > 50 else "")
            return result

        except Exception as e:
            logger.error(f"💥 Error in base64_codec: {str(e)}")
            return {"error": f"Codec error: {str(e)}"}
