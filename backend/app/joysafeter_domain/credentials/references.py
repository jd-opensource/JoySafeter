from __future__ import annotations

import copy
import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from .types import (
    CREDENTIAL_FIELD_NAME_MAX_LENGTH,
    CredentialGroupId,
    CredentialId,
    ProjectId,
    make_credential_id,
    require_identifier,
    require_non_empty_text,
    require_project_id,
)

_REFERENCE_CONTRACT = json.loads(
    (Path(__file__).resolve().parents[3] / "contracts" / "credential_reference_contract.json").read_text()
)
_SNAPSHOT_SCHEMA_VALUES = _REFERENCE_CONTRACT["snapshot_schemas"]
_CANONICAL_KEYS = frozenset(_REFERENCE_CONTRACT["canonical_reference_keys"])
_LEGACY_KEYS = frozenset(_REFERENCE_CONTRACT["legacy_decoder_keys"])
_REGISTERED_KEYS = _CANONICAL_KEYS | _LEGACY_KEYS
_SNAPSHOT_CODEC_REFERENCE_PATHS = frozenset(
    {
        "$.model_credential_id",
        "$.environment_credential_ids[*]",
        "$.environment.config.environment_credential_ids[*]",
        "$.environment.config.secret_refs[*]",
        "$.environment.config.egress_services[*].service_credential_id",
        "$.environment.config.egress_services[*].credential_ref",
        "$.environment.config.egress_services[*].inject.credential_field",
        "$.environment.config.egress_services[*].inject.secret_key",
        "$.secret_ref",
        "$.secret_refs[*]",
    }
)
_ENVIRONMENT_CODEC_REFERENCE_PATHS = frozenset(
    {
        "$.environment_credential_ids[*]",
        "$.secret_refs[*]",
        "$.egress_services[*].service_credential_id",
        "$.egress_services[*].credential_ref",
        "$.egress_services[*].inject.credential_field",
        "$.egress_services[*].inject.secret_key",
        "$.service_credential_id",
    }
)
CODEC_SUPPORTED_REFERENCE_PATHS = frozenset(
    {
        *(
            (document, path)
            for document in ("agent_version_snapshot", "active_session_snapshot")
            for path in _SNAPSHOT_CODEC_REFERENCE_PATHS
        ),
        *(("environment_config", path) for path in _ENVIRONMENT_CODEC_REFERENCE_PATHS),
    }
)


def _validate_reference_path_inventory(reference_paths: object) -> None:
    if not isinstance(reference_paths, list | tuple):
        raise ValueError("credential reference contract paths must be a list or tuple")
    contract_paths = frozenset(
        (str(entry["document"]), str(entry["path"])) for entry in reference_paths if isinstance(entry, Mapping)
    )
    missing = CODEC_SUPPORTED_REFERENCE_PATHS - contract_paths
    unexpected = contract_paths - CODEC_SUPPORTED_REFERENCE_PATHS
    if missing:
        raise ValueError(f"credential reference contract is missing Codec-supported paths: {sorted(missing)!r}")
    if unexpected:
        raise ValueError(f"credential reference contract has unsupported paths: {sorted(unexpected)!r}")


_REFERENCE_PATHS = tuple(_REFERENCE_CONTRACT["reference_paths"])
_validate_reference_path_inventory(_REFERENCE_PATHS)
_SUPPORTED_INJECT_KINDS = frozenset({"bearer", "api_key", "raw_header", "cookie"})
_EXPLICIT_V2_FORBIDDEN_PATHS = frozenset(
    str(entry["path"])
    for entry in _REFERENCE_PATHS
    if entry["document"] != "environment_config" and "v2" not in entry["schemas"]
)


def registered_reference_paths(
    *,
    documents: frozenset[str],
    surfaces: frozenset[str],
    value_kind: str = "credential_id",
) -> frozenset[str]:
    return frozenset(
        str(entry["path"])
        for entry in _REFERENCE_PATHS
        if entry["document"] in documents and entry["surface"] in surfaces and entry["value_kind"] == value_kind
    )


def _registered_path_key_count(document: object, path: str) -> int:
    segments = path.removeprefix("$.").split(".")
    parents: list[object] = [document]
    for segment in segments[:-1]:
        expand = segment.endswith("[*]")
        key = segment[:-3] if expand else segment
        children: list[object] = []
        for parent in parents:
            if not isinstance(parent, Mapping) or key not in parent:
                continue
            child = parent[key]
            if expand:
                if isinstance(child, list):
                    children.extend(child)
            else:
                children.append(child)
        parents = children
    terminal = segments[-1]
    terminal_key = terminal[:-3] if terminal.endswith("[*]") else terminal
    return sum(isinstance(parent, Mapping) and terminal_key in parent for parent in parents)


class CredentialReferenceKind(StrEnum):
    RESOURCE = "resource"
    GROUP = "group"


@dataclass(frozen=True, slots=True)
class CredentialReference:
    kind: CredentialReferenceKind
    project_id: ProjectId
    source: str
    source_id: str
    credential_id: CredentialId | None
    group_id: CredentialGroupId | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", require_project_id(self.project_id))
        object.__setattr__(self, "source", require_non_empty_text(self.source, label="reference source"))
        object.__setattr__(self, "source_id", require_non_empty_text(self.source_id, label="reference source id"))
        if self.kind is CredentialReferenceKind.RESOURCE:
            if self.credential_id is None or self.group_id is not None:
                raise ValueError("resource references require only a credential id")
            require_identifier(self.credential_id, label="credential id")
        elif self.kind is CredentialReferenceKind.GROUP:
            if self.group_id is None or self.credential_id is not None:
                raise ValueError("group references require only a credential group id")
            require_identifier(self.group_id, label="credential group id")
        else:
            raise TypeError("credential reference kind is invalid")


class SnapshotSchema(StrEnum):
    LEGACY_V0 = "legacy_v0"
    V1 = "v1"
    V2 = "v2"


@dataclass(frozen=True, slots=True)
class SnapshotModelReference:
    credential_id: CredentialId
    engine_kind: str
    model_id: str | None
    source_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SnapshotEnvironmentReference:
    credential_id: CredentialId
    source_path: str
    index: int | None


@dataclass(frozen=True, slots=True)
class SnapshotHttpEgressReference:
    credential_id: CredentialId
    endpoint: str
    inject_kind: str
    credential_field: str
    header: str | None
    cookie_name: str | None
    source_paths: tuple[str, ...] = ()
    index: int | None = None
    name: str | None = None
    allowed_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CanonicalCredentialReferences:
    schema: SnapshotSchema
    model: SnapshotModelReference | None
    environment_references: tuple[SnapshotEnvironmentReference, ...]
    http_egress: tuple[SnapshotHttpEgressReference, ...]

    @property
    def environment_credential_ids(self) -> tuple[CredentialId, ...]:
        return _sorted_ids(reference.credential_id for reference in self.environment_references)

    @property
    def credential_ids(self) -> tuple[CredentialId, ...]:
        values = list(self.environment_credential_ids)
        values.extend(reference.credential_id for reference in self.http_egress)
        if self.model is not None:
            values.append(self.model.credential_id)
        return _sorted_ids(values)


DecodedSnapshot = CanonicalCredentialReferences


@dataclass(frozen=True, slots=True)
class CanonicalEnvironmentReferences:
    direct_references: tuple[SnapshotEnvironmentReference, ...]
    http_egress: tuple[SnapshotHttpEgressReference, ...]

    @property
    def direct_credential_ids(self) -> tuple[CredentialId, ...]:
        return _sorted_ids(reference.credential_id for reference in self.direct_references)

    @property
    def credential_ids(self) -> tuple[CredentialId, ...]:
        return _sorted_ids([*self.direct_credential_ids, *(reference.credential_id for reference in self.http_egress)])


@dataclass(frozen=True, slots=True)
class CredentialReferenceMetricSnapshot:
    reader_versions: Mapping[tuple[str, str, str], int]
    persisted_keys: Mapping[tuple[str, str, str, str], int]


_reader_version_metrics: Counter[tuple[str, str, str]] = Counter()
_persisted_key_metrics: Counter[tuple[str, str, str, str]] = Counter()


def credential_reference_metric_snapshot() -> CredentialReferenceMetricSnapshot:
    return CredentialReferenceMetricSnapshot(
        reader_versions=MappingProxyType(dict(_reader_version_metrics)),
        persisted_keys=MappingProxyType(dict(_persisted_key_metrics)),
    )


def reset_credential_reference_metrics() -> None:
    _reader_version_metrics.clear()
    _persisted_key_metrics.clear()


def _corrupt(message: str) -> ValueError:
    return ValueError(f"corrupt_record: {message}")


def _mapping(value: object, *, label: str) -> Mapping[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if not isinstance(value, Mapping):
        raise _corrupt(f"{label} must be an object")
    return value


def _sorted_ids(values: Any) -> tuple[CredentialId, ...]:
    return tuple(sorted(set(values), key=str))


def _credential_id(value: object, *, label: str) -> CredentialId:
    try:
        return make_credential_id(value)
    except (TypeError, ValueError) as exc:
        raise _corrupt(f"{label} is invalid") from exc


def _optional_alias_id(
    document: Mapping[str, Any],
    keys: tuple[str, ...],
    *,
    label: str,
    path_prefix: str = "$",
) -> tuple[CredentialId | None, tuple[str, ...]]:
    values = []
    source_paths = []
    for key in keys:
        if key not in document or document[key] is None:
            continue
        values.append(_credential_id(document[key], label=label))
        source_paths.append(f"{path_prefix}.{key}")
    if not values:
        return None, ()
    if len(set(values)) != 1:
        raise _corrupt(f"{label} aliases conflict")
    return values[0], tuple(source_paths)


def _credential_id_occurrences(
    document: Mapping[str, Any],
    key: str,
    *,
    label: str,
    path_prefix: str = "$",
) -> tuple[SnapshotEnvironmentReference, ...]:
    if key not in document or document[key] is None:
        return ()
    values = document[key]
    if not isinstance(values, list):
        raise _corrupt(f"{label} must be a list or null")
    return tuple(
        SnapshotEnvironmentReference(
            credential_id=_credential_id(value, label=f"{label}[{index}]"),
            source_path=f"{path_prefix}.{key}[*]",
            index=index,
        )
        for index, value in enumerate(values)
    )


def _model_id(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, Mapping):
        raw_id = value.get("id")
        if raw_id is None:
            return None
        try:
            return require_non_empty_text(raw_id, label="Snapshot model id")
        except (TypeError, ValueError) as exc:
            raise _corrupt("Snapshot model id is invalid") from exc
    raise _corrupt("Snapshot model must be a string or object")


def _required_text(value: object, *, label: str, maximum: int | None = None) -> str:
    try:
        normalized = require_non_empty_text(value, label=label)
    except (TypeError, ValueError) as exc:
        raise _corrupt(f"{label} is invalid") from exc
    if maximum is not None and len(normalized) > maximum:
        raise _corrupt(f"{label} exceeds {maximum} characters")
    return normalized


def _optional_text(value: object, *, label: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, label=label)


def _alias_text(
    document: Mapping[str, Any],
    keys: tuple[str, ...],
    *,
    label: str,
    maximum: int | None = None,
    default: str | None = None,
) -> tuple[str, tuple[str, ...]]:
    values = []
    source_paths = []
    for key in keys:
        if key not in document or document[key] is None:
            continue
        values.append(_required_text(document[key], label=label, maximum=maximum))
        source_paths.append(key)
    if not values:
        if default is None:
            raise _corrupt(f"{label} is required")
        return default, ()
    if len(set(values)) != 1:
        raise _corrupt(f"{label} aliases conflict")
    return values[0], tuple(source_paths)


def _decode_http_egress(
    document: Mapping[str, Any],
    *,
    path_prefix: str,
) -> tuple[SnapshotHttpEgressReference, ...]:
    raw_services = document.get("egress_services")
    if raw_services is None:
        return ()
    if not isinstance(raw_services, list):
        raise _corrupt("HTTP egress services must be a list or null")
    references = []
    for index, service in enumerate(raw_services):
        service_mapping = _mapping(service, label=f"HTTP egress service[{index}]")
        credential_id, credential_paths = _optional_alias_id(
            service_mapping,
            ("service_credential_id", "credential_ref"),
            label=f"HTTP egress credential id[{index}]",
            path_prefix=f"{path_prefix}.egress_services[*]",
        )
        if credential_id is None:
            raise _corrupt(f"HTTP egress credential id[{index}] is required")
        endpoint = _required_text(
            service_mapping.get("base_url"),
            label=f"HTTP egress endpoint[{index}]",
        )
        raw_inject = service_mapping.get("inject")
        inject = {} if raw_inject is None else _mapping(raw_inject, label=f"HTTP egress inject[{index}]")
        inject_kind = _required_text(
            inject.get("type", "bearer"),
            label=f"HTTP egress inject kind[{index}]",
        ).lower()
        if inject_kind not in _SUPPORTED_INJECT_KINDS:
            raise _corrupt(f"HTTP egress inject kind[{index}] is unsupported")
        credential_field, field_keys = _alias_text(
            inject,
            ("credential_field", "secret_key"),
            label=f"HTTP egress credential field[{index}]",
            maximum=CREDENTIAL_FIELD_NAME_MAX_LENGTH,
            default={
                "bearer": "ACCESS_TOKEN",
                "api_key": "API_KEY",
                "raw_header": "API_KEY",
                "cookie": "COOKIE_HEADER",
            }[inject_kind],
        )
        allowed_paths = service_mapping.get("allowed_paths")
        if allowed_paths is None:
            normalized_allowed_paths = ()
        elif isinstance(allowed_paths, list):
            normalized_allowed_paths = tuple(
                _required_text(value, label=f"HTTP egress allowed path[{index}]") for value in allowed_paths
            )
        else:
            raise _corrupt(f"HTTP egress allowed paths[{index}] must be a list or null")
        references.append(
            SnapshotHttpEgressReference(
                credential_id=credential_id,
                endpoint=endpoint,
                inject_kind=inject_kind,
                credential_field=credential_field,
                header=_optional_text(inject.get("header"), label=f"HTTP egress header[{index}]"),
                cookie_name=_optional_text(
                    inject.get("cookie_name"),
                    label=f"HTTP egress cookie name[{index}]",
                ),
                source_paths=(
                    *credential_paths,
                    *(f"{path_prefix}.egress_services[*].inject.{key}" for key in field_keys),
                ),
                index=index,
                name=_optional_text(service_mapping.get("name"), label=f"HTTP egress name[{index}]"),
                allowed_paths=normalized_allowed_paths,
            )
        )
    return tuple(references)


def _safe_snapshot_schema_label(document: object) -> str:
    if not isinstance(document, Mapping):
        return "unknown"
    raw_schema = document.get("schema")
    if raw_schema is None:
        return "legacy_v0"
    for name, value in _SNAPSHOT_SCHEMA_VALUES.items():
        if value == raw_schema:
            return name
    return "unknown"


def _record_persisted_keys(document: object, *, document_kind: str, version: str) -> None:
    if document_kind == "snapshot":
        contract_documents = {"agent_version_snapshot", "active_session_snapshot"}
        contract_schema = version
    elif document_kind == "environment":
        contract_documents = {"environment_config"}
        contract_schema = "live"
    else:
        return

    registered_paths = {
        str(entry["path"])
        for entry in _REFERENCE_PATHS
        if entry["document"] in contract_documents and contract_schema in entry["schemas"]
    }
    for path in sorted(registered_paths):
        count = _registered_path_key_count(document, path)
        if count == 0:
            continue
        key = path.rsplit(".", 1)[-1].removesuffix("[*]")
        _persisted_key_metrics[(document_kind, version, path, key)] += count


class CredentialReferenceCodec:
    def decode_snapshot(self, raw: object) -> CanonicalCredentialReferences:
        schema_label = _safe_snapshot_schema_label(raw)
        try:
            document = _mapping(raw, label="Snapshot")
            raw_schema = document.get("schema")
            schema = next(
                (SnapshotSchema(name) for name, value in _SNAPSHOT_SCHEMA_VALUES.items() if value == raw_schema),
                None,
            )
            if schema is None:
                raise _corrupt("unknown explicit Snapshot schema")
            if schema is SnapshotSchema.V2 and any(
                _registered_path_key_count(document, path) for path in _EXPLICIT_V2_FORBIDDEN_PATHS
            ):
                raise _corrupt("legacy alias is not allowed in explicit v2 Snapshot")

            model_credential_id, source_paths = _optional_alias_id(
                document,
                ("model_credential_id", "secret_ref"),
                label="Snapshot model credential id",
            )
            model = None
            if model_credential_id is not None:
                model = SnapshotModelReference(
                    credential_id=model_credential_id,
                    engine_kind=_required_text(
                        document.get("engine_kind"),
                        label="Snapshot engine kind",
                    ),
                    model_id=_model_id(document.get("model")),
                    source_paths=source_paths,
                )

            environment_references = [
                *_credential_id_occurrences(
                    document,
                    "environment_credential_ids",
                    label="Snapshot environment credential ids",
                ),
                *_credential_id_occurrences(
                    document,
                    "secret_refs",
                    label="Snapshot legacy secret refs",
                ),
            ]
            environment = document.get("environment")
            config: Mapping[str, Any] = {}
            if environment is not None:
                environment_mapping = _mapping(environment, label="Snapshot environment")
                raw_config = environment_mapping.get("config")
                if raw_config is not None:
                    config = _mapping(raw_config, label="Snapshot environment config")
            decoded_environment = self._decode_environment(config, path_prefix="$.environment.config")
            environment_references.extend(decoded_environment.direct_references)

            result = CanonicalCredentialReferences(
                schema=schema,
                model=model,
                environment_references=tuple(environment_references),
                http_egress=decoded_environment.http_egress,
            )
        except Exception:
            _reader_version_metrics[("snapshot", schema_label, "error")] += 1
            raise
        _reader_version_metrics[("snapshot", schema.value, "success")] += 1
        return result

    def decode_environment(self, raw: object) -> CanonicalEnvironmentReferences:
        try:
            result = self._decode_environment(raw, path_prefix="$")
        except Exception:
            _reader_version_metrics[("environment", "live", "error")] += 1
            raise
        _reader_version_metrics[("environment", "live", "success")] += 1
        return result

    def _decode_environment(
        self,
        raw: object,
        *,
        path_prefix: str,
    ) -> CanonicalEnvironmentReferences:
        document = _mapping(raw, label="Environment config")
        direct_references = [
            *_credential_id_occurrences(
                document,
                "environment_credential_ids",
                label="Environment credential ids",
                path_prefix=path_prefix,
            ),
            *_credential_id_occurrences(
                document,
                "secret_refs",
                label="Environment secret refs",
                path_prefix=path_prefix,
            ),
        ]
        legacy_service_id, _paths = _optional_alias_id(
            document,
            ("service_credential_id",),
            label="Environment legacy service credential id",
            path_prefix=path_prefix,
        )
        if legacy_service_id is not None:
            direct_references.append(
                SnapshotEnvironmentReference(
                    credential_id=legacy_service_id,
                    source_path=f"{path_prefix}.service_credential_id",
                    index=None,
                )
            )
        return CanonicalEnvironmentReferences(
            direct_references=tuple(direct_references),
            http_egress=_decode_http_egress(document, path_prefix=path_prefix),
        )

    def encode_snapshot(
        self,
        value: Mapping[str, object],
        *,
        version: Literal["v1", "v2"] = "v1",
    ) -> dict[str, Any]:
        if version not in {"v1", "v2"}:
            raise ValueError("Snapshot encode version must be v1 or v2")
        document = copy.deepcopy(dict(_mapping(value, label="Snapshot")))
        decoded = self.decode_snapshot(document)
        document["schema"] = _SNAPSHOT_SCHEMA_VALUES[version]

        had_model_key = "model_credential_id" in document or "secret_ref" in document
        document.pop("secret_ref", None)
        if decoded.model is not None:
            document["model_credential_id"] = str(decoded.model.credential_id)
        elif had_model_key:
            document["model_credential_id"] = None

        top_level_environment_ids = _sorted_ids(
            reference.credential_id
            for reference in decoded.environment_references
            if reference.source_path in {"$.environment_credential_ids[*]", "$.secret_refs[*]"}
        )
        had_environment_keys = "environment_credential_ids" in document or "secret_refs" in document
        document.pop("environment_credential_ids", None)
        document.pop("secret_refs", None)
        if top_level_environment_ids or had_environment_keys:
            key = "secret_refs" if version == "v1" else "environment_credential_ids"
            document[key] = [str(credential_id) for credential_id in top_level_environment_ids]

        environment = document.get("environment")
        if environment is not None:
            environment_mapping = dict(_mapping(environment, label="Snapshot environment"))
            if environment_mapping.get("config") is not None:
                environment_mapping["config"] = self._encode_environment(
                    environment_mapping["config"],
                    version=version,
                    record_metrics=False,
                )
            document["environment"] = environment_mapping

        _record_persisted_keys(document, document_kind="snapshot", version=version)
        return document

    def encode_environment(
        self,
        value: Mapping[str, object],
        *,
        version: Literal["v1", "v2"] = "v1",
    ) -> dict[str, Any]:
        return self._encode_environment(value, version=version, record_metrics=True)

    def _encode_environment(
        self,
        value: Mapping[str, object],
        *,
        version: Literal["v1", "v2"],
        record_metrics: bool,
    ) -> dict[str, Any]:
        if version not in {"v1", "v2"}:
            raise ValueError("Environment encode version must be v1 or v2")
        document = copy.deepcopy(dict(_mapping(value, label="Environment config")))
        decoded = self.decode_environment(document)
        had_direct_keys = any(
            key in document for key in ("environment_credential_ids", "secret_refs", "service_credential_id")
        )
        document.pop("environment_credential_ids", None)
        document.pop("secret_refs", None)
        document.pop("service_credential_id", None)
        if decoded.direct_credential_ids or had_direct_keys:
            key = "secret_refs" if version == "v1" else "environment_credential_ids"
            document[key] = [str(credential_id) for credential_id in decoded.direct_credential_ids]

        services = document.get("egress_services")
        if services is None:
            if "egress_services" in document:
                document["egress_services"] = []
        else:
            encoded_services = []
            for index, raw_service in enumerate(services):
                service = copy.deepcopy(dict(_mapping(raw_service, label=f"HTTP egress service[{index}]")))
                credential_id, _paths = _optional_alias_id(
                    service,
                    ("service_credential_id", "credential_ref"),
                    label=f"HTTP egress credential id[{index}]",
                )
                service.pop("credential_ref", None)
                if credential_id is not None:
                    service["service_credential_id"] = str(credential_id)
                inject_value = service.get("inject")
                if inject_value is not None:
                    inject = copy.deepcopy(dict(_mapping(inject_value, label=f"HTTP egress inject[{index}]")))
                    field, _field_keys = _alias_text(
                        inject,
                        ("credential_field", "secret_key"),
                        label=f"HTTP egress credential field[{index}]",
                        maximum=CREDENTIAL_FIELD_NAME_MAX_LENGTH,
                        default={
                            "bearer": "ACCESS_TOKEN",
                            "api_key": "API_KEY",
                            "raw_header": "API_KEY",
                            "cookie": "COOKIE_HEADER",
                        }[
                            _required_text(
                                inject.get("type", "bearer"),
                                label=f"HTTP egress inject kind[{index}]",
                            ).lower()
                        ],
                    )
                    inject.pop("credential_field", None)
                    inject.pop("secret_key", None)
                    inject["secret_key" if version == "v1" else "credential_field"] = field
                    service["inject"] = inject
                encoded_services.append(service)
            document["egress_services"] = encoded_services

        if record_metrics:
            _record_persisted_keys(document, document_kind="environment", version=version)
        return document


_CODEC = CredentialReferenceCodec()


def decode_snapshot(snapshot: object) -> DecodedSnapshot:
    return _CODEC.decode_snapshot(snapshot)


def snapshot_model_credential_id(snapshot: object) -> str | None:
    decoded = _CODEC.decode_snapshot(snapshot)
    return None if decoded.model is None else str(decoded.model.credential_id)


def decode_environment(environment: object) -> CanonicalEnvironmentReferences:
    return _CODEC.decode_environment(environment)


def encode_snapshot(
    value: Mapping[str, object],
    *,
    version: Literal["v1", "v2"] = "v1",
) -> dict[str, Any]:
    return _CODEC.encode_snapshot(value, version=version)


def encode_environment(
    value: Mapping[str, object],
    *,
    version: Literal["v1", "v2"] = "v1",
) -> dict[str, Any]:
    return _CODEC.encode_environment(value, version=version)


def canonicalize_environment_for_read(value: Mapping[str, object]) -> dict[str, Any]:
    return _CODEC._encode_environment(value, version="v1", record_metrics=False)


def build_environment_execution_snapshot(
    environment: Any,
    *,
    environment_ref: str | None,
) -> dict[str, Any] | None:
    if environment is None:
        return None
    environment_id = getattr(environment, "id", None)
    return {
        "ref": environment_ref,
        "id": str(environment_id) if environment_id is not None else None,
        "name": getattr(environment, "name", None),
        "config": encode_environment(getattr(environment, "config", None) or {}, version="v1"),
        "image_tag": getattr(environment, "image_tag", None),
        "image_version": getattr(environment, "image_version", None),
    }


def split_agent_assets(merged: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    skills: list[dict] = []
    agents: list[dict] = []
    commands: list[dict] = []
    for item in merged:
        item_copy = {key: value for key, value in item.items() if key != "target"}
        target = item.get("target")
        if target == "agents":
            agents.append(item_copy)
        elif target == "commands":
            commands.append(item_copy)
        elif target == "skills":
            skills.append(item_copy)
        else:
            raise ValueError("Agent asset target must be skills, agents, or commands")
    return skills, agents, commands


def build_agent_execution_snapshot(
    agent: Any,
    *,
    environment: Any = None,
    environment_ref: str | None = None,
    version: int | None = None,
    split_assets: tuple[list[dict], list[dict], list[dict]] | None = None,
) -> dict[str, Any]:
    skills, agents, commands = split_assets or split_agent_assets(list(agent.skills or []))
    effective_environment_ref = environment_ref if environment_ref is not None else agent.environment_ref
    snapshot: dict[str, Any] = {
        "id": str(agent.id),
        "version": version if version is not None else agent.version,
        "name": agent.name,
        "engine_kind": agent.engine_kind,
        "model": agent.model,
        "system": agent.system_prompt,
        "description": agent.description,
        "metadata": agent.metadata_,
        "env": agent.env,
        "mcp_servers": agent.mcp_servers,
        "skills": skills,
        "agents": agents,
        "commands": commands,
        "tools": agent.tools,
        "permission_mode": agent.permission_mode,
        "multiagent": agent.multiagent,
        "environment_ref": effective_environment_ref,
        "model_credential_id": str(agent.model_credential_id) if agent.model_credential_id else None,
    }
    environment_snapshot = build_environment_execution_snapshot(
        environment,
        environment_ref=effective_environment_ref,
    )
    if environment_snapshot is not None:
        snapshot["environment"] = environment_snapshot
    return encode_snapshot(snapshot, version="v1")
