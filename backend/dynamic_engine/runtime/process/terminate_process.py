import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.process_manager import ProcessManager

logger = logging.getLogger(__name__)


class TerminateProcessHandler(AbstractHandler):
    """Handler for anew functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def handle(self, data: Dict) -> Any:
        try:
            pid = data.get("pid")
            success = ProcessManager.terminate_process(pid)
            if success:
                logger.info(f"🛑 Process {pid} terminated successfully")
                return {"success": True, "message": f"Process {pid} terminated successfully"}
            else:
                return {"success": False, "error": f"Failed to terminate process {pid} or process not found"}
        except Exception as e:
            logger.error(f"💥 Error terminating process {pid}: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
