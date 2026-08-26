"""Typed entity identifiers.

Single source of truth for public-facing prefixed IDs. Each entity has a
subclass carrying the entity kind in its type (static safety) and value
(serialization/equality). Physical storage remains a bare UUID.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar, Self

from uuid_utils import uuid7


class EntityId:
    prefix: ClassVar[str]
    __slots__ = ("_uuid",)

    def __init__(self, value: uuid.UUID | "EntityId") -> None:
        self._uuid = self._coerce(value)

    @classmethod
    def _coerce(cls, value: Any) -> uuid.UUID:
        if isinstance(value, EntityId):
            if type(value) is not cls:
                raise TypeError(f"cannot build {cls.__name__} from {type(value).__name__}")
            return value.uuid
        if isinstance(value, uuid.UUID):
            return value
        raise TypeError(f"cannot build {cls.__name__} from {type(value).__name__}")

    @classmethod
    def new(cls) -> Self:
        return cls.from_uuid(uuid.UUID(str(uuid7())))

    @classmethod
    def from_uuid(cls, value: uuid.UUID) -> Self:
        return cls(value)

    @classmethod
    def from_public(cls, value: str) -> Self:
        if not isinstance(value, str) or not value.startswith(cls.prefix):
            raise ValueError(f"expected {cls.prefix} prefix")
        raw_uuid = value[len(cls.prefix) :]
        try:
            parsed_uuid = uuid.UUID(raw_uuid)
        except ValueError as exc:
            raise ValueError(f"expected canonical {cls.prefix} entity ID") from exc
        if str(parsed_uuid) != raw_uuid:
            raise ValueError(f"expected canonical {cls.prefix} entity ID")
        return cls.from_uuid(parsed_uuid)

    @property
    def uuid(self) -> uuid.UUID:
        return self._uuid

    def __str__(self) -> str:
        return f"{self.prefix}{self._uuid}"

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._uuid})"

    def __eq__(self, other: object) -> bool:
        if type(self) is not type(other):
            return False
        assert isinstance(other, EntityId)
        return self._uuid == other._uuid

    def __lt__(self, other: object) -> bool:
        # SQLAlchemy's unit of work sorts pending objects by primary key, so a
        # PK-typed EntityId must be orderable. Order by the underlying uuid within
        # the same entity type; cross-type ordering is undefined (never mixed).
        if type(self) is not type(other):
            return NotImplemented
        assert isinstance(other, EntityId)
        return self._uuid < other._uuid

    def __hash__(self) -> int:
        return hash((type(self), self._uuid))

    @classmethod
    def __get_pydantic_core_schema__(cls, source: Any, handler: Any) -> Any:
        from pydantic_core import core_schema

        def validate(value: Any) -> "EntityId":
            if isinstance(value, cls):
                return value
            try:
                if isinstance(value, str):
                    return cls.from_public(value)
                raise TypeError(f"cannot validate {type(value).__name__} as {cls.__name__}")
            except (ValueError, TypeError):
                raise ValueError(f"__entity_id__:{cls.__name__}")  # marker for the handler

        return core_schema.no_info_plain_validator_function(
            validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                str, return_schema=core_schema.str_schema(), when_used="json-unless-none"
            ),
        )


class AgentId(EntityId):
    prefix = "agent_"


class AgentVersionId(EntityId):
    prefix = "agentver_"


class ApiKeyId(EntityId):
    prefix = "apikey_"


class UserId(EntityId):
    prefix = "user_"


class OrganizationId(EntityId):
    prefix = "org_"


class OrganizationMemberId(EntityId):
    prefix = "orgmem_"


class ProjectId(EntityId):
    prefix = "proj_"


class ProjectMemberId(EntityId):
    prefix = "projmem_"


class OAuthAccountId(EntityId):
    prefix = "oauthacct_"


class AuthSessionId(EntityId):
    prefix = "authsess_"


class SessionId(EntityId):
    prefix = "sess_"


class TaskId(EntityId):
    prefix = "task_"


class EnvironmentId(EntityId):
    prefix = "env_"


class TriggerId(EntityId):
    prefix = "trig_"


class MemoryStoreId(EntityId):
    prefix = "memstore_"


class MemoryId(EntityId):
    prefix = "mem_"


class MemoryVersionId(EntityId):
    prefix = "memver_"


class SandboxId(EntityId):
    prefix = "sbx_"


class CredentialId(EntityId):
    prefix = "cred_"


class CredentialGroupId(EntityId):
    prefix = "credgrp_"


class SkillId(EntityId):
    prefix = "skill_"


class SkillFileId(EntityId):
    prefix = "sklfile_"


class SkillSecurityScanId(EntityId):
    prefix = "sklscan_"


class SkillVersionId(EntityId):
    prefix = "sklver_"


class SkillVersionFileId(EntityId):
    prefix = "sklvfile_"


class SkillUsageId(EntityId):
    prefix = "skluse_"


class EventId(EntityId):
    prefix = "evt_"


class FileId(EntityId):
    prefix = "file_"


class SessionResourceId(EntityId):
    prefix = "sesrsc_"


class StorageVolumeId(EntityId):
    prefix = "vol_"


class StorageGrantId(EntityId):
    prefix = "stgrant_"


class StorageMountAuditId(EntityId):
    prefix = "staudit_"


class CredentialAccessAuditId(EntityId):
    prefix = "credaudit_"


class SecurityAuditId(EntityId):
    prefix = "secaudit_"


class SandboxNetworkPolicyId(EntityId):
    prefix = "sbxnetpol_"


REGISTERED_ENTITY_ID_PREFIXES: tuple[str, ...] = tuple(id_type.prefix for id_type in EntityId.__subclasses__())


def registered_entity_id_prefix(value: str) -> str | None:
    return next(
        (prefix for prefix in REGISTERED_ENTITY_ID_PREFIXES if value.startswith(prefix)),
        None,
    )


def as_uuid(value: EntityId) -> uuid.UUID:
    """Return the bare UUID for a typed entity or native UUID.

    Physical-boundary helpers (advisory-lock keys, cross-language Redis channel
    names) need the raw UUID. String parsing belongs at an explicit public or
    persistence boundary and must not leak through this adapter.
    """
    if not isinstance(value, EntityId):
        raise TypeError(f"cannot unwrap {type(value).__name__} as UUID")
    return value.uuid
