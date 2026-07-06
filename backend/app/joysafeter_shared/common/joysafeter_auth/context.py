"""
JoySafeter auth context — role enum and auth context dataclass.

Python equivalent of joysafeter-native's AuthContext.
"""

from dataclasses import dataclass
from enum import Enum


class JoySafeterRole(str, Enum):
    """JoySafeter-level roles (superset of OrgRole for finer-grained control)."""

    OWNER = "owner"
    ADMIN = "admin"
    DEVELOPER = "developer"
    VIEWER = "viewer"

    @classmethod
    def normalize(cls, role: str | None) -> "JoySafeterRole":
        if not role:
            return cls.VIEWER
        normalized = role.strip().lower()
        if normalized == "member":
            return cls.DEVELOPER
        try:
            return cls(normalized)
        except ValueError:
            return cls.VIEWER

    @property
    def rank(self) -> int:
        return {
            JoySafeterRole.VIEWER: 1,
            JoySafeterRole.DEVELOPER: 2,
            JoySafeterRole.ADMIN: 3,
            JoySafeterRole.OWNER: 4,
        }[self]

    def can_write(self) -> bool:
        return self in (JoySafeterRole.OWNER, JoySafeterRole.ADMIN, JoySafeterRole.DEVELOPER)

    def can_manage_members(self) -> bool:
        return self in (JoySafeterRole.OWNER, JoySafeterRole.ADMIN)

    def can_manage_projects(self) -> bool:
        return self in (JoySafeterRole.OWNER, JoySafeterRole.ADMIN)

    def can_manage_org(self) -> bool:
        return self == JoySafeterRole.OWNER

    def can_grant(self, target: "JoySafeterRole") -> bool:
        return self.rank >= target.rank


@dataclass
class JoySafeterAuthContext:
    """Resolved auth context for a joysafeter API request."""

    user_id: str
    org_id: str
    project_id: str
    role: JoySafeterRole
    # How the caller authenticated. "user" = a human principal (session/JWT);
    # "api_key" = a service principal. Per-user fairness quotas apply only to
    # human principals; service keys are bounded by the per-project quota so a
    # single service key is not silently clamped to one human's budget.
    principal_type: str = "user"
