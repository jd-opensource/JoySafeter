"""
Vulnerability Rules Definition
"""

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class VulnerabilityRule:
    """Definition of a vulnerability scanning rule"""

    id: str
    name: str
    severity: str  # HIGH, MEDIUM, LOW, INFO
    patterns: List[str]
    languages: List[str]
    requires_agent: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "id": self.id,
            "name": self.name,
            "severity": self.severity,
            "patterns": self.patterns,
            "languages": self.languages,
            "requires_agent": self.requires_agent,
        }


@dataclass
class Finding:
    """A detected vulnerability"""

    id: str
    rule_id: str
    name: str
    severity: str
    file_path: str
    line_number: int
    code_snippet: str
    context: str = ""
    agent_verification: str = "PENDING"  # PENDING, VERIFIED, FALSE_POSITIVE, UNCERTAIN
    agent_comment: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "id": self.id,
            "rule_id": self.rule_id,
            "type": self.name,
            "severity": self.severity,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "code_snippet": self.code_snippet,
            "agent_verification": self.agent_verification,
            "agent_comment": self.agent_comment,
        }


def load_rules() -> List[VulnerabilityRule]:
    """
    Load vulnerability scanning rules

    Returns:
        List of VulnerabilityRule instances
    """
    rules = [
        # SQL Injection patterns for Python
        VulnerabilityRule(
            id="SQL_INJECTION_PY",
            name="Potential SQL Injection (Python)",
            severity="HIGH",
            patterns=[
                r'["\'].*%.*["\'].*\s*%\s*.*["\']',  # Old style string formatting
                r'["\'].*["\'].*\s*\+\s*[a-zA-Z_][a-zA-Z0-9_]*',  # String concatenation with variable
                r'execute\s*\(\s*["\'].*%.*["\'].*\)',  # execute() with % formatting
                r'cursor\.execute\s*\(\s*["\'].*%.*["\'].*\)',  # cursor.execute() with % formatting
            ],
            languages=[".py"],
            requires_agent=True,
        ),
        # SQL Injection patterns for JavaScript
        VulnerabilityRule(
            id="SQL_INJECTION_JS",
            name="Potential SQL Injection (JavaScript)",
            severity="HIGH",
            patterns=[
                r'["\'].*\+.*["\']',  # String concatenation
                r'query\s*\(\s*["\'].*\+.*["\'].*\)',  # query() with concatenation
                r'pool\.query\s*\(\s*["\'].*\+.*["\'].*\)',  # pool.query() with concatenation
            ],
            languages=[".js", ".ts"],
            requires_agent=True,
        ),
        # Hardcoded secrets
        VulnerabilityRule(
            id="HARDCODED_SECRET",
            name="Hardcoded Secret",
            severity="HIGH",
            patterns=[
                r'[Aa][Pp][Ii][_-]?[Kk][Ee][Yy]\s*=\s*["\'][a-zA-Z0-9\-_]{20,}["\']',  # api_key = "..." (case insensitive)
                r'[Ss][Ee][Cc][Rr][Ee][Tt][_-]?[Kk][Ee][Yy]\s*=\s*["\'][a-zA-Z0-9\-_]{20,}["\']',  # secret_key = "..." (case insensitive)
                r'[Pp][Aa][Ss][Ss][Ww][Oo][Rr][Dd]\s*=\s*["\'][^"\']{8,}["\']',  # password = "..." (case insensitive)
                r'[Tt][Oo][Kk][Ee][Nn]\s*=\s*["\'][a-zA-Z0-9\-_]{20,}["\']',  # token = "..." (case insensitive)
                r'["\'][a-zA-Z0-9]{32}["\']',  # 32-character strings (potential MD5/keys)
                r'["\'][a-zA-Z0-9]{40}["\']',  # 40-character strings (potential SHA1/keys)
            ],
            languages=[".py", ".js", ".ts", ".java", ".php"],
            requires_agent=False,
        ),
        # XSS patterns for JavaScript
        VulnerabilityRule(
            id="XSS_JS",
            name="Potential XSS (JavaScript)",
            severity="MEDIUM",
            patterns=[
                r"innerHTML\s*=\s*.*\+",  # innerHTML with concatenation
                r"document\.write\s*\(\s*.*\+",  # document.write with concatenation
                r"\+\s*user[_-]?input",  # User input being concatenated
                r"\+\s*request\.[a-zA-Z]+",  # Request parameters being concatenated
            ],
            languages=[".js", ".ts"],
            requires_agent=True,
        ),
    ]

    return rules
