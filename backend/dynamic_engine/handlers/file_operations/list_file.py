import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.file_manager import file_manager

logger = logging.getLogger(__name__)


class ListFileHandler(AbstractHandler):
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
        """List files in a directory"""
        try:
            directory = data.get("directory", "")
            result = file_manager.list_files(directory)
            return result
        except Exception as e:
            logger.error(f"💥 Error listing files: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
