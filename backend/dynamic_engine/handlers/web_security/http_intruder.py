import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.services.http_test_framework import http_framework

logger = logging.getLogger(__name__)


class HttpFrameworkEndpointHandler(AbstractHandler):
    """Handler for http_framework_endpoint functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return []

    def handle(self, data: Dict) -> Any:
        """Execute http_framework_endpoint with enhanced logging"""
        try:
            action = data.get("action", "request")  # request, spider, ... see original handler
            url = data.get("url", "")
            method = data.get("method", "GET")
            request_data = data.get("data", {})
            headers = data.get("headers", {})
            cookies = data.get("cookies", {})
            if action == "request":
                if not url:
                    return {"error": "URL parameter is required for request action"}
                result = http_framework.intercept_request(url, method, request_data, headers, cookies)
                return result
        except Exception as e:
            return {"error": f"Server error: {str(e)}"}
