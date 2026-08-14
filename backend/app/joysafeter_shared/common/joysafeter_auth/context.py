"""
JoySafeter auth context — role enum and auth context dataclass.

Python equivalent of joysafeter-native's AuthContext.
"""

from dataclasses import dataclass
from enum import Enum, IntEnum


class JoySafeterRole(str, Enum):
    """Organization-level role.

    Answers exactly one question: is this principal an org super-user? Owner and
    admin reach every project; ``member`` is an ordinary member whose per-project
    capability comes solely from ``ProjectRole``.
    """

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"

    @classmethod
    def normalize(cls, role: str | None) -> "JoySafeterRole":
        if not role:
            return cls.MEMBER
        normalized = role.strip().lower()
        try:
            return cls(normalized)
        except ValueError:
            return cls.MEMBER

    @property
    def rank(self) -> int:
        return {
            JoySafeterRole.MEMBER: 1,
            JoySafeterRole.ADMIN: 2,
            JoySafeterRole.OWNER: 3,
        }[self]

    def can_manage_members(self) -> bool:
        return self in (JoySafeterRole.OWNER, JoySafeterRole.ADMIN)

    def can_manage_projects(self) -> bool:
        return self in (JoySafeterRole.OWNER, JoySafeterRole.ADMIN)

    def can_manage_org(self) -> bool:
        return self == JoySafeterRole.OWNER

    def can_grant(self, target: "JoySafeterRole") -> bool:
        return self.rank >= target.rank

    def is_org_superuser(self) -> bool:
        """Owner/admin reach every project regardless of ProjectMember rows."""
        return self in (JoySafeterRole.OWNER, JoySafeterRole.ADMIN)


class ProjectRole(str, Enum):
    """Per-project role. For non-super-users this is the SOLE source of capability."""

    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"

    @classmethod
    def normalize(cls, role: "str | ProjectRole | None") -> "ProjectRole | None":
        if role is None:
            return None
        if isinstance(role, ProjectRole):
            return role
        normalized = role.strip().lower()
        if not normalized:
            return None
        try:
            return cls(normalized)
        except ValueError:
            return cls.VIEWER  # unrecognized but present role → least privilege

    @classmethod
    def parse_strict(cls, role: str) -> "ProjectRole":
        """Parse a role in the project vocabulary.

        Unlike ``normalize`` (fail-closed to VIEWER), this raises ``ValueError``
        on an unrecognized or empty value, so a user-facing assignment endpoint
        can reject bad input rather than silently downgrading it.
        """
        return cls((role or "").strip().lower())


class ProjectCapability(IntEnum):
    """Ordered effective capability within a project (supports >= threshold checks)."""

    NONE = 0
    READ = 1
    WRITE = 2
    ADMIN = 3


def effective_project_capability(
    org_role: "str | JoySafeterRole",
    project_role: "str | ProjectRole | None",
) -> ProjectCapability:
    """Single source of truth for what a principal can do in a project.

    Org owner/admin are super-users (admin everywhere). For everyone else the
    capability is SOLELY their ProjectMember role; no row means no access. There
    is no intersection with the org role — one authoritative source per layer.
    """
    org = org_role if isinstance(org_role, JoySafeterRole) else JoySafeterRole.normalize(org_role)
    if org.is_org_superuser():
        return ProjectCapability.ADMIN
    role = ProjectRole.normalize(project_role)
    if role is None:
        return ProjectCapability.NONE
    return {
        ProjectRole.ADMIN: ProjectCapability.ADMIN,
        ProjectRole.EDITOR: ProjectCapability.WRITE,
        ProjectRole.VIEWER: ProjectCapability.READ,
    }[role]


def default_project_role_for_org_role(org_role: "str | JoySafeterRole") -> ProjectRole:
    """The project role to seed when granting default-project access to a member.

    Super-users map to admin; every ordinary member seeds as viewer (least
    privilege). Higher per-project access is granted explicitly through the
    project-member management surface.
    """
    org = org_role if isinstance(org_role, JoySafeterRole) else JoySafeterRole.normalize(org_role)
    if org.is_org_superuser():
        return ProjectRole.ADMIN
    return ProjectRole.VIEWER


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
    # The caller's ProjectMember.role for the active project (None = no explicit
    # row). Combined with `role` via effective_project_capability to decide what
    # the caller may do in this project. Ignored for org super-users.
    project_role: str | None = None
    # Platform-level super user. This is distinct from org owner/admin and is
    # reserved for cross-organization infrastructure operations.
    is_super_user: bool = False
