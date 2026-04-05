"""
Shared enums for model fields.

These are plain str enums (not SQLAlchemy Enum types) so the DB column stays
varchar — no migration needed.  They provide type safety and IDE autocomplete.
"""

import enum


class InstanceStatus(str, enum.Enum):
    """Lifecycle status for sandbox / OpenClaw container instances."""

    PENDING = "pending"
    CREATING = "creating"
    STARTING = "starting"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"
    TERMINATING = "terminating"


class CopilotSessionStatus(str, enum.Enum):
    """Status for copilot analysis sessions (stored in Redis)."""

    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


class OrgRole(str, enum.Enum):
    """Organization membership roles."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class McpConnectionStatus(str, enum.Enum):
    """Connection status for MCP servers."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class SecurityAuditEventType(str, enum.Enum):
    """Event types for security audit logs."""

    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILURE = "login_failure"


class ModelUsageSource(str, enum.Enum):
    """Source context for model usage logging."""

    CHAT = "chat"
    PLAYGROUND = "playground"
    SKILLS_CREATOR = "skills_creator_page"
