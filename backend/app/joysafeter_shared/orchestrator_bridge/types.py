"""Minimal dataclass types extracted from the legacy Python orchestrator runtime.

Only types that API/Worker code imports are kept here.
"""

from dataclasses import dataclass


@dataclass
class SkillArchive:
    name: str
    data: bytes  # decoded tar.gz content
    target: str  # "skills", "agents", or "commands"
