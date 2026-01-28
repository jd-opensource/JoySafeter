import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class ApiSchemaAnalyzerHandler(AbstractHandler):
    """Handler for api_schema_analyzer functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["curl"]

    def handle(self, data: Dict) -> Any:
        """Execute api_schema_analyzer with enhanced logging"""
        try:
            schema_url = data.get("schema_url", "")
            schema_type = data.get("schema_type", "openapi")  # openapi, swagger, graphql
            if not schema_url:
                logger.warning("📋 API Schema Analyzer called without schema_url parameter")
                return {"error": "Schema URL parameter is required"}
            logger.info(f"🔍 Starting API schema analysis: {schema_url}")
            command = f"curl -s '{schema_url}'"
            result = execute_command(command, use_cache=True)
            if not result.get("success"):
                return {"error": "Failed to fetch API schema"}
            schema_content = result.get("stdout", "")
            analysis_results = {
                "schema_url": schema_url,
                "schema_type": schema_type,
                "endpoints_found": [],
                "security_issues": [],
                "recommendations": [],
            }
            try:
                import json

                schema_data = json.loads(schema_content)
                if schema_type.lower() in ["openapi", "swagger"]:
                    paths = schema_data.get("paths", {})
                    for path, methods in paths.items():
                        for method, details in methods.items():
                            if isinstance(details, dict):
                                endpoint_info = {
                                    "path": path,
                                    "method": method.upper(),
                                    "summary": details.get("summary", ""),
                                    "parameters": details.get("parameters", []),
                                    "security": details.get("security", []),
                                }
                                analysis_results["endpoints_found"].append(endpoint_info)
                                if not endpoint_info["security"]:
                                    analysis_results["security_issues"].append(
                                        {
                                            "endpoint": f"{method.upper()} {path}",
                                            "issue": "no_authentication",
                                            "severity": "MEDIUM",
                                            "description": "Endpoint has no authentication requirements",
                                        }
                                    )
                                for param in endpoint_info["parameters"]:
                                    param_name = param.get("name", "").lower()
                                    if any(
                                        sensitive in param_name for sensitive in ["password", "token", "key", "secret"]
                                    ):
                                        analysis_results["security_issues"].append(
                                            {
                                                "endpoint": f"{method.upper()} {path}",
                                                "issue": "sensitive_parameter",
                                                "severity": "HIGH",
                                                "description": f"Sensitive parameter detected: {param_name}",
                                            }
                                        )
                if analysis_results["security_issues"]:
                    analysis_results["recommendations"] = [
                        "Implement authentication for all endpoints",
                        "Use HTTPS for all API communications",
                        "Validate and sanitize all input parameters",
                        "Implement rate limiting",
                        "Add proper error handling",
                        "Use secure headers (CORS, CSP, etc.)",
                    ]
            except json.JSONDecodeError:
                analysis_results["security_issues"].append(
                    {
                        "endpoint": "schema",
                        "issue": "invalid_json",
                        "severity": "HIGH",
                        "description": "Schema is not valid JSON",
                    }
                )
            logger.info(f"📊 Schema analysis completed | Issues found: {len(analysis_results['security_issues'])}")
            return {"success": True, "schema_analysis_results": analysis_results}
        except Exception as e:
            logger.error(f"💥 Error in API schema analyzer: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
