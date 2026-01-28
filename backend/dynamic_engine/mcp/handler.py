import logging
import shutil
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class HandlerType(Enum):
    """ "handler type"""

    MARKDOWN = "markdown"
    COMMAND = "command"
    PYTHON = "python"


class AbstractHandler(ABC):
    def __init__(self, config: Optional[Dict[Any, Any]] = None):
        self.config = config or {}

    @abstractmethod
    def type(self) -> HandlerType:
        pass

    @abstractmethod
    def handle(self, data: Dict) -> Any:
        pass

    def commands(self) -> List[str]:
        """handler related commands"""
        return []

    def available(self) -> bool:
        cmds = self.commands()
        if not cmds:
            return True

        for cmd in cmds:
            if not shutil.which(cmd):
                logger.warning(f"command {cmd} not found, skipping")
                return False
        return True


class MarkdownKnowledgeHandler(AbstractHandler):
    def __init__(self, config: Dict):
        super().__init__(config)
        self.markdown = None
        self.markdown_file_path = config.get("markdown_file_path", None)
        if self.markdown_file_path is None:
            logger.error("Markdown File Path is missing")
            return

        try:
            with open(self.markdown_file_path, "r", encoding="utf-8") as markdown_file:
                self.markdown = markdown_file.read()
        except FileNotFoundError:
            logger.error(f"Markdown File {self.markdown_file_path} Not Found")
        except Exception as e:
            logger.exception("Read Markdown File Error")
            logger.error(f"Read Markdown File {self.markdown_file_path} Error: {e}")

    def type(self) -> HandlerType:
        return HandlerType.MARKDOWN

    def handle(self, data: Dict) -> str:
        return self.markdown if self.markdown is not None else "No Data"
