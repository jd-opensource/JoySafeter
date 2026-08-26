"""
Base models
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from app.joysafeter_shared.database import Base
from app.joysafeter_shared.utils.datetime import utc_now


class TSVECTOR(UserDefinedType):
    """PostgreSQL tsvector type for full-text search."""

    def get_col_spec(self):
        return "tsvector"

    def bind_processor(self, dialect):
        def process(value):
            if value is None:
                return None
            return value

        return process

    def result_processor(self, dialect, coltype):
        def process(value):
            return value

        return process


class TimestampMixin:
    """Timestamp mixin."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        onupdate=utc_now,
        nullable=False,
    )


class SoftDeleteMixin:
    """Soft-delete mixin."""

    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class JoySafeterModel(Base, TimestampMixin):
    """Base for persisted JoySafeter models; aggregates own their typed IDs."""

    __abstract__ = True
