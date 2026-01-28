import logging
import time
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.utils.process_manager import ProcessManager

logger = logging.getLogger(__name__)


class GetProcessInfoHandler(AbstractHandler):
    """Handler for anew functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def handle(self, data: Dict) -> Any:
        try:
            pid = data.get("pid")
            process_info = ProcessManager.get_process_status(pid)
            if process_info:
                runtime = time.time() - process_info["start_time"]
                process_info["runtime_formatted"] = f"{runtime:.1f}s"
                if process_info["progress"] > 0:
                    eta = (runtime / process_info["progress"]) * (1.0 - process_info["progress"])
                    process_info["eta_formatted"] = f"{eta:.1f}s"
                else:
                    process_info["eta_formatted"] = "Unknown"
                return {"success": True, "process": process_info}
            else:
                return {"success": False, "error": f"Process {pid} not found"}
        except Exception as e:
            logger.error(f"💥 Error getting process status: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
