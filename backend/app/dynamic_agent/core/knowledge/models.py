# agent/core/knowledge/models.py
# Data models for CTF knowledge

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List

logger = logging.getLogger(__name__)

# Path to CTF knowledge handlers
# Local development path (agent/core/knowledge/models.py -> backend/dynamic_engine/handlers/knowledge/ctf)
# From: app/dynamic_agent/core/knowledge/models.py
# To:   dynamic_engine/handlers/knowledge/ctf
# Need 5 parents: knowledge -> core -> dynamic_agent -> app -> backend
CTF_KNOWLEDGE_PATH_LOCAL = (
    Path(__file__).parent.parent.parent.parent.parent / "dynamic_engine" / "handlers" / "knowledge" / "ctf"
)
# Container path (mounted volume)
CTF_KNOWLEDGE_PATH_CONTAINER = Path("/opt/ctf/knowledge")

CTF_KNOWLEDGE_PATH_ENV = os.getenv("CTF_KNOWLEDGE_HOST_PATH")


def _is_under_allowed(base_paths: List[Path], user_path: Path) -> bool:
    """
    Check if user_path is within one of the allowed base directories.

    Args:
        base_paths: List of allowed base directories
        user_path: Path to validate

    Returns:
        True if path is within allowed directories, False otherwise
    """
    resolved_user = user_path.resolve()
    for base in base_paths:
        try:
            resolved_user.relative_to(base.resolve())
            return True
        except ValueError:
            continue
    return False


def _get_ctf_knowledge_path() -> Path:
    """Get the appropriate CTF knowledge path based on environment."""
    if CTF_KNOWLEDGE_PATH_ENV:
        env_path = Path(CTF_KNOWLEDGE_PATH_ENV).resolve()

        # Define allowed base directories
        allowed_bases = [
            Path("/opt/ctf/knowledge"),
            Path("/tmp/ctf_knowledge"),
            CTF_KNOWLEDGE_PATH_LOCAL.resolve(),
        ]

        if env_path.exists() and _is_under_allowed(allowed_bases, env_path):
            return env_path

        # Path not allowed or doesn't exist, log warning and fallback
        logger.warning(f"Path {CTF_KNOWLEDGE_PATH_ENV} not allowed or missing, falling back to default path")

    # Check container path first (for Docker environment)
    if CTF_KNOWLEDGE_PATH_CONTAINER.exists():
        return CTF_KNOWLEDGE_PATH_CONTAINER
    # Fall back to local development path
    if CTF_KNOWLEDGE_PATH_LOCAL.exists():
        return CTF_KNOWLEDGE_PATH_LOCAL
    # Return container path as default (will be created if needed)
    return CTF_KNOWLEDGE_PATH_CONTAINER


CTF_KNOWLEDGE_PATH = _get_ctf_knowledge_path()

# File type to challenge type mapping
FILE_TYPE_MAPPING: dict[str, str] = {
    ".elf": "pwn",
    ".exe": "reversing",
    ".so": "pwn",
    ".php": "web",
    ".js": "web",
    ".html": "web",
    ".py": "misc",
    ".pcap": "forensics",
    ".zip": "misc",
    ".png": "misc",
    ".jpg": "misc",
}

# Base keywords for CTF searches
BASE_KEYWORDS = [
    "flag",
    "ctf",
    "exploit",
    "vulnerability",
    "bypass",
    "injection",
    "overflow",
    "shell",
    "reverse",
    "crypto",
]

# Type-specific keywords
TYPE_KEYWORDS: dict[str, list[str]] = {
    "web": ["sql", "xss", "csrf", "ssrf", "lfi", "rce", "ssti", "xxe"],
    "pwn": ["buffer", "overflow", "rop", "shellcode", "heap", "stack"],
    "crypto": ["rsa", "aes", "xor", "hash", "cipher", "decrypt"],
    "reversing": ["disassemble", "decompile", "binary", "assembly"],
    "forensics": ["pcap", "memory", "disk", "steganography", "metadata"],
    "misc": ["encoding", "decode", "script", "automation"],
}


@dataclass
class Trick:
    """Single solving trick for CTF challenges (simplified format)."""

    name: str  # trick name
    when: str  # when to use
    how: str  # how to do it (one sentence)
    payload: str = ""  # example payload (optional)


@dataclass
class CtfKnowledge:
    """CTF knowledge configuration loaded from YAML."""

    name: str
    category: str
    tags: list[str] = field(default_factory=list)
    description: str = ""
    prerequisites: list[str] = field(default_factory=list)
    indicators: list[str] = field(default_factory=list)
    detection: list[dict[str, Any]] = field(default_factory=list)
    mitigation: list[dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    # New simplified format fields
    tricks: list[Trick] = field(default_factory=list)
    difficulty: str = "medium"


@dataclass
class KeywordSearchContext:
    """Context for keyword-guided search."""

    challenge_type: str
    user_hints: list[str] = field(default_factory=list)
    file_signals: list[str] = field(default_factory=list)
    base_keywords: list[str] = field(default_factory=lambda: BASE_KEYWORDS.copy())
    max_keywords: int = 15

    def get_keywords(self) -> list[str]:
        """Assemble keyword pool based on context."""
        keywords: list[str] = []
        seen: set[str] = set()

        def add_keyword(kw: str):
            kw_lower = kw.lower().strip()
            if kw_lower and kw_lower not in seen:
                seen.add(kw_lower)
                keywords.append(kw_lower)

        # 1. User hints have highest priority
        for hint in self.user_hints:
            add_keyword(hint)

        # 2. Type-specific keywords
        if self.challenge_type in TYPE_KEYWORDS:
            for kw in TYPE_KEYWORDS[self.challenge_type]:
                add_keyword(kw)

        # 3. Keywords from file signals
        for signal in self.file_signals:
            ext = os.path.splitext(signal)[1].lower()
            if ext in FILE_TYPE_MAPPING:
                inferred_type = FILE_TYPE_MAPPING[ext]
                if inferred_type in TYPE_KEYWORDS:
                    for kw in TYPE_KEYWORDS[inferred_type][:3]:  # Top 3 from inferred type
                        add_keyword(kw)

        # 4. Base keywords
        for kw in self.base_keywords:
            add_keyword(kw)

        # Cap total keywords
        return keywords[: self.max_keywords]
