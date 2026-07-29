from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

from app.joysafeter_domain.schemas.joysafeter_environment import (
    _is_safe_token,
    normalize_safe_relative_path,
)
from app.joysafeter_shared.config.settings import settings

SUPPORTED_STORAGE_BACKENDS = {"generic", "cubefs", "cephfs", "nfs", "juicefs", "lustre", "pvc", "host_path"}
SUPPORTED_STORAGE_ACCESS = {"read_only", "read_write"}
DANGEROUS_DOCKER_HOST_PATHS = {
    "/",
    "/bin",
    "/boot",
    "/dev",
    "/etc",
    "/home",
    "/proc",
    "/root",
    "/run",
    "/sbin",
    "/sys",
    "/tmp",
    "/usr",
    "/var",
    "/var/run",
    "/var/run/docker.sock",
}


def _trim(value: object) -> str:
    return str(value or "").strip()


def _validate_prefixes(prefixes: list[str]) -> list[str]:
    return [normalize_safe_relative_path(prefix, field_name="allowed_prefix") for prefix in prefixes]


def _allowed_host_path_roots() -> list[PurePosixPath]:
    roots = []
    for raw_root in settings.storage_volume_host_path_roots.split(","):
        root = _trim(raw_root)
        if not root:
            continue
        roots.append(PurePosixPath(root))
    return roots or [PurePosixPath("/mnt/joysafeter/storage")]


def _path_within_root(path: PurePosixPath, root: PurePosixPath) -> bool:
    return path == root or root in path.parents


def _validate_docker_host_path(value: object) -> str:
    host_path = _trim(value)
    if not host_path.startswith("/"):
        raise ValueError("docker.host_path must be absolute")
    if "\x00" in host_path or "\n" in host_path or "\r" in host_path or ":" in host_path:
        raise ValueError("docker.host_path contains unsupported characters")
    path = PurePosixPath(host_path)
    if ".." in path.parts:
        raise ValueError("docker.host_path must not contain path traversal")
    normalized = str(path)
    if normalized in DANGEROUS_DOCKER_HOST_PATHS:
        raise ValueError("docker.host_path points to a reserved host path")
    if normalized.startswith("/var/run/") or normalized.startswith("/proc/") or normalized.startswith("/sys/") or normalized.startswith("/dev/"):
        raise ValueError("docker.host_path points to a reserved host path")
    allowed_roots = _allowed_host_path_roots()
    if not any(_path_within_root(path, root) for root in allowed_roots):
        allowed = ", ".join(str(root) for root in allowed_roots)
        raise ValueError(f"docker.host_path must be under allowed storage roots: {allowed}")
    return normalized


def _validate_k8s_name(value: object, field_name: str) -> str:
    name = _trim(value).lower()
    if not name:
        raise ValueError(f"k8s.{field_name} is required")
    if len(name) > 253:
        raise ValueError(f"k8s.{field_name} is too long")
    if not all(ch.isascii() and (ch.islower() or ch.isdigit() or ch == "-") for ch in name):
        raise ValueError(f"k8s.{field_name} must contain only lowercase letters, numbers or '-'")
    if not name[0].isalnum() or not name[-1].isalnum():
        raise ValueError(f"k8s.{field_name} must start and end with a letter or number")
    return name


def _validate_runtime_spec_dicts(docker: dict[str, Any], k8s: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    docker = dict(docker or {})
    k8s = dict(k8s or {})
    if docker.get("host_path"):
        docker = {"host_path": _validate_docker_host_path(docker.get("host_path"))}
    else:
        docker = {}
    if k8s.get("pvc"):
        normalized_k8s: dict[str, Any] = {"pvc": _validate_k8s_name(k8s.get("pvc"), "pvc")}
        if k8s.get("namespace"):
            normalized_k8s["namespace"] = _validate_k8s_name(k8s.get("namespace"), "namespace")
        k8s = normalized_k8s
    else:
        k8s = {}
    return docker, k8s


class StorageVolumeBase(BaseModel):
    volume_ref: str
    backend_type: str = "generic"
    display_name: str
    description: str = ""
    max_access: str = "read_only"
    allowed_prefixes: list[str] = Field(default_factory=list)
    docker: dict[str, Any] = Field(default_factory=dict)
    k8s: dict[str, Any] = Field(default_factory=dict)
    quota_bytes: Optional[int] = None
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("volume_ref", mode="before")
    @classmethod
    def validate_volume_ref(cls, value: object) -> str:
        ref = _trim(value)
        if not _is_safe_token(ref):
            raise ValueError("volume_ref must contain only ASCII letters, numbers, '-' or '_'")
        return ref

    @field_validator("backend_type", mode="before")
    @classmethod
    def validate_backend_type(cls, value: object) -> str:
        backend = _trim(value).lower() or "generic"
        if backend not in SUPPORTED_STORAGE_BACKENDS:
            raise ValueError(f"unsupported storage backend_type: {backend}")
        return backend

    @field_validator("display_name", mode="before")
    @classmethod
    def validate_display_name(cls, value: object) -> str:
        name = _trim(value)
        if not name:
            raise ValueError("display_name is required")
        return name

    @field_validator("max_access", mode="before")
    @classmethod
    def validate_max_access(cls, value: object) -> str:
        access = _trim(value).lower() or "read_only"
        if access not in SUPPORTED_STORAGE_ACCESS:
            raise ValueError(f"unsupported max_access: {access}")
        return access

    @field_validator("allowed_prefixes", mode="before")
    @classmethod
    def validate_allowed_prefixes(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("allowed_prefixes must be a list")
        return _validate_prefixes([str(item) for item in value])

    @field_validator("quota_bytes")
    @classmethod
    def validate_quota_bytes(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value < 0:
            raise ValueError("quota_bytes must be non-negative")
        return value

    @model_validator(mode="after")
    def validate_runtime_specs(self) -> "StorageVolumeBase":
        self.docker, self.k8s = _validate_runtime_spec_dicts(self.docker, self.k8s)
        docker_host = self.docker.get("host_path")
        k8s_pvc = self.k8s.get("pvc")
        if not docker_host and not k8s_pvc:
            raise ValueError("at least one runtime spec is required: docker.host_path or k8s.pvc")
        return self


class CreateStorageVolumeRequest(StorageVolumeBase):
    project_grants: list["StorageProjectGrantInput"] = Field(default_factory=list)
    organization_grants: list["StorageOrganizationGrantInput"] = Field(default_factory=list)


class UpdateStorageVolumeRequest(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    backend_type: Optional[str] = None
    max_access: Optional[str] = None
    allowed_prefixes: Optional[list[str]] = None
    docker: Optional[dict[str, Any]] = None
    k8s: Optional[dict[str, Any]] = None
    quota_bytes: Optional[int] = None
    enabled: Optional[bool] = None
    metadata: Optional[dict[str, Any]] = None

    _validate_backend_type = field_validator("backend_type", mode="before")(StorageVolumeBase.validate_backend_type.__func__)
    _validate_max_access = field_validator("max_access", mode="before")(StorageVolumeBase.validate_max_access.__func__)
    _validate_allowed_prefixes = field_validator("allowed_prefixes", mode="before")(StorageVolumeBase.validate_allowed_prefixes.__func__)
    _validate_quota_bytes = field_validator("quota_bytes")(StorageVolumeBase.validate_quota_bytes.__func__)

    @model_validator(mode="after")
    def validate_runtime_specs(self) -> "UpdateStorageVolumeRequest":
        if self.docker is not None or self.k8s is not None:
            self.docker, self.k8s = _validate_runtime_spec_dicts(self.docker or {}, self.k8s or {})
            if not self.docker and not self.k8s:
                raise ValueError("at least one runtime spec is required: docker.host_path or k8s.pvc")
        return self


class StorageProjectGrantInput(BaseModel):
    project_id: str
    max_access: str = "read_only"
    allowed_prefixes: list[str] = Field(default_factory=list)
    quota_bytes: Optional[int] = None
    enabled: bool = True

    @field_validator("project_id", mode="before")
    @classmethod
    def validate_project_id(cls, value: object) -> str:
        project_id = _trim(value)
        if not project_id:
            raise ValueError("project_id is required")
        return project_id

    _validate_max_access = field_validator("max_access", mode="before")(StorageVolumeBase.validate_max_access.__func__)
    _validate_allowed_prefixes = field_validator("allowed_prefixes", mode="before")(StorageVolumeBase.validate_allowed_prefixes.__func__)
    _validate_quota_bytes = field_validator("quota_bytes")(StorageVolumeBase.validate_quota_bytes.__func__)


class StorageOrganizationGrantInput(BaseModel):
    org_id: str
    max_access: str = "read_only"
    allowed_prefixes: list[str] = Field(default_factory=list)
    quota_bytes: Optional[int] = None
    enabled: bool = True

    @field_validator("org_id", mode="before")
    @classmethod
    def validate_org_id(cls, value: object) -> str:
        org_id = _trim(value)
        if not org_id:
            raise ValueError("org_id is required")
        return org_id

    _validate_max_access = field_validator("max_access", mode="before")(StorageVolumeBase.validate_max_access.__func__)
    _validate_allowed_prefixes = field_validator("allowed_prefixes", mode="before")(StorageVolumeBase.validate_allowed_prefixes.__func__)
    _validate_quota_bytes = field_validator("quota_bytes")(StorageVolumeBase.validate_quota_bytes.__func__)


class StorageProjectGrantResponse(BaseModel):
    id: uuid.UUID
    volume_id: uuid.UUID
    project_id: str
    max_access: str
    allowed_prefixes: list[str] = Field(default_factory=list)
    quota_bytes: Optional[int] = None
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("id", "volume_id")
    def serialize_uuid(self, value: uuid.UUID) -> str:
        return str(value)


class StorageOrganizationGrantResponse(BaseModel):
    id: uuid.UUID
    volume_id: uuid.UUID
    org_id: str
    max_access: str
    allowed_prefixes: list[str] = Field(default_factory=list)
    quota_bytes: Optional[int] = None
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("id", "volume_id")
    def serialize_uuid(self, value: uuid.UUID) -> str:
        return str(value)


class StorageVolumeResponse(BaseModel):
    id: uuid.UUID
    volume_ref: str
    backend_type: str
    display_name: str
    description: str = ""
    max_access: str
    allowed_prefixes: list[str] = Field(default_factory=list)
    docker: dict[str, Any] = Field(default_factory=dict)
    k8s: dict[str, Any] = Field(default_factory=dict)
    quota_bytes: Optional[int] = None
    used_bytes: int = 0
    enabled: bool
    metadata: dict[str, Any] = Field(default_factory=dict)
    grants: list[StorageProjectGrantResponse] = Field(default_factory=list)
    organization_grants: list[StorageOrganizationGrantResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("id")
    def serialize_id(self, value: uuid.UUID) -> str:
        return str(value)


class StorageCatalogItem(BaseModel):
    volume_ref: str
    backend_type: str
    display_name: str
    description: str = ""
    max_access: str
    allowed_prefixes: list[str] = Field(default_factory=list)
    quota_bytes: Optional[int] = None
    used_bytes: int = 0
    supports_docker: bool = False
    supports_k8s: bool = False


class StorageMountAuditResponse(BaseModel):
    id: uuid.UUID
    volume_id: Optional[uuid.UUID] = None
    project_id: Optional[str] = None
    session_id: Optional[uuid.UUID] = None
    environment_id: Optional[uuid.UUID] = None
    user_id: Optional[str] = None
    action: str
    volume_ref: Optional[str] = None
    mount_path: Optional[str] = None
    sub_path: Optional[str] = None
    access: Optional[str] = None
    bytes_used: Optional[int] = None
    result: str
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("id", "volume_id", "session_id", "environment_id")
    def serialize_uuid(self, value: Optional[uuid.UUID]) -> Optional[str]:
        return str(value) if value else None
