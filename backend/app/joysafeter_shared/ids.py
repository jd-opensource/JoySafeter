"""Typed entity identifiers.

Single source of truth for public-facing prefixed IDs. Each entity has a
subclass carrying the entity kind in its type (static safety) and value
(serialization/equality). Physical storage remains a bare UUID.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from pydantic import GetCoreSchemaHandler
from pydantic_core import core_schema
from uuid_utils import uuid7


class EntityId:
    prefix: ClassVar[str]
    __slots__ = ("_uuid",)

    def __init__(self, value: uuid.UUID | str | "EntityId") -> None:
        self._uuid = self._coerce(value)

    @classmethod
    def _coerce(cls, value: Any) -> uuid.UUID:
        if isinstance(value, EntityId):
            if type(value) is not cls:
                raise TypeError(
                    f"cannot build {cls.__name__} from {type(value).__name__}"
                )
            return value._uuid
        if isinstance(value, uuid.UUID):
            return value
        s = str(value)
        if s.startswith(cls.prefix):
            s = s[len(cls.prefix):]
        return uuid.UUID(s)  # raises ValueError on non-uuid remainder

    @classmethod
    def new(cls) -> "EntityId":
        return cls(uuid.UUID(str(uuid7())))

    @property
    def uuid(self) -> uuid.UUID:
        return self._uuid

    def __str__(self) -> str:
        return f"{self.prefix}{self._uuid}"

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._uuid})"

    def __eq__(self, other: object) -> bool:
        return type(self) is type(other) and self._uuid == other._uuid  # type: ignore[attr-defined]

    def __hash__(self) -> int:
        return hash((type(self), self._uuid))

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        def validate(value: Any) -> "EntityId":
            if isinstance(value, cls):
                return value
            try:
                return cls(value)
            except (ValueError, TypeError):
                raise ValueError(f"__entity_id__:{cls.__name__}")  # marker for the handler

        return core_schema.no_info_plain_validator_function(
            validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                str, return_schema=core_schema.str_schema(), when_used="json-unless-none"
            ),
        )


class AgentId(EntityId):              prefix = "agent_"
class SessionId(EntityId):            prefix = "sess_"
class TaskId(EntityId):               prefix = "task_"
class EnvironmentId(EntityId):        prefix = "env_"
class SecretId(EntityId):             prefix = "secret_"
class TriggerId(EntityId):            prefix = "trig_"
class MemoryStoreId(EntityId):        prefix = "memstore_"
class MemoryId(EntityId):             prefix = "mem_"
class MemoryVersionId(EntityId):      prefix = "memver_"
class SandboxId(EntityId):            prefix = "sbx_"
class VaultId(EntityId):              prefix = "vault_"
class CredentialId(EntityId):         prefix = "cred_"
class SkillId(EntityId):              prefix = "skill_"
class SkillFileId(EntityId):          prefix = "sklfile_"
class SkillSecurityScanId(EntityId):  prefix = "sklscan_"
class EventId(EntityId):              prefix = "evt_"
class FileId(EntityId):               prefix = "file_"
class SessionResourceId(EntityId):    prefix = "sesrsc_"


from sqlalchemy.dialects.postgresql import UUID as _PgUUID
from sqlalchemy.types import TypeDecorator


class EntityIdType(TypeDecorator):
    """Store an EntityId as a native UUID column; hydrate back to the typed id."""

    impl = _PgUUID(as_uuid=True)
    cache_ok = True

    def __init__(self, id_cls: type[EntityId]) -> None:
        self.id_cls = id_cls
        super().__init__()

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, EntityId):
            return value.uuid
        return self.id_cls(value).uuid

    def process_result_value(self, value, dialect):
        return None if value is None else self.id_cls(value)
