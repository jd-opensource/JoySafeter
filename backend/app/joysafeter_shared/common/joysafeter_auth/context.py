"""
JoySafeter auth context — role enum and auth context dataclass.

Python equivalent of joysafeter-native's AuthContext.
"""

from dataclasses import dataclass
from enum import Enum, IntEnum


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
        # Legacy values written before the admin/editor/viewer vocabulary existed.
        legacy = {"owner": cls.ADMIN, "developer": cls.EDITOR, "member": cls.EDITOR}
        if normalized in legacy:
            return legacy[normalized]
        try:
            return cls(normalized)
        except ValueError:
            return cls.VIEWER  # unrecognized but present role → least privilege


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

    Super-users map to admin; org developer→editor; everyone else→viewer. This is
    the one place the legacy org-role vocabulary is translated into project roles.
    """
    org = org_role if isinstance(org_role, JoySafeterRole) else JoySafeterRole.normalize(org_role)
    if org.is_org_superuser():
        return ProjectRole.ADMIN
    if org is JoySafeterRole.DEVELOPER:
        return ProjectRole.EDITOR
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
