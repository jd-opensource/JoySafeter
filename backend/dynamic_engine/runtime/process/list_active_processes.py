import logging
import time
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.utils.process_manager import ProcessManager

logger = logging.getLogger(__name__)


class ListProcessesHandler(AbstractHandler):
    """Handler for list_processes functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def handle(self, data: Dict) -> Any:
        """Execute list_processes with enhanced logging"""
        try:
            processes = ProcessManager.list_active_processes()
            for pid, info in processes.items():
                runtime = time.time() - info["start_time"]
                info["runtime_formatted"] = f"{runtime:.1f}s"
                if info["progress"] > 0:
                    eta = (runtime / info["progress"]) * (1.0 - info["progress"])
                    info["eta_formatted"] = f"{eta:.1f}s"
                else:
                    info["eta_formatted"] = "Unknown"
            return {"success": True, "active_processes": processes, "total_count": len(processes)}
        except Exception as e:
            logger.error(f"💥 Error listing processes: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
