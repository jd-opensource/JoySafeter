import logging
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class CurlRequestHandler(AbstractHandler):
    """
    HTTP request handler using curl.
    Supports various HTTP methods, custom headers, and request body.
    Ideal for CTF web challenges and API testing.
    """

    def __init__(self, config: Dict):
        super().__init__(config)

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["curl"]

    def handle(self, data: Dict) -> Any:
        """Execute HTTP request using curl"""
        try:
            url = data.get("url", "")
            method = data.get("method", "GET").upper()
            headers = data.get("headers", "")
            request_data = data.get("data", "")
            timeout = data.get("timeout", 30)
            follow_redirects = data.get("follow_redirects", True)
            verbose = data.get("verbose", False)

            if not url:
                logger.warning("🌐 curl_request called without URL")
                return {"error": "URL parameter is required"}

            # Build curl command
            command = "curl"

            # Add method
            if method != "GET":
                command += f" -X {method}"

            # Add verbose flag
            if verbose:
                command += " -v"

            # Add follow redirects
            if follow_redirects:
                command += " -L"

            # Add timeout
            command += f" --max-time {timeout}"

            # Add custom headers
            if headers:
                for header in headers.split(","):
                    header = header.strip()
                    if header:
                        command += f' -H "{header}"'

            # Add request body
            if request_data:
                # Escape quotes in data
                escaped_data = request_data.replace('"', '\\"')
                command += f' -d "{escaped_data}"'

            # Add URL (must be last)
            command += f' "{url}"'

            logger.info(f"🌐 Executing curl request: {method} {url}")
            result = execute_command(command, timeout=timeout + 5)

            logger.info(f"📊 curl request completed for {url}")
            result["method"] = method
            result["url"] = url
            return result

        except Exception as e:
            logger.error(f"💥 Error in curl_request: {str(e)}")
            return {"error": f"Request error: {str(e)}"}
