import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.file_manager import file_manager

logger = logging.getLogger(__name__)


class ModifyFileHandler(AbstractHandler):
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
        """Modify an existing file"""
        try:
            filename = data.get("filename", "")
            content = data.get("content", "")
            append = data.get("append", False)

            if not filename:
                return {"error": "Filename is required"}

            result = file_manager.modify_file(filename, content, append)
            return result
        except Exception as e:
            logger.error(f"💥 Error modifying file: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
