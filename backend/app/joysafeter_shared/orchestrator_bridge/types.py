"""Minimal dataclass types shared across Python API/worker runtime boundaries.

Only types that API/Worker code imports are kept here.
"""

from dataclasses import dataclass


@dataclass
class SkillArchive:
    name: str
    data: bytes  # decoded tar.gz content
    target: str  # "skills", "agents", or "commands"
