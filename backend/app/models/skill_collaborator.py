"""Skill Collaborator model — per-skill role-based access control."""

from __future__ import annotations

import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel

if TYPE_CHECKING:
    from .auth import AuthUser
    from .skill import Skill


class CollaboratorRole(str, enum.Enum):
    """Roles ordered by privilege: viewer < editor < publisher < admin."""

    viewer = "viewer"
    editor = "editor"
    publisher = "publisher"
    admin = "admin"

    @classmethod
    def rank(cls, role: "CollaboratorRole") -> int:
        _order = [cls.viewer, cls.editor, cls.publisher, cls.admin]
        return _order.index(role)

    def __ge__(self, other):
        if not isinstance(other, CollaboratorRole):
            return NotImplemented
        return CollaboratorRole.rank(self) >= CollaboratorRole.rank(other)

    def __gt__(self, other):
        if not isinstance(other, CollaboratorRole):
            return NotImplemented
        return CollaboratorRole.rank(self) > CollaboratorRole.rank(other)

    def __le__(self, other):
        if not isinstance(other, CollaboratorRole):
            return NotImplemented
        return CollaboratorRole.rank(self) <= CollaboratorRole.rank(other)

    def __lt__(self, other):
        if not isinstance(other, CollaboratorRole):
            return NotImplemented
        return CollaboratorRole.rank(self) < CollaboratorRole.rank(other)


class SkillCollaborator(BaseModel):
    """Per-skill collaborator with role."""

    __tablename__ = "skill_collaborators"

    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[CollaboratorRole] = mapped_column(
        Enum(CollaboratorRole, name="collaborator_role", create_constraint=True),
        nullable=False,
    )
    invited_by: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Relationships
    skill: Mapped["Skill"] = relationship("Skill", lazy="selectin")
    user: Mapped["AuthUser"] = relationship("AuthUser", foreign_keys=[user_id], lazy="selectin")
    inviter: Mapped["AuthUser"] = relationship("AuthUser", foreign_keys=[invited_by], lazy="selectin")

    __table_args__ = (
        UniqueConstraint("skill_id", "user_id", name="skill_collaborators_skill_user_unique"),
        Index("skill_collaborators_user_skill_idx", "user_id", "skill_id"),
    )
