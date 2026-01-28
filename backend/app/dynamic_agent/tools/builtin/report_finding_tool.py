"""
Report Finding Tool - For sub_agent to report key findings

When sub_agent discovers important information during execution,
call this tool to record it to session_context.findings,
which will be injected into LLM context in subsequent rounds.

When FLAG is found, automatically set flag_found signal to terminate subsequent execution.
"""

import re
from typing import Dict

from langchain_core.tools import tool
from loguru import logger

from app.dynamic_agent.infra.metadata_context import MetadataContext

# FLAG regex patterns
FLAG_PATTERNS = [
    re.compile(r"FLAG\{[^}]+\}", re.IGNORECASE),
    re.compile(r"CTF\{[^}]+\}", re.IGNORECASE),
]

# MetadataContext key for findings storage
_FINDINGS_KEY = "report_findings_store"


def get_findings_store() -> Dict[str, str]:
    """
    Get findings storage for current session (session-scope)

    Returns:
        Findings dictionary for current session, or empty dict if no session context
    """
    metadata = MetadataContext.get()
    if metadata is None:
        logger.warning("No MetadataContext available, returning empty findings")
        return {}

    findings = metadata.get(_FINDINGS_KEY)
    if findings is None:
        # Initialize empty dict
        findings = {}
        metadata[_FINDINGS_KEY] = findings

    return findings


def clear_findings_store() -> None:
    """
    Clear findings storage for current session (session-scope)

    Note: Only clears data for the current session, does not affect other concurrent sessions
    """
    metadata = MetadataContext.get()
    if metadata is not None:
        metadata[_FINDINGS_KEY] = {}
        logger.debug("Cleared findings store for current session")


def _is_real_flag(value: str) -> bool:
    """Check if this is a real FLAG (exclude examples/placeholders)"""
    if not value:
        return False
    lower = value.lower()
    # Exclude examples and placeholders
    if "example" in lower or value == "FLAG{...}" or "placeholder" in lower:
        return False
    # Match FLAG pattern
    return any(p.match(value) for p in FLAG_PATTERNS)


@tool
def report_finding(key: str, value: str) -> str:
    """
    Report an important discovery for tracking (session-scoped).

    Call this when you find critical information during execution:
    - credentials (username:password)
    - cookies or session tokens
    - API endpoints with parameters
    - flags or secrets
    - vulnerable parameters

    Args:
        key: Category of finding (e.g., "credentials", "cookie", "endpoint", "flag")
        value: The actual value found (e.g., "admin:password123", "session=abc123")

    Returns:
        Confirmation message

    Examples:
        report_finding(key="credentials", value="test:test123")
        report_finding(key="cookie", value="PHPSESSID=abc123def456")
        report_finding(key="endpoint", value="/api/order/{id}/receipt")
        report_finding(key="flag", value="FLAG{example_flag}")

    Note:
        Findings are stored in MetadataContext (session-scope), ensuring proper
        isolation between concurrent sessions.
    """
    # Store to session-scope findings store
    findings_store = get_findings_store()
    findings_store[key] = value

    # Check if this is a FLAG
    is_flag = key.lower() == "flag" and _is_real_flag(value)

    # Update metadata
    try:
        metadata = MetadataContext.get()
        if metadata:
            # Update session_context
            session_context = metadata.get("agent_session_context")
            if session_context and hasattr(session_context, "add_finding"):
                session_context.add_finding(key, value)

            # FLAG discovery: set termination signal
            if is_flag:
                metadata["flag_found"] = True
                metadata["found_flag"] = value
                logger.info(f"🏁 FLAG FOUND: {value} - Setting termination signal")
            else:
                logger.info(f"🔑 Finding reported: {key}={value[:50]}...")
    except Exception as e:
        logger.warning(f"Failed to update metadata: {e}")

    if is_flag:
        return f"🏁 FLAG CAPTURED: {value}\n✅ Task completed successfully!"
    return f"✅ Finding recorded: {key}={value[:100]}{'...' if len(value) > 100 else ''}"


# Export tool list
REPORT_FINDING_TOOLS = [report_finding]
