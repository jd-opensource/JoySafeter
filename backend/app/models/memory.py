"""
Memory model

Schema for the memories table:
MEMORY_TABLE_SCHEMA = {
    "memory_id": {"type": String, "primary_key": True, "nullable": False},
    "memory": {"type": JSON, "nullable": False},
    "feedback": {"type": Text, "nullable": True},
    "input": {"type": Text, "nullable": True},
    "agent_id": {"type": String, "nullable": True},
    "team_id": {"type": String, "nullable": True},
    "user_id": {"type": String, "nullable": True, "index": True},
    "topics": {"type": JSON, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": False, "index": True},
    "updated_at": {"type": BigInteger, "nullable": True, "index": True},
}
"""

from typing import Optional

from sqlalchemy import JSON, BigInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Memory(Base):
    """Memory table model."""

    __tablename__ = "memories"

    # primary key is a string memory_id
    memory_id: Mapped[str] = mapped_column(String, primary_key=True, nullable=False, comment="memory ID")

    # core content column
    memory: Mapped[dict] = mapped_column(JSON, nullable=False, comment="memory content (JSON)")

    # optional text columns
    feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="feedback")
    input: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="input")

    # associations (no foreign key constraint; indexed/stored as needed)
    agent_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, comment="Agent ID")
    team_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, comment="team ID")
    user_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True, comment="user ID (string)")

    # topic list (JSON array)
    topics: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True, comment="topic list (JSON array)")

    # timestamps (Unix epoch, BigInteger)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="created at (Unix timestamp)")
    updated_at: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True, index=True, comment="updated at (Unix timestamp)"
    )

    def __repr__(self) -> str:
        return f"<Memory(memory_id={self.memory_id})>"
