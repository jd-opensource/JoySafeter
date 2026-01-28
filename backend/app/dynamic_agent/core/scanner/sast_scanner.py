"""
SAST Scanner - Integrates Semgrep for source code analysis

This module provides a unified interface to run SAST tools and collect findings.
"""

from typing import Any, Dict, List

from loguru import logger


class SASTScanner:
    """
    SAST (Static Application Security Testing) scanner.

    Uses Semgrep to provide comprehensive source code security analysis.
    """

    def __init__(self):
        """Initialize the SAST scanner."""
        self._import_handlers()

    def _import_handlers(self):
        """Import handler classes from dynamic_engine."""
        try:
            from dynamic_engine.handlers.source_code_audit.semgrep_scan import SemgrepHandler

            self.semgrep_handler = SemgrepHandler()
            logger.info("Semgrep handler loaded successfully")
        except ImportError as e:
            logger.warning(f"Could not import Semgrep handler: {e}. Will use fallback mode.")
            self.semgrep_handler = None

    def scan_directory(self, directory: str) -> Dict[str, Any]:
        """
        Run SAST scan on a directory using Semgrep.

        Args:
            directory: Path to the directory to scan

        Returns:
            Dictionary with findings from Semgrep
        """
        all_findings = []
        tool_results = {}

        # Run Semgrep
        if self.semgrep_handler:
            logger.info(f"Running Semgrep scan on {directory}")
            try:
                result = self.semgrep_handler.handle(
                    {
                        "target_path": directory,
                        "rules": "p/security-audit",
                        "exclude": "node_modules,.git,dist,build,vendor,__pycache__",
                    }
                )
                tool_results["semgrep"] = result
                if "findings" in result:
                    all_findings.extend(result["findings"])
            except Exception as e:
                logger.error(f"Semgrep scan failed: {e}")
                tool_results["semgrep"] = {"error": str(e), "findings": []}
        else:
            logger.warning("Semgrep handler not available, skipping scan")
            tool_results["semgrep"] = {"error": "Handler not available", "findings": []}

        # Deduplicate findings
        deduplicated = self._deduplicate_findings(all_findings)

        return {
            "directory": directory,
            "tools_used": ["semgrep"],
            "findings_count": len(deduplicated),
            "findings": deduplicated,
            "tool_results": tool_results,
        }

    def _deduplicate_findings(self, findings: List[Dict]) -> List[Dict]:
        """
        Deduplicate findings based on file path, line number, and rule.

        Args:
            findings: List of finding dictionaries

        Returns:
            Deduplicated list of findings
        """
        seen = set()
        unique = []

        for finding in findings:
            # Create a unique key based on important fields
            key = (
                finding.get("tool", ""),
                finding.get("rule_id", ""),
                finding.get("file_path", ""),
                finding.get("line_number", 0),
            )

            if key not in seen:
                seen.add(key)
                unique.append(finding)

        logger.info(f"Deduplicated {len(findings)} findings to {len(unique)}")
        return unique
