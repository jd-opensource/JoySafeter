import logging
import time
from datetime import datetime
from typing import Any, Dict

import psutil

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.mcp.visual_engine import ModernVisualEngine
from dynamic_engine.utils.process_manager import ProcessManager

logger = logging.getLogger(__name__)


class ProcessDashboardHandler(AbstractHandler):
    """Handler for process_dashboard functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def handle(self, data: Dict) -> Any:
        """Execute process_dashboard with enhanced logging"""
        try:
            processes = ProcessManager.list_active_processes()
            current_time = time.time()
            dashboard_visual = ModernVisualEngine.create_live_dashboard(processes)
            dashboard = {
                "timestamp": datetime.now().isoformat(),
                "total_processes": len(processes),
                "visual_dashboard": dashboard_visual,
                "processes": [],
                "system_load": {
                    "cpu_percent": psutil.cpu_percent(interval=1),
                    "memory_percent": psutil.virtual_memory().percent,
                    "active_connections": len(psutil.net_connections()),
                },
            }
            for pid, info in processes.items():
                runtime = current_time - info["start_time"]
                progress_fraction = info.get("progress", 0)
                progress_bar = ModernVisualEngine.render_progress_bar(
                    progress_fraction, width=25, style="cyber", eta=info.get("eta", 0)
                )
                process_status = {
                    "pid": pid,
                    "command": info["command"][:60] + "..." if len(info["command"]) > 60 else info["command"],
                    "status": info["status"],
                    "runtime": f"{runtime:.1f}s",
                    "progress_percent": f"{progress_fraction * 100:.1f}%",
                    "progress_bar": progress_bar,
                    "eta": f"{info.get('eta', 0):.0f}s" if info.get("eta", 0) > 0 else "Calculating...",
                    "bytes_processed": info.get("bytes_processed", 0),
                    "last_output": info.get("last_output", "")[:100],
                }
                dashboard["processes"].append(process_status)
            return dashboard
        except Exception as e:
            logger.error(f"💥 Error getting process dashboard: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
