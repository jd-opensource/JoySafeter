import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.file_manager import file_manager

logger = logging.getLogger(__name__)


class CreateFileHandler(AbstractHandler):
    """
    Arbitrary shell command
    """

    def __init__(self, config: Dict):
        super().__init__(config)

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return []

    def handle(self, data: Dict) -> Any:
        try:
            filename = data.get("filename", "")
            content = data.get("content", "")
            binary = data.get("binary", False)

            if not filename:
                return {"error": "Filename is required"}

            result = file_manager.create_file(filename, content, binary)
            return result
        except Exception as e:
            logger.error(f"💥 Error creating file: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
