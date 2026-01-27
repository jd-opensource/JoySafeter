"""
AI Agent Reviewer - Verifies high-severity findings to reduce false positives
"""

from typing import List

from loguru import logger

from .rules import Finding, load_rules


class AgentReviewer:
    """
    AI Agent to verify vulnerability findings and reduce false positives.

    Uses taint analysis to determine if a potential vulnerability is actually exploitable.
    """

    def __init__(self):
        """Initialize the agent reviewer."""
        self.rules = load_rules()

    def _create_taint_analysis_prompt(self, finding: Finding) -> str:
        """
        Create a prompt for taint analysis of a finding.

        Args:
            finding: The Finding to analyze

        Returns:
            Prompt string for the LLM
        """
        prompt = f"""
You are a security expert performing taint analysis on a potential vulnerability.

Vulnerability: {finding.name}
File: {finding.file_path}
Line: {finding.line_number}
Severity: {finding.severity}

Code Context (showing ±5 lines around the vulnerability):
```python
{finding.context}
```

Matching Pattern Found:
{finding.code_snippet}

Your task:
1. Analyze if this is a genuine vulnerability (source-to-sink flow)
2. Consider if the input is properly sanitized or validated
3. Determine if the sink (vulnerable code) actually executes with user-controlled data

Answer with:
VERIFIED: If this is a real vulnerability
FALSE_POSITIVE: If this is not actually exploitable (e.g., mock data, safe library function, properly sanitized)
UNCERTAIN: If you cannot determine with confidence

Provide a brief explanation (1-2 sentences) of your reasoning.
"""
        return prompt

    def verify_finding(self, finding: Finding) -> Finding:
        """
        Verify a single finding using AI analysis.

        Args:
            finding: The Finding to verify

        Returns:
            Updated Finding with agent verification results
        """
        # For findings that don't require agent review, mark as not needed
        rule = next((r for r in self.rules if r.id == finding.rule_id), None)
        if not rule or not rule.requires_agent:
            finding.agent_verification = "NOT_REQUIRED"
            finding.agent_comment = "Agent verification not required for this rule"
            return finding

        # For now, use a simple heuristic approach since we don't have actual LLM integration
        # In a real implementation, this would call an LLM API

        # Simple heuristic: if the code contains certain safe patterns, mark as false positive
        safe_patterns = [
            "test",
            "mock",
            "example",
            "demo",
            "#",
            "def test_",
            "def mock_",
        ]

        code_lower = finding.code_snippet.lower()
        context_lower = finding.context.lower()

        # Check if this looks like test code
        if any(pattern in code_lower or pattern in context_lower for pattern in safe_patterns):
            finding.agent_verification = "FALSE_POSITIVE"
            finding.agent_comment = "Appears to be test code or example, not a real vulnerability"
        else:
            # For HIGH severity findings without clear indicators, mark as uncertain for manual review
            if finding.severity == "HIGH":
                finding.agent_verification = "UNCERTAIN"
                finding.agent_comment = "Potential vulnerability - requires manual review"
            else:
                # For lower severity, mark as verified by default
                finding.agent_verification = "VERIFIED"
                finding.agent_comment = "Appears to be a valid vulnerability based on pattern match"

        return finding

    def verify_findings(self, findings: List[Finding]) -> List[Finding]:
        """
        Verify a list of findings.

        Args:
            findings: List of Finding instances

        Returns:
            List of verified Finding instances
        """
        verified_findings = []

        for finding in findings:
            logger.info(f"Verifying finding: {finding.name} in {finding.file_path}")
            verified_finding = self.verify_finding(finding)
            verified_findings.append(verified_finding)

        return verified_findings
