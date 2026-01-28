import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.utils.process_manager import ProcessManager

logger = logging.getLogger(__name__)


class PauseProcessHandler(AbstractHandler):
    """Handler for anew functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def handle(self, data: Dict) -> Any:
        try:
            pid = data.get("pid")
            success = ProcessManager.pause_process(pid)
            if success:
                logger.info(f"⏸️ Process {pid} paused successfully")
                return {"success": True, "message": f"Process {pid} paused successfully"}
            else:
                return {"success": False, "error": f"Failed to pause process {pid} or process not found"}
        except Exception as e:
            logger.error(f"💥 Error pausing process {pid}: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
