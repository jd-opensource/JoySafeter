import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class JwtAnalyzerHandler(AbstractHandler):
    """Handler for jwt_analyzer functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["python3"]

    def handle(self, data: Dict) -> Any:
        """Execute jwt_analyzer with enhanced logging"""
        try:
            jwt_token = data.get("jwt_token", "")
            target_url = data.get("target_url", "")
            if not jwt_token:
                logger.warning("🔐 JWT Analyzer called without jwt_token parameter")
                return {"error": "JWT token parameter is required"}
            logger.info("🔍 Starting JWT security analysis")
            results = {
                "token": jwt_token[:50] + "..." if len(jwt_token) > 50 else jwt_token,
                "vulnerabilities": [],
                "token_info": {},
                "attack_vectors": [],
            }
            try:
                parts = jwt_token.split(".")
                if len(parts) >= 2:
                    import base64
                    import json

                    header_b64 = parts[0] + "=" * (4 - len(parts[0]) % 4)
                    payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
                    try:
                        header = json.loads(base64.b64decode(header_b64))
                        payload = json.loads(base64.b64decode(payload_b64))
                        results["token_info"] = {
                            "header": header,
                            "payload": payload,
                            "algorithm": header.get("alg", "unknown"),
                        }
                        algorithm = header.get("alg", "").lower()
                        if algorithm == "none":
                            results["vulnerabilities"].append(
                                {
                                    "type": "none_algorithm",
                                    "severity": "CRITICAL",
                                    "description": "JWT uses 'none' algorithm - no signature verification",
                                }
                            )
                        if algorithm in ["hs256", "hs384", "hs512"]:
                            results["attack_vectors"].append("hmac_key_confusion")
                            results["vulnerabilities"].append(
                                {
                                    "type": "hmac_algorithm",
                                    "severity": "MEDIUM",
                                    "description": "HMAC algorithm detected - vulnerable to key confusion attacks",
                                }
                            )
                        exp = payload.get("exp")
                        if not exp:
                            results["vulnerabilities"].append(
                                {
                                    "type": "no_expiration",
                                    "severity": "HIGH",
                                    "description": "JWT token has no expiration time",
                                }
                            )
                    except Exception as decode_error:
                        results["vulnerabilities"].append(
                            {
                                "type": "malformed_token",
                                "severity": "HIGH",
                                "description": f"Token decoding failed: {str(decode_error)}",
                            }
                        )
            except Exception:
                results["vulnerabilities"].append(
                    {"type": "invalid_format", "severity": "HIGH", "description": "Invalid JWT token format"}
                )
            if target_url:
                none_token_parts = jwt_token.split(".")
                if len(none_token_parts) >= 2:
                    none_header = base64.b64encode('{"alg":"none","typ":"JWT"}'.encode()).decode().rstrip("=")
                    none_token = f"{none_header}.{none_token_parts[1]}."
                    command = f"curl -s -H 'Authorization: Bearer {none_token}' '{target_url}'"
                    none_result = execute_command(command, use_cache=False)
                    if "200" in none_result.get("stdout", "") or "success" in none_result.get("stdout", "").lower():
                        results["vulnerabilities"].append(
                            {
                                "type": "none_algorithm_accepted",
                                "severity": "CRITICAL",
                                "description": "Server accepts tokens with 'none' algorithm",
                            }
                        )
            logger.info(f"📊 JWT analysis completed | Vulnerabilities found: {len(results['vulnerabilities'])}")
            return {"success": True, "jwt_analysis_results": results}
        except Exception as e:
            logger.error(f"💥 Error in JWT analyzer: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
