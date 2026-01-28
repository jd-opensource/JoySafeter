"""
Extracted State Model

Provides structured state extraction from app.dynamic_agent execution results.
Uses generic, universal patterns that work across all scenarios.

Design Principle (Constitution §6 - Universal Generalization):
- All patterns MUST be generic, not derived from specific test cases
- Extraction logic MUST work for ANY challenge type
- No hardcoded field names or values
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ExtractedState:
    """
    Structured state extracted from execution results.

    Used to pass key state between sequential tasks.
    All fields are generic and scenario-agnostic.
    """

    # Target information (CRITICAL for sub-agent context)
    target_url: Optional[str] = None  # Base URL like http://192.168.64.2:8080

    # HTTP state
    cookies: Dict[str, str] = field(default_factory=dict)
    headers: Dict[str, str] = field(default_factory=dict)

    # Authentication state
    auth_tokens: Dict[str, str] = field(default_factory=dict)  # type -> token

    # Discovered values (generic key-value pairs)
    discovered_values: Dict[str, str] = field(default_factory=dict)  # name -> value

    # Created artifacts
    files_created: List[str] = field(default_factory=list)

    # Important findings (successes worth noting)
    important_findings: List[str] = field(default_factory=list)

    # Errors encountered (for learning and adjustment)
    errors_encountered: List[str] = field(default_factory=list)

    # Successful endpoints/paths discovered
    valid_endpoints: List[str] = field(default_factory=list)

    def merge(self, other: "ExtractedState") -> "ExtractedState":
        """Merge another state into this one, returning a new combined state."""
        return ExtractedState(
            target_url=other.target_url or self.target_url,
            cookies={**self.cookies, **other.cookies},
            headers={**self.headers, **other.headers},
            auth_tokens={**self.auth_tokens, **other.auth_tokens},
            discovered_values={**self.discovered_values, **other.discovered_values},
            files_created=list(set(self.files_created + other.files_created)),
            important_findings=self._dedupe_list(self.important_findings + other.important_findings),
            errors_encountered=self._dedupe_list(self.errors_encountered + other.errors_encountered),
            valid_endpoints=list(set(self.valid_endpoints + other.valid_endpoints)),
        )

    @staticmethod
    def _dedupe_list(items: List[str], max_items: int = 10) -> List[str]:
        """Deduplicate and limit list size."""
        seen = set()
        result = []
        for item in items:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result[-max_items:]  # Keep last N items

    def to_context_string(self) -> str:
        """Generate a context string for passing to subsequent tasks."""
        lines = []

        # Target URL is CRITICAL - must be first
        if self.target_url:
            lines.append(f"**Target URL**: `{self.target_url}`")

        if self.cookies:
            cookie_str = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
            lines.append(f"**Cookies**: `{cookie_str}`")

        if self.auth_tokens:
            for token_type, token_value in self.auth_tokens.items():
                lines.append(f"**{token_type}**: `{token_value}`")

        if self.discovered_values:
            lines.append("**Discovered Values**:")
            for name, value in self.discovered_values.items():
                lines.append(f"  - {name}: `{value}`")

        if self.headers:
            lines.append("**Headers to include**:")
            for k, v in self.headers.items():
                lines.append(f"  - {k}: {v}")

        if self.files_created:
            lines.append(f"**Files Created**: {', '.join(self.files_created)}")

        if self.valid_endpoints:
            lines.append(f"**Valid Endpoints**: {', '.join(self.valid_endpoints[-5:])}")

        if self.important_findings:
            lines.append("**Important Findings**:")
            for finding in self.important_findings[-5:]:
                lines.append(f"  ✅ {finding[:150]}")

        if self.errors_encountered:
            lines.append("**Errors to Avoid** (do NOT repeat these):")
            for error in self.errors_encountered[-3:]:
                lines.append(f"  ❌ {error[:100]}")

        return "\n".join(lines) if lines else ""

    def is_empty(self) -> bool:
        """Check if no state has been extracted."""
        return (
            not self.target_url
            and not self.cookies
            and not self.auth_tokens
            and not self.discovered_values
            and not self.headers
            and not self.files_created
            and not self.important_findings
            and not self.errors_encountered
            and not self.valid_endpoints
        )

    def add_finding(self, finding: str) -> None:
        """Add an important finding."""
        if finding and finding not in self.important_findings:
            self.important_findings.append(finding)

    def add_error(self, error: str) -> None:
        """Add an error encountered."""
        if error and error not in self.errors_encountered:
            self.errors_encountered.append(error)

    def add_valid_endpoint(self, endpoint: str) -> None:
        """Add a valid endpoint discovered."""
        if endpoint and endpoint not in self.valid_endpoints:
            self.valid_endpoints.append(endpoint)


# todo extract with ai
def extract_key_state(result: str) -> ExtractedState:
    """
    Extract key state from execution result text using universal patterns.

    Design Principle (Constitution §6):
    - Uses only generic HTTP/auth patterns
    - No scenario-specific field names
    - Extracts raw key-value pairs for LLM interpretation

    Args:
        result: The execution result text to parse

    Returns:
        ExtractedState with extracted values
    """
    state = ExtractedState()

    if not result:
        return state

    # === Target URL Extraction (CRITICAL for sub-agent context) ===

    # Extract URLs from the result (http/https with host:port)
    url_pattern = r"https?://[a-zA-Z0-9\-\.]+(?::\d+)?"
    url_matches = re.findall(url_pattern, result)
    if url_matches:
        # Use the first complete URL as target
        state.target_url = url_matches[0]

    # === HTTP State Extraction (Universal) ===

    # Extract Set-Cookie headers
    cookie_matches = re.findall(r"Set-Cookie:\s*([^;\n]+)", result, re.IGNORECASE)
    for cookie in cookie_matches:
        if "=" in cookie:
            name, value = cookie.split("=", 1)
            state.cookies[name.strip()] = value.strip()

    # Extract Cookie header
    cookie_header = re.search(r"Cookie:\s*([^\n]+)", result, re.IGNORECASE)
    if cookie_header:
        for part in cookie_header.group(1).split(";"):
            if "=" in part:
                name, value = part.split("=", 1)
                state.cookies[name.strip()] = value.strip()

    # === Authentication Tokens (Universal patterns) ===

    # Bearer token
    bearer_match = re.search(r"Authorization:\s*Bearer\s+([a-zA-Z0-9_\-\.]+)", result, re.IGNORECASE)
    if bearer_match:
        state.auth_tokens["Bearer"] = bearer_match.group(1)

    # Generic token patterns (token, jwt, access_token, etc.)
    token_match = re.search(
        r'["\']?(token|jwt|access_token|api_key)["\']?\s*[=:]\s*["\']?([a-zA-Z0-9_\-\.]+)', result, re.IGNORECASE
    )
    if token_match:
        state.auth_tokens[token_match.group(1)] = token_match.group(2)

    # === Generic Key-Value Extraction ===

    # Extract any JSON-like key-value pairs with string/number values
    # Pattern: "key": "value" or "key": 123
    json_kv = re.findall(r'"(\w+)"\s*:\s*(?:"([^"]+)"|(\d+))', result)
    for key, str_val, num_val in json_kv:
        value = str_val or num_val
        if value and len(key) > 2:  # Skip very short keys
            state.discovered_values[key] = value

    # === File Artifacts ===

    # Files created/saved
    file_patterns = [
        r"(?:created|saved|wrote|written|output)\s+(?:to\s+)?([/\w\-\.]+\.\w+)",
        r"(?:file|output):\s*([/\w\-\.]+\.\w+)",
    ]
    for pattern in file_patterns:
        matches = re.findall(pattern, result, re.IGNORECASE)
        state.files_created.extend(matches)
    state.files_created = list(set(state.files_created))

    # === Important Findings ===

    # Extract lines containing flags or success indicators
    finding_patterns = [
        r".*FLAG\{[^}]+\}.*",  # Flag pattern
        r".*flag\{[^}]+\}.*",
        r".*(?:success|authenticated|logged in|access granted).*",
    ]
    for pattern in finding_patterns:
        matches = re.findall(pattern, result, re.IGNORECASE)
        for match in matches[:3]:
            if len(match.strip()) > 5:
                state.important_findings.append(match.strip()[:200])

    # === Valid Endpoints ===

    # Extract successful endpoint paths (HTTP 200 responses)
    endpoint_pattern = r"(?:GET|POST|PUT|DELETE)\s+(https?://[^\s]+|/[^\s]+).*?(?:200|OK)"
    endpoint_matches = re.findall(endpoint_pattern, result, re.IGNORECASE)
    for endpoint in endpoint_matches[:10]:
        state.valid_endpoints.append(endpoint)

    # === Error Extraction ===

    # Extract error messages for learning
    error_patterns = [
        r"(?:error|failed|denied|unauthorized|forbidden|not found)[:\s]+([^\n]{10,100})",
        r"(?:curl|http).*?(?:error|failed)[:\s]*([^\n]{10,100})",
        r"(?:4\d{2}|5\d{2})\s+([^\n]{10,50})",  # HTTP error codes
    ]
    for pattern in error_patterns:
        matches = re.findall(pattern, result, re.IGNORECASE)
        for match in matches[:3]:
            if len(match.strip()) > 10:
                state.errors_encountered.append(match.strip()[:100])

    return state
