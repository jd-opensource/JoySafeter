"""
Mention parsing for comments.

Format: [@DisplayName](mention://agent/<uuid>) or [@DisplayName](mention://member/<uuid>)
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

_MENTION_RE = re.compile(
    r"\[@([^\]]*)\]\(mention://(agent|member)/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\)"
)


@dataclass(frozen=True)
class Mention:
    display_name: str
    type: str  # "agent" | "member"
    id: uuid.UUID


def parse_mentions(content: str) -> list[Mention]:
    return [
        Mention(display_name=m.group(1), type=m.group(2), id=uuid.UUID(m.group(3)))
        for m in _MENTION_RE.finditer(content)
    ]


def agent_mentions(content: str) -> list[Mention]:
    return [m for m in parse_mentions(content) if m.type == "agent"]
