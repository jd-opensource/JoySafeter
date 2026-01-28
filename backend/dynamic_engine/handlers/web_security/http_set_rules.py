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
            action = data.get(
                "action", "request"
            )  # request, spider, proxy_history, set_rules, set_scope, repeater, intruder
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
            elif action == "spider":
                if not url:
                    return {"error": "URL parameter is required for spider action"}
                max_depth = data.get("max_depth", 3)
                max_pages = data.get("max_pages", 100)
                result = http_framework.spider_website(url, max_depth, max_pages)
                return result
            elif action == "proxy_history":
                return {
                    "success": True,
                    "history": http_framework.proxy_history[-100:],  # Last 100 requests
                    "total_requests": len(http_framework.proxy_history),
                    "vulnerabilities": http_framework.vulnerabilities,
                }
            elif action == "set_rules":
                rules = data.get("rules", [])
                http_framework.set_match_replace_rules(rules)
                return {"success": True, "rules_set": len(rules)}
            elif action == "set_scope":
                scope_host = data.get("host")
                include_sub = data.get("include_subdomains", True)
                if not scope_host:
                    return {"error": "host parameter required"}
                http_framework.set_scope(scope_host, include_sub)
                return {"success": True, "scope": http_framework.scope}
            elif action == "repeater":
                request_spec = data.get("request") or {}
                result = http_framework.send_custom_request(request_spec)
                return result
            elif action == "intruder":
                if not url:
                    return {"error": "URL parameter required"}
                method = data.get("method", "GET")
                location = data.get("location", "query")
                fuzz_params = data.get("params", [])
                payloads = data.get("payloads", [])
                base_data = data.get("base_data", {})
                max_requests = data.get("max_requests", 100)
                result = http_framework.intruder_sniper(
                    url, method, location, fuzz_params, payloads, base_data, max_requests
                )
                return result
            else:
                return {"error": f"Unknown action: {action}"}
        except Exception as e:
            return {"error": f"Server error: {str(e)}"}
