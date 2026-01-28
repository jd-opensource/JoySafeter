"""
Skill 模型
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel

if TYPE_CHECKING:
    from .auth import AuthUser


class Skill(BaseModel):
    """Skill 主表"""

    __tablename__ = "skills"

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(1024), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, default="local")
    source_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    root_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    owner_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    license: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    compatibility: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    meta_data: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    allowed_tools: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # 关系
    owner: Mapped[Optional["AuthUser"]] = relationship(
        "AuthUser",
        foreign_keys=[owner_id],
        lazy="selectin",
    )
    created_by: Mapped["AuthUser"] = relationship(
        "AuthUser",
        foreign_keys=[created_by_id],
        lazy="selectin",
    )
    files: Mapped[List["SkillFile"]] = relationship(
        "SkillFile",
        back_populates="skill",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="skills_owner_name_unique"),
        Index("skills_owner_idx", "owner_id"),
        Index("skills_created_by_idx", "created_by_id"),
        Index("skills_public_idx", "is_public"),
        Index("skills_tags_idx", "tags", postgresql_using="gin"),
    )


class SkillFile(BaseModel):
    """Skill 文件表"""

    __tablename__ = "skill_files"

    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        nullable=False,
    )
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    storage_type: Mapped[str] = mapped_column(String(20), nullable=False, default="database")
    storage_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 关系
    skill: Mapped["Skill"] = relationship("Skill", back_populates="files", lazy="selectin")

    __table_args__ = (
        Index("skill_files_skill_idx", "skill_id"),
        Index("skill_files_path_idx", "skill_id", "path"),
    )
