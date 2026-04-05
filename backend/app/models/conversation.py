"""
Conversation model

Manage conversations for the LangGraph dialogue system.
"""

from typing import TYPE_CHECKING

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel, SoftDeleteMixin

if TYPE_CHECKING:
    from app.models.message import Message


class Conversation(BaseModel, SoftDeleteMixin):
    """Conversation table -- store dialogue session information.

    Inherit from BaseTableMixin with the following columns:
    - id: primary key
    - create_by: creator
    - update_by: updater
    - create_time: creation timestamp
    - update_time: update timestamp
    - deleted: soft-delete flag
    """

    __tablename__ = "conversations"

    thread_id: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False, comment="thread ID")
    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        comment="user ID (text)",
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, comment="conversation title")
    meta_data: Mapped[dict] = mapped_column(JSON, nullable=True, default=dict, comment="metadata")
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, comment="active flag (0=no, 1=yes)")

    # relationship: a conversation has many messages; cascade delete on conversation removal
    messages: Mapped[list["Message"]] = relationship(
        "Message",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Conversation(id={self.id}, thread_id={self.thread_id}, title={self.title})>"
