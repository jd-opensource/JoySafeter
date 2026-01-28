# NOTE: Converted to object-based implementation
import logging
import time
from datetime import datetime
from typing import Any, Dict

from dynamic_engine.basic.constants import UNSUPPORTED
from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.services.browser import browser_agent

logger = logging.getLogger(__name__)


class BrowserAgentEndpointHandler(AbstractHandler):
    """Handler for browser_agent_endpoint functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return [UNSUPPORTED]

    def handle(self, data: Dict) -> Any:
        """Execute browser_agent_endpoint with enhanced logging"""
        try:
            action = data.get("action", "navigate")  # navigate, screenshot, close
            url = data.get("url", "")
            headless = data.get("headless", True)
            wait_time = data.get("wait_time", 5)
            proxy_port = data.get("proxy_port")
            active_tests = data.get("active_tests", False)
            if action == "navigate":
                if not url:
                    return {"error": "URL parameter is required for navigate action"}
                if not browser_agent.driver:
                    setup_success = browser_agent.setup_browser(headless, proxy_port)
                    if not setup_success:
                        return {"error": "Failed to setup browser"}
                result = browser_agent.navigate_and_inspect(url, wait_time)
                if result.get("success") and active_tests:
                    active_results = browser_agent.run_active_tests(result.get("page_info", {}))
                    result["active_tests"] = active_results
                    if active_results["active_findings"]:
                        logger.warning()
                return result
            elif action == "screenshot":
                if not browser_agent.driver:
                    return {"error": "Browser not initialized. Use navigate action first."}
                screenshot_path = f"/tmp/hexstrike_screenshot_{int(time.time())}.png"
                browser_agent.driver.save_screenshot(screenshot_path)
                return {
                    "success": True,
                    "screenshot": screenshot_path,
                    "current_url": browser_agent.driver.current_url,
                    "timestamp": datetime.now().isoformat(),
                }
            elif action == "close":
                browser_agent.close_browser()
                return {"success": True, "message": "Browser closed successfully"}
            elif action == "status":
                return {
                    "success": True,
                    "browser_active": browser_agent.driver is not None,
                    "screenshots_taken": len(browser_agent.screenshots),
                    "pages_visited": len(browser_agent.page_sources),
                }
            else:
                return {"error": f"Unknown action: {action}"}
        except Exception as e:
            logger.error()
            return {"error": f"Server error: {str(e)}"}
