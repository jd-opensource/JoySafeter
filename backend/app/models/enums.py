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
