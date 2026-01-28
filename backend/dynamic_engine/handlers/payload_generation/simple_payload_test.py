import logging
from datetime import datetime
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class AiTestPayloadHandler(AbstractHandler):
    """Handler for ai_test_payload functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return []

    def handle(self, data: Dict) -> Any:
        """Execute ai_test_payload with enhanced logging"""
        try:
            payload = data.get("payload", "")
            target_url = data.get("target_url", "")
            method = data.get("method", "GET")
            if not payload or not target_url:
                return {"success": False, "error": "Payload and target_url are required"}
            logger.info(f"🧪 Testing AI-generated payload against {target_url}")
            if method.upper() == "GET":
                encoded_payload = payload.replace(" ", "%20").replace("'", "%27")
                test_command = f"curl -s '{target_url}?test={encoded_payload}'"
            else:
                test_command = f"curl -s -X POST -d 'test={payload}' '{target_url}'"
            result = execute_command(test_command, use_cache=False)
            analysis = {
                "payload_tested": payload,
                "target_url": target_url,
                "method": method,
                "response_size": len(result.get("stdout", "")),
                "success": result.get("success", False),
                "potential_vulnerability": payload.lower() in result.get("stdout", "").lower(),
                "recommendations": [
                    "Analyze response for payload reflection",
                    "Check for error messages indicating vulnerability",
                    "Monitor application behavior changes",
                ],
            }
            logger.info(f"🔍 Payload test completed | Potential vuln: {analysis['potential_vulnerability']}")
            return {
                "success": True,
                "test_result": result,
                "ai_analysis": analysis,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"💥 Error in AI payload testing: {str(e)}")
            return {"success": False, "error": f"Server error: {str(e)}"}
