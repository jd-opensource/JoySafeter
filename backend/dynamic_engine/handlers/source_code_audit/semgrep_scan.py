"""
Semgrep Static Analysis Handler

Executes Semgrep SAST scanner and returns structured findings.
"""

import json
import logging
import os
import tempfile
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class SemgrepHandler(AbstractHandler):
    """Handler for Semgrep static code analysis."""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["semgrep"]

    def handle(self, data: Dict) -> Any:
        """
        Execute Semgrep scan with structured output.

        Args:
            data: Dictionary containing:
                - target_path: Path to scan
                - rules: Semgrep rules config (default: p/security-audit)
                - severity: Minimum severity filter
                - exclude: Paths to exclude
                - timeout: Scan timeout in seconds
                - json_output: Output format flag

        Returns:
            Dictionary with findings and metadata
        """
        try:
            target_path = data.get("target_path", "")
            rules = data.get("rules", "p/security-audit")
            severity = data.get("severity", "")
            exclude = data.get("exclude", "node_modules,.git,dist,build,vendor,__pycache__")
            timeout = data.get("timeout", 300)

            if not target_path:
                logger.warning("🔍 Semgrep called without target_path parameter")
                return {"error": "target_path parameter is required", "findings": []}

            if not os.path.exists(target_path):
                logger.error(f"🔍 Target path does not exist: {target_path}")
                return {"error": f"Target path does not exist: {target_path}", "findings": []}

            # Build command
            output_file = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
            output_path = output_file.name
            output_file.close()

            command = f"semgrep scan --config {rules} --json --output {output_path}"

            # Add severity filter
            if severity:
                command += f" --severity {severity}"

            # Add exclude patterns
            if exclude:
                for pattern in exclude.split(","):
                    pattern = pattern.strip()
                    if pattern:
                        command += f" --exclude '{pattern}'"

            # Add timeout
            command += f" --timeout {timeout}"

            # Add target path
            command += f" {target_path}"

            logger.info(f"🔬 Starting Semgrep scan: {target_path}")
            logger.debug(f"Command: {command}")

            # Execute scan
            execute_command(command, timeout=timeout + 60)

            # Parse JSON output
            findings = []
            raw_report = {}

            if os.path.exists(output_path):
                try:
                    with open(output_path, "r") as f:
                        raw_report = json.load(f)

                    # Extract and normalize findings
                    for item in raw_report.get("results", []):
                        finding = self._normalize_finding(item, target_path)
                        findings.append(finding)

                    logger.info(f"📊 Semgrep scan completed: {len(findings)} findings")

                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse Semgrep output: {e}")

                finally:
                    # Cleanup temp file
                    os.unlink(output_path)
            else:
                logger.warning("Semgrep output file not found")

            return {
                "tool": "semgrep",
                "target_path": target_path,
                "rules": rules,
                "findings_count": len(findings),
                "findings": findings,
                "raw_errors": raw_report.get("errors", []),
            }

        except Exception as e:
            logger.error(f"💥 Error in Semgrep scan: {str(e)}")
            return {
                "error": f"Semgrep scan failed: {str(e)}",
                "findings": [],
            }

    def _normalize_finding(self, item: Dict, base_path: str) -> Dict:
        """
        Normalize a Semgrep finding to unified schema.

        Args:
            item: Raw Semgrep result item
            base_path: Base path for relative path calculation

        Returns:
            Normalized finding dictionary
        """
        # Extract severity (Semgrep uses uppercase)
        severity_map = {
            "ERROR": "HIGH",
            "WARNING": "MEDIUM",
            "INFO": "LOW",
        }
        raw_severity = item.get("extra", {}).get("severity", "INFO")
        severity = severity_map.get(raw_severity.upper(), "INFO")

        # Get file path (make relative if possible)
        file_path = item.get("path", "")
        if file_path.startswith(base_path):
            file_path = os.path.relpath(file_path, base_path)

        # Extract code snippet
        start_line = item.get("start", {}).get("line", 0)
        end_line = item.get("end", {}).get("line", start_line)
        code_lines = item.get("extra", {}).get("lines", "")

        return {
            "id": f"semgrep-{item.get('check_id', 'unknown')}-{start_line}",
            "tool": "semgrep",
            "rule_id": item.get("check_id", "unknown"),
            "type": item.get("extra", {}).get("metadata", {}).get("category", "security"),
            "severity": severity,
            "file_path": file_path,
            "line_number": start_line,
            "end_line": end_line,
            "code_snippet": code_lines,
            "message": item.get("extra", {}).get("message", ""),
            "metadata": item.get("extra", {}).get("metadata", {}),
            "agent_verification": "NOT_REQUIRED",  # Will be updated by LLM review
            "agent_comment": None,
        }
