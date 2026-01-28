import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class ApiFuzzerHandler(AbstractHandler):
    """Handler for api_fuzzer functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["curl", "ffuf"]

    def handle(self, data: Dict) -> Any:
        """Execute api_fuzzer with enhanced logging"""
        try:
            base_url = data.get("base_url", "")
            endpoints = data.get("endpoints", [])
            methods = data.get("methods", ["GET", "POST", "PUT", "DELETE"])
            wordlist = data.get("wordlist", "/usr/share/wordlists/api/api-endpoints.txt")
            if not base_url:
                logger.warning("🌐 API Fuzzer called without base_url parameter")
                return {"error": "Base URL parameter is required"}
            if endpoints:
                results = []
                for endpoint in endpoints:
                    for method in methods:
                        test_url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
                        command = f"curl -s -X {method} -w '%{{http_code}}|%{{size_download}}' '{test_url}'"
                        result = execute_command(command, use_cache=False)
                        results.append({"endpoint": endpoint, "method": method, "result": result})
                logger.info(f"🔍 API endpoint testing completed for {len(endpoints)} endpoints")
                return {"success": True, "fuzzing_type": "endpoint_testing", "results": results}
            else:
                command = f"ffuf -u {base_url}/FUZZ -w {wordlist} -mc 200,201,202,204,301,302,307,401,403,405 -t 50"
                logger.info(f"🔍 Starting API endpoint discovery: {base_url}")
                result = execute_command(command)
                logger.info("📊 API endpoint discovery completed")
                return {"success": True, "fuzzing_type": "endpoint_discovery", "result": result}
        except Exception as e:
            logger.error(f"💥 Error in API fuzzer: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
