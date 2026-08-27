from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class CapturedIdentityCredential:
    kind: Literal["auth_code", "identity_token"]
    value: str
    headers_map: dict[str, str] | None = None
