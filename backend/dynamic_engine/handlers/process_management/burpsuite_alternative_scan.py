import logging
from datetime import datetime
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.services.browser import browser_agent
from dynamic_engine.services.http_test_framework import http_framework

logger = logging.getLogger(__name__)


class BurpsuiteAlternativeHandler(AbstractHandler):
    """Handler for burpsuite_alternative functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return []

    def handle(self, data: Dict) -> Any:
        """Execute burpsuite_alternative with enhanced logging"""
        try:
            target = data.get("target", "")
            scan_type = data.get("scan_type", "comprehensive")  # comprehensive, spider, passive, active
            headless = data.get("headless", True)
            max_depth = data.get("max_depth", 3)
            max_pages = data.get("max_pages", 50)
            if not target:
                return {"error": "Target parameter is required"}
            results = {
                "target": target,
                "scan_type": scan_type,
                "timestamp": datetime.now().isoformat(),
                "success": True,
            }
            if scan_type in ["comprehensive", "spider"]:
                if not browser_agent.driver:
                    browser_agent.setup_browser(headless)
                browser_result = browser_agent.navigate_and_inspect(target)
                results["browser_analysis"] = browser_result
            if scan_type in ["comprehensive", "spider"]:
                spider_result = http_framework.spider_website(target, max_depth, max_pages)
                results["spider_analysis"] = spider_result
            if scan_type in ["comprehensive", "active"]:
                discovered_urls = results.get("spider_analysis", {}).get("discovered_urls", [target])
                vuln_results = []
                for url in discovered_urls[:20]:  # Limit to 20 URLs
                    test_result = http_framework.intercept_request(url)
                    if test_result.get("success"):
                        vuln_results.append(test_result)
                results["vulnerability_analysis"] = {
                    "tested_urls": len(vuln_results),
                    "total_vulnerabilities": len(http_framework.vulnerabilities),
                    "recent_vulnerabilities": http_framework._get_recent_vulns(20),
                }
            total_vulns = len(http_framework.vulnerabilities)
            vuln_summary = {}
            for vuln in http_framework.vulnerabilities:
                severity = vuln.get("severity", "unknown")
                vuln_summary[severity] = vuln_summary.get(severity, 0) + 1
            results["summary"] = {
                "total_vulnerabilities": total_vulns,
                "vulnerability_breakdown": vuln_summary,
                "pages_analyzed": len(results.get("spider_analysis", {}).get("discovered_urls", [])),
                "security_score": max(0, 100 - (total_vulns * 5)),
            }
            return results
        except Exception as e:
            return {"error": f"Server error: {str(e)}"}
