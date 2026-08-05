import re
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

MEMORY_MAX_CONTENT_BYTES = 102400  # 100 KB
MEMORY_MAX_PATH_BYTES = 1024
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


class MemoryOperation(str, Enum):
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"


class MemoryAccess(str, Enum):
    READ_WRITE = "read_write"
    READ_ONLY = "read_only"


class MemoryPrefix(BaseModel):
    type: str = "memory_prefix"
    path: str


class CreateMemoryStoreRequest(BaseModel):
    name: str
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateMemoryStoreRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class MemoryStoreResponse(BaseModel):
    id: uuid.UUID
    type: str = "memory_store"
    name: str
    description: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    archived_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("id")
    def serialize_id(self, v: uuid.UUID) -> str:
        return f"memstore_{v}"


class CreateMemoryRequest(BaseModel):
    path: str
    content: str = ""

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError("Path must start with '/'")
        if len(v.encode("utf-8")) > MEMORY_MAX_PATH_BYTES:
            raise ValueError(f"Path exceeds {MEMORY_MAX_PATH_BYTES} bytes")
        segments = v.split("/")
        for segment in segments:
            if segment in (".", ".."):
                raise ValueError("Path must not contain '.' or '..' segments")
        if "//" in v:
            raise ValueError("Path must not contain '//'")
        if _CONTROL_CHAR_RE.search(v):
            raise ValueError("Path must not contain control characters")
        return v

    @field_validator("content")
    @classmethod
    def validate_content_size(cls, v: str) -> str:
        if len(v.encode("utf-8")) > MEMORY_MAX_CONTENT_BYTES:
            raise ValueError(f"Content exceeds {MEMORY_MAX_CONTENT_BYTES} bytes (100 KB)")
        return v


class UpdateMemoryRequest(BaseModel):
    content: Optional[str] = None
    if_sha256: Optional[str] = None
    precondition: Optional[dict[str, Any]] = None

    @field_validator("content")
    @classmethod
    def validate_content_size(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v.encode("utf-8")) > MEMORY_MAX_CONTENT_BYTES:
            raise ValueError(f"Content exceeds {MEMORY_MAX_CONTENT_BYTES} bytes (100 KB)")
        return v


class MemoryResponse(BaseModel):
    id: uuid.UUID
    type: str = "memory"
    memory_store_id: uuid.UUID
    path: str
    content: Optional[str] = None
    content_sha256: str = ""
    content_size_bytes: int = 0
    version: int = 1
    memory_version_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("id")
    def serialize_id(self, v: uuid.UUID) -> str:
        return f"mem_{v}"

    @field_serializer("memory_store_id")
    def serialize_store_id(self, v: uuid.UUID) -> str:
        return f"memstore_{v}"

    @field_serializer("memory_version_id")
    def serialize_version_id(self, v: Optional[uuid.UUID]) -> Optional[str]:
        return f"memver_{v}" if v else None


class MemoryVersionResponse(BaseModel):
    id: uuid.UUID
    type: str = "memory_version"
    memory_store_id: uuid.UUID
    memory_id: uuid.UUID
    operation: str
    path: Optional[str] = None
    content: Optional[str] = None
    content_sha256: Optional[str] = None
    content_size_bytes: Optional[int] = None
    created_by: Optional[dict[str, Any]] = None
    created_at: datetime
    redacted_at: Optional[datetime] = None
    redacted_by: Optional[dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("id")
    def serialize_id(self, v: uuid.UUID) -> str:
        return f"memver_{v}"

    @field_serializer("memory_store_id")
    def serialize_store_id(self, v: uuid.UUID) -> str:
        return f"memstore_{v}"

    @field_serializer("memory_id")
    def serialize_memory_id(self, v: uuid.UUID) -> str:
        return f"mem_{v}"


class SessionMemoryStoreResponse(BaseModel):
    id: uuid.UUID
    type: str = "session_memory_store"
    session_id: uuid.UUID
    store_id: uuid.UUID
    access: str = "read_write"
    instructions: Optional[str] = None
    mount_name: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("id")
    def serialize_id(self, v: uuid.UUID) -> str:
        return f"sesrsc_{v}"

    @field_serializer("store_id")
    def serialize_store_id(self, v: uuid.UUID) -> str:
        return f"memstore_{v}"
