import posixpath
import uuid
from datetime import datetime
from typing import Any, Literal, NamedTuple, Optional
from urllib.parse import urlparse

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.joysafeter_domain.credentials.references import (
    CredentialReferenceCodec,
    canonicalize_environment_for_read,
)
from app.joysafeter_shared.ids import CredentialId, EnvironmentId, registered_entity_id_prefix

SUPPORTED_EGRESS_INJECT_TYPES = {"bearer", "api_key", "raw_header", "cookie"}
SUPPORTED_EGRESS_EXPOSURES = {"placeholder"}
SUPPORTED_EGRESS_KINDS = {"external"}
SUPPORTED_MOUNT_RESOURCE_TYPES = {"storage"}
SUPPORTED_MOUNT_ACCESS = {"read_only", "read_write"}
FORBIDDEN_MOUNT_PATHS = {
    "/",
    "/workspace",
    "/etc",
    "/root",
    "/home",
    "/proc",
    "/sys",
    "/dev",
    "/var",
    "/var/run",
    "/sockets",
}
_REFERENCE_CODEC = CredentialReferenceCodec()


def _trim_string(value: Optional[str]) -> Optional[str]:
    return value.strip() if value is not None else value


def _validate_environment_name(value: str) -> str:
    name = value.strip()
    if registered_entity_id_prefix(name) is not None:
        raise ValueError("environment name must not begin with a registered entity ID prefix")
    try:
        uuid.UUID(name)
    except ValueError:
        return name
    raise ValueError("environment name must not be UUID-shaped")


def _is_safe_token(value: str, *, allow_dash: bool = True) -> bool:
    allowed = {"_"}
    if allow_dash:
        allowed.add("-")
    return bool(value) and all(ch.isascii() and (ch.isalnum() or ch in allowed) for ch in value)


def normalize_safe_relative_path(value: str, *, field_name: str) -> str:
    raw = str(value or "").replace("\\", "/").strip().strip("/")
    if not raw:
        return ""
    if raw.startswith("/"):
        raise ValueError(f"{field_name} must be relative")
    normalized = posixpath.normpath(raw)
    if normalized in {".", ""}:
        return ""
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"{field_name} must not contain path traversal")
    return normalized


def normalize_safe_workspace_mount_path(value: str) -> str:
    raw = str(value or "").replace("\\", "/").strip()
    if not raw:
        raise ValueError("mount_path is required")
    if not raw.startswith("/"):
        raise ValueError("mount_path must be absolute")
    normalized = posixpath.normpath(raw)
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts[1:]):
        raise ValueError("mount_path must not contain path traversal")
    if normalized in FORBIDDEN_MOUNT_PATHS:
        raise ValueError(f"mount_path is reserved: {normalized}")
    if not normalized.startswith("/workspace/"):
        raise ValueError("mount_path must be under /workspace/")
    return normalized


def _paths_overlap(left: str, right: str) -> bool:
    left = left.rstrip("/")
    right = right.rstrip("/")
    return left == right or left.startswith(f"{right}/") or right.startswith(f"{left}/")


class Packages(BaseModel):
    apt: list[str] = Field(default_factory=list)
    pip: list[str] = Field(default_factory=list)
    npm: list[str] = Field(default_factory=list)
    cargo: list[str] = Field(default_factory=list)
    gem: list[str] = Field(default_factory=list)
    go: list[str] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not any([self.apt, self.pip, self.npm, self.cargo, self.gem, self.go])

    def install_commands(self) -> list[str]:
        cmds: list[str] = []
        if self.apt:
            cmds.append(f"apt-get update && apt-get install -y {' '.join(self.apt)}")
        if self.pip:
            cmds.append(f"pip install {' '.join(self.pip)}")
        if self.npm:
            cmds.append(f"npm install -g {' '.join(self.npm)}")
        if self.cargo:
            cmds.append(f"cargo install {' '.join(self.cargo)}")
        if self.gem:
            cmds.append(f"gem install {' '.join(self.gem)}")
        if self.go:
            cmds.append(f"go install {' '.join(self.go)}")
        return cmds


class Networking(BaseModel):
    type: str = "limited"
    allowed_hosts: list[str] = Field(default_factory=list)
    allow_package_managers: bool = False

    def is_default(self) -> bool:
        return self.type == "limited"

    @staticmethod
    def normalize_allowed_host(host: str) -> str:
        host = host.lower().strip()
        for prefix in ("https://", "http://"):
            if host.startswith(prefix):
                host = host[len(prefix) :]
        return host.rstrip("/")


class EgressServiceInject(BaseModel):
    type: str = "bearer"
    credential_field: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("credential_field", "secret_key"),
    )
    header: Optional[str] = None
    cookie_name: Optional[str] = None
    cookies: dict[str, str] = Field(default_factory=dict)

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, value: object) -> str:
        typ = str(value or "bearer").strip().lower()
        if typ not in SUPPORTED_EGRESS_INJECT_TYPES:
            raise ValueError(f"unsupported egress inject type: {typ}")
        return typ

    @field_validator("credential_field", "header", "cookie_name", mode="before")
    @classmethod
    def trim_optional_strings(cls, value: Optional[str]) -> Optional[str]:
        value = _trim_string(value)
        return value or None

    @field_validator("cookies")
    @classmethod
    def validate_cookies(cls, value: dict[str, str]) -> dict[str, str]:
        cleaned: dict[str, str] = {}
        for cookie_name, secret_key in value.items():
            name = str(cookie_name).strip()
            key = str(secret_key).strip()
            if not name or not key:
                raise ValueError("cookie mappings require non-empty cookie names and secret keys")
            if any(ch in name for ch in "=;\r\n\t"):
                raise ValueError(f"invalid cookie name: {name}")
            cleaned[name] = key
        return cleaned

    @model_validator(mode="after")
    def validate_shape(self) -> "EgressServiceInject":
        if self.type in {"api_key", "raw_header"} and self.header:
            if any(ch in self.header for ch in ":\r\n\t"):
                raise ValueError("header must be a single HTTP header name")
        if self.type == "bearer" and self.header:
            if any(ch in self.header for ch in ":\r\n\t"):
                raise ValueError("header must be a single HTTP header name")
        if self.type == "cookie":
            if self.cookie_name or self.cookies:
                raise ValueError("cookie inject uses credential_field as the full Cookie header")
        return self


class EgressService(BaseModel):
    name: str
    kind: str = "external"
    exposure: str = "placeholder"
    base_url: str
    service_credential_id: CredentialId
    inject: EgressServiceInject = Field(default_factory=EgressServiceInject)

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, value: object) -> str:
        name = str(value or "").strip().lower()
        if not _is_safe_token(name):
            raise ValueError("egress service name must contain only letters, numbers, '-' or '_'")
        return name

    @field_validator("kind", mode="before")
    @classmethod
    def validate_kind(cls, value: object) -> str:
        kind = str(value or "external").strip().lower()
        if kind not in SUPPORTED_EGRESS_KINDS:
            raise ValueError(f"unsupported egress service kind: {kind}")
        return kind

    @field_validator("exposure", mode="before")
    @classmethod
    def validate_exposure(cls, value: object) -> str:
        exposure = str(value or "placeholder").strip().lower()
        if exposure not in SUPPORTED_EGRESS_EXPOSURES:
            raise ValueError("only placeholder egress exposure is currently supported")
        return exposure

    @field_validator("base_url", mode="before")
    @classmethod
    def validate_base_url(cls, value: object) -> str:
        raw = str(value or "").strip()
        parsed = urlparse(raw)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("egress service base_url must use http or https")
        if not parsed.hostname:
            raise ValueError("egress service base_url must include a host")
        if parsed.username or parsed.password:
            raise ValueError("egress service base_url must not include credentials")
        return raw


def _serialize_typed_credential_ids(value: object) -> object:
    if isinstance(value, CredentialId):
        return str(value)
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _serialize_typed_credential_ids(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_typed_credential_ids(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_serialize_typed_credential_ids(item) for item in value)
    return value


class MountResource(BaseModel):
    type: str = "storage"
    name: str
    volume_ref: str
    sub_path: str = ""
    mount_path: str
    access: str = "read_only"
    required: bool = True

    @field_validator("type", mode="before")
    @classmethod
    def validate_type(cls, value: object) -> str:
        typ = str(value or "storage").strip().lower()
        if typ not in SUPPORTED_MOUNT_RESOURCE_TYPES:
            raise ValueError(f"unsupported mount resource type: {typ}")
        return typ

    @field_validator("name", "volume_ref", mode="before")
    @classmethod
    def validate_safe_name(cls, value: object) -> str:
        text = str(value or "").strip()
        if not _is_safe_token(text):
            raise ValueError("mount name and volume_ref must contain only letters, numbers, '-' or '_'")
        return text

    @field_validator("sub_path", mode="before")
    @classmethod
    def validate_sub_path(cls, value: object) -> str:
        return normalize_safe_relative_path(str(value or ""), field_name="sub_path")

    @field_validator("mount_path", mode="before")
    @classmethod
    def validate_mount_path(cls, value: object) -> str:
        return normalize_safe_workspace_mount_path(str(value or ""))

    @field_validator("access", mode="before")
    @classmethod
    def validate_access(cls, value: object) -> str:
        access = str(value or "read_only").strip().lower()
        if access not in SUPPORTED_MOUNT_ACCESS:
            raise ValueError(f"unsupported mount access: {access}")
        return access


class EnvironmentConfig(BaseModel):
    type: str = "cloud"
    packages: Packages = Field(default_factory=Packages)
    networking: Networking = Field(default_factory=Networking)
    env_vars: dict[str, str] = Field(default_factory=dict)
    environment_credential_ids: list[CredentialId] = Field(
        default_factory=list,
        validation_alias=AliasChoices("environment_credential_ids", "secret_refs"),
    )
    egress_services: list[EgressService] = Field(default_factory=list)
    mount_resources: list[MountResource] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def decode_credential_reference_aliases(cls, value: object) -> object:
        if isinstance(value, dict):
            serialized = _serialize_typed_credential_ids(value)
            assert isinstance(serialized, dict)
            return canonicalize_environment_for_read(serialized)
        return value

    @model_validator(mode="after")
    def validate_egress_services(self) -> "EnvironmentConfig":
        names: set[str] = set()
        for service in self.egress_services:
            if service.name in names:
                raise ValueError(f"duplicate egress service name: {service.name}")
            names.add(service.name)
        return self

    @model_validator(mode="after")
    def validate_mount_resources(self) -> "EnvironmentConfig":
        names: set[str] = set()
        mount_paths: list[str] = []
        for resource in self.mount_resources:
            if resource.name in names:
                raise ValueError(f"duplicate mount resource name: {resource.name}")
            names.add(resource.name)
            for existing in mount_paths:
                if _paths_overlap(resource.mount_path, existing):
                    raise ValueError(f"mount_path overlaps with another mount: {resource.mount_path}")
            mount_paths.append(resource.mount_path)
        return self


EnvironmentCredentialReferenceSource = Literal["environment_credential_ids", "egress_services"]


class EnvironmentCredentialReference(NamedTuple):
    credential_id: CredentialId
    source: EnvironmentCredentialReferenceSource
    index: int | None = None
    path: str | None = None


def _coerce_credential_id(value: object) -> Optional[CredentialId]:
    if isinstance(value, CredentialId):
        return value
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return CredentialId.from_public(text)
    except (TypeError, ValueError):
        return None


def extract_environment_credential_references(
    config: EnvironmentConfig | dict[str, Any] | None,
) -> list[EnvironmentCredentialReference]:
    raw = config.model_dump(mode="json") if isinstance(config, EnvironmentConfig) else config
    if raw is None:
        return []
    decoded = _REFERENCE_CODEC.decode_environment(raw)
    references = [
        EnvironmentCredentialReference(
            CredentialId.from_public(str(reference.credential_id)),
            "environment_credential_ids",
            reference.index,
            (
                f"environment_credential_ids[{reference.index}]"
                if reference.index is not None
                else "service_credential_id"
            ),
        )
        for reference in decoded.direct_references
    ]
    references.extend(
        EnvironmentCredentialReference(
            CredentialId.from_public(str(reference.credential_id)),
            "egress_services",
            reference.index,
            f"egress_services[{reference.index}]",
        )
        for reference in decoded.http_egress
    )
    return references


def _normalize_request_credential_ids(config: EnvironmentConfig) -> EnvironmentConfig:
    # environment_credential_ids is already typed as list[CredentialId]; blank/invalid values are
    # rejected at field coercion. Deduplicate while preserving order.
    normalized_refs: list[CredentialId] = []
    seen: set[CredentialId] = set()
    for value in config.environment_credential_ids:
        if value in seen:
            continue
        seen.add(value)
        normalized_refs.append(value)
    return config.model_copy(update={"environment_credential_ids": normalized_refs})


class CreateEnvironmentRequest(BaseModel):
    name: str
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    config: EnvironmentConfig = Field(default_factory=EnvironmentConfig)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _validate_environment_name(value)

    @field_validator("config")
    @classmethod
    def normalize_credential_ids(cls, value: EnvironmentConfig) -> EnvironmentConfig:
        return _normalize_request_credential_ids(value)


class UpdateEnvironmentRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    config: Optional[EnvironmentConfig] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else _validate_environment_name(value)

    @field_validator("config")
    @classmethod
    def normalize_credential_ids(cls, value: Optional[EnvironmentConfig]) -> Optional[EnvironmentConfig]:
        return None if value is None else _normalize_request_credential_ids(value)


class EnvironmentResponse(BaseModel):
    id: EnvironmentId
    type: str = "environment"
    name: str
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    config: EnvironmentConfig = Field(default_factory=EnvironmentConfig)
    created_at: datetime
    updated_at: datetime
    archived_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    image_tag: Optional[str] = None
    image_version: int = 0

    model_config = ConfigDict(from_attributes=True)
