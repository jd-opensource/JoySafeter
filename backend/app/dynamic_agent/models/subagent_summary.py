"""
SubagentSummary - Structured summary returned by subagents.

006: Single Subagent Clean Architecture
- Subagents return concise summaries instead of full execution logs
- Summaries are limited to SUMMARY_MAX_LENGTH characters
- Key information categories: status codes, IDs, cookies, error types
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger

from app.dynamic_agent.core.shared_constants import SUMMARY_MAX_LENGTH

# Key information categories for validation
KEY_INFO_CATEGORIES = [
    "status_code",  # HTTP status codes (200, 401, 403, 500, etc.)
    "id",  # Any discovered IDs (user_id, order_id, session_id, etc.)
    "cookie",  # Session cookies, auth tokens
    "error_type",  # Error classifications
    "flag",  # CTF flags
    "credential",  # Usernames, passwords discovered
    "endpoint",  # API endpoints discovered
    "vulnerability",  # Security vulnerabilities found
]


@dataclass
class SubagentSummary:
    """
    Structured summary of subagent execution result.

    Attributes:
        success: Whether the task completed successfully
        key_findings: List of important discoveries
        extracted_values: Dictionary of key-value pairs (cookies, IDs, etc.)
        next_hint: Optional suggestion for next step
        error: Error message if failed
        duration_ms: Execution duration in milliseconds
    """

    success: bool
    key_findings: List[str] = field(default_factory=list)
    extracted_values: Dict[str, Any] = field(default_factory=dict)
    next_hint: Optional[str] = None
    error: Optional[str] = None
    duration_ms: int = 0

    def to_string(self, max_length: int = SUMMARY_MAX_LENGTH) -> str:
        """
        Convert summary to a concise string representation.

        Args:
            max_length: Maximum length of output string

        Returns:
            Formatted summary string, truncated if necessary
        """
        lines = []

        # Status line
        status = "✅ SUCCESS" if self.success else "❌ FAILED"
        lines.append(f"**Status**: {status}")

        # Error (if any)
        if self.error:
            error_short = self.error[:100] + "..." if len(self.error) > 100 else self.error
            lines.append(f"**Error**: {error_short}")

        # Key findings
        if self.key_findings:
            lines.append("**Findings**:")
            for finding in self.key_findings[:5]:  # Max 5 findings
                finding_short = finding[:80] + "..." if len(finding) > 80 else finding
                lines.append(f"  - {finding_short}")

        # Extracted values
        if self.extracted_values:
            lines.append("**Extracted**:")
            for key, value in list(self.extracted_values.items())[:5]:  # Max 5 values
                value_str = str(value)[:50] + "..." if len(str(value)) > 50 else str(value)
                lines.append(f"  - {key}: {value_str}")

        # Next hint
        if self.next_hint:
            hint_short = self.next_hint[:80] + "..." if len(self.next_hint) > 80 else self.next_hint
            lines.append(f"**Next**: {hint_short}")

        # Duration
        if self.duration_ms > 0:
            lines.append(f"**Duration**: {self.duration_ms}ms")

        result = "\n".join(lines)

        # Truncate if too long
        if len(result) > max_length:
            result = result[: max_length - 3] + "..."

        return result

    @classmethod
    def from_llm_response(cls, response: str, duration_ms: int = 0) -> "SubagentSummary":
        """
        Parse LLM response into SubagentSummary.

        Parses XML format <result>...</result>.

        Args:
            response: Raw LLM response string
            duration_ms: Execution duration

        Returns:
            SubagentSummary instance
        """
        # Parse XML format <result>...</result>
        if "<result>" in response and "</result>" in response:
            try:
                # Extract success
                success_match = re.search(r"<success>(\w+)</success>", response)
                success: bool = bool(success_match and success_match.group(1).lower() == "true")

                # Extract discovery_type (for replan decision)
                discovery_match = re.search(r"<discovery_type>([^<]+)</discovery_type>", response)
                discovery_type = discovery_match.group(1).strip() if discovery_match else "none"

                # Extract key_findings
                findings = re.findall(r"<finding>([^<]+)</finding>", response)
                findings = [f.strip() for f in findings[:5]]

                # Extract extracted_values
                extracted = {}
                values_match = re.search(r"<extracted_values>(.*?)</extracted_values>", response, re.DOTALL)
                if values_match:
                    values_block = values_match.group(1)
                    for tag in ["cookie", "flag", "credentials", "endpoint", "token", "session", "id"]:
                        tag_match = re.search(rf"<{tag}>([^<]+)</{tag}>", values_block)
                        if tag_match:
                            extracted[tag] = tag_match.group(1).strip()

                # Add discovery_type to extracted for context
                if discovery_type and discovery_type != "none":
                    extracted["discovery_type"] = discovery_type

                # Extract suggested_next
                suggested_match = re.search(r"<suggested_next>([^<]+)</suggested_next>", response)
                next_hint = suggested_match.group(1).strip() if suggested_match else None

                # Extract error_diagnosis
                error_match = re.search(r"<error_diagnosis>([^<]+)</error_diagnosis>", response)
                error = error_match.group(1).strip() if error_match else None

                return cls(
                    success=success,
                    key_findings=findings,
                    extracted_values=extracted,
                    next_hint=next_hint,
                    error=error,
                    duration_ms=duration_ms,
                )
            except (ValueError, KeyError) as e:
                logger.debug(f"Failed to parse XML summary: {e}")

        # Fallback: extract from text patterns
        success = (
            ("success" in response.lower() or "completed successfully" in response.lower())
            and "failed" not in response.lower()
            and "error:" not in response.lower()
        )
        error = None
        if "error" in response.lower() or "failed" in response.lower():
            success = False
            error_match = re.search(r"error[:\s]+([^\n]+)", response, re.IGNORECASE)
            if error_match:
                error = error_match.group(1).strip()

        # Extract key findings from bullet points
        findings = []
        for match in re.finditer(r"[-•*]\s*(.+?)(?:\n|$)", response):
            finding = match.group(1).strip()
            if finding and len(finding) > 5:
                findings.append(finding)

        # Extract key-value pairs
        extracted = {}
        for match in re.finditer(r'(\w+(?:_\w+)*)\s*[=:]\s*["\']?([^"\'\n,]+)["\']?', response):
            key, value = match.groups()
            key_lower = key.lower()
            if any(
                cat in key_lower
                for cat in ["id", "cookie", "token", "flag", "user", "pass", "session", "credential", "endpoint"]
            ):
                extracted[key] = value.strip()

        return cls(
            success=success,
            key_findings=findings[:5],
            extracted_values=extracted,
            error=error,
            duration_ms=duration_ms,
        )

    def has_key_info(self, category: str) -> bool:
        """
        Check if summary contains information of a specific category.

        Args:
            category: One of KEY_INFO_CATEGORIES

        Returns:
            True if category information is present
        """
        if category not in KEY_INFO_CATEGORIES:
            return False

        # Check in extracted_values
        for key in self.extracted_values:
            if category in key.lower():
                return True

        # Check in key_findings
        for finding in self.key_findings:
            if category in finding.lower():
                return True

        # Special checks
        if category == "status_code":
            pattern = r"\b[1-5]\d{2}\b"
            for finding in self.key_findings:
                if re.search(pattern, finding):
                    return True

        if category == "flag":
            pattern = r"flag\{[^}]+\}|CTF\{[^}]+\}"
            for finding in self.key_findings:
                if re.search(pattern, finding, re.IGNORECASE):
                    return True
            for value in self.extracted_values.values():
                if re.search(pattern, str(value), re.IGNORECASE):
                    return True

        return False

    def get_coverage_score(self) -> float:
        """
        Calculate coverage score for key information categories.

        Returns:
            Float between 0 and 1 representing coverage
        """
        if not self.key_findings and not self.extracted_values:
            return 0.0

        covered = sum(1 for cat in KEY_INFO_CATEGORIES if self.has_key_info(cat))
        return covered / len(KEY_INFO_CATEGORIES)


def create_summary_from_result(
    result: str,
    success: bool,
    error: Optional[str] = None,
    duration_ms: int = 0,
) -> SubagentSummary:
    """
    Create a SubagentSummary from raw execution result.

    This is a convenience function that combines result parsing
    with explicit success/error status.

    Args:
        result: Raw execution result string
        success: Whether execution succeeded
        error: Error message if failed
        duration_ms: Execution duration

    Returns:
        SubagentSummary instance
    """
    summary = SubagentSummary.from_llm_response(result, duration_ms)
    summary.success = success
    if error:
        summary.error = error
    return summary
