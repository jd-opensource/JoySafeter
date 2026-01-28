import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class GraphqlScannerHandler(AbstractHandler):
    """Handler for graphql_scanner functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["curl"]

    def handle(self, data: Dict) -> Any:
        """Execute graphql_scanner with enhanced logging"""
        try:
            endpoint = data.get("endpoint", "")
            introspection = data.get("introspection", True)
            query_depth = data.get("query_depth", 10)
            data.get("test_mutations", True)
            if not endpoint:
                logger.warning("🌐 GraphQL Scanner called without endpoint parameter")
                return {"error": "GraphQL endpoint parameter is required"}
            logger.info(f"🔍 Starting GraphQL security scan: {endpoint}")
            results = {"endpoint": endpoint, "tests_performed": [], "vulnerabilities": [], "recommendations": []}
            if introspection:
                introspection_query = """
                {
                    __schema {
                        types {
                            name
                            fields {
                                name
                                type {
                                    name
                                }
                            }
                        }
                    }
                }
                """
                clean_query = introspection_query.replace("\n", " ").replace("  ", " ").strip()
                command = f"curl -s -X POST -H 'Content-Type: application/json' -d '{{\"query\":\"{clean_query}\"}}' '{endpoint}'"
                result = execute_command(command, use_cache=False)
                results["tests_performed"].append("introspection_query")
                if "data" in result.get("stdout", ""):
                    results["vulnerabilities"].append(
                        {
                            "type": "introspection_enabled",
                            "severity": "MEDIUM",
                            "description": "GraphQL introspection is enabled",
                        }
                    )
            deep_query = "{ " * query_depth + "field" + " }" * query_depth
            command = (
                f"curl -s -X POST -H 'Content-Type: application/json' -d '{{\"query\":\"{deep_query}\"}}' {endpoint}"
            )
            depth_result = execute_command(command, use_cache=False)
            results["tests_performed"].append("query_depth_analysis")
            if "error" not in depth_result.get("stdout", "").lower():
                results["vulnerabilities"].append(
                    {
                        "type": "no_query_depth_limit",
                        "severity": "HIGH",
                        "description": f"No query depth limiting detected (tested depth: {query_depth})",
                    }
                )
            batch_query = "[" + ",".join(['{"query":"{field}"}' for _ in range(10)]) + "]"
            command = f"curl -s -X POST -H 'Content-Type: application/json' -d '{batch_query}' {endpoint}"
            batch_result = execute_command(command, use_cache=False)
            results["tests_performed"].append("batch_query_testing")
            if "data" in batch_result.get("stdout", "") and batch_result.get("success"):
                results["vulnerabilities"].append(
                    {
                        "type": "batch_queries_allowed",
                        "severity": "MEDIUM",
                        "description": "Batch queries are allowed without rate limiting",
                    }
                )
            if results["vulnerabilities"]:
                results["recommendations"] = [
                    "Disable introspection in production",
                    "Implement query depth limiting",
                    "Add rate limiting for batch queries",
                    "Implement query complexity analysis",
                    "Add authentication for sensitive operations",
                ]
            logger.info(f"📊 GraphQL scan completed | Vulnerabilities found: {len(results['vulnerabilities'])}")
            return {"success": True, "graphql_scan_results": results}
        except Exception as e:
            logger.error(f"💥 Error in GraphQL scanner: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
