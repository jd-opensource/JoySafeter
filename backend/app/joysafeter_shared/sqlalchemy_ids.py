"""SQLAlchemy persistence adapter for typed entity identifiers."""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import UUID as _PgUUID
from sqlalchemy.types import TypeDecorator

from app.joysafeter_shared.ids import EntityId


class EntityIdType(TypeDecorator):
    """Store an EntityId as a native UUID column; hydrate its concrete type."""

    impl = _PgUUID(as_uuid=True)
    cache_ok = True

    def __init__(self, id_cls: type[EntityId]) -> None:
        self.id_cls = id_cls
        super().__init__()

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if type(value) is self.id_cls:
            return value.uuid
        raise TypeError(f"cannot bind {type(value).__name__} as {self.id_cls.__name__}")

    def process_result_value(self, value, dialect):
        return None if value is None else self.id_cls.from_uuid(value)
