"""SQLAlchemy persistence adapter for credential resources and groups.

Owns resource-level CRUD, the flat ``data`` contract (encrypt-on-write,
mask-on-read via a default-deny display-safe whitelist), the masked-value
preservation semantics on update, lifecycle transitions, group membership, and
row-level locks used by concurrency-sensitive operations.
"""

from __future__ import annotations

import builtins
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import and_, or_, select, text, tuple_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.joysafeter_application.credentials.ports import CredentialMaterialStoragePort, MutationOutcome
from app.joysafeter_domain.credentials.dependencies import (
    CredentialImpact,
    runtime_impact_dispositions,
)
from app.joysafeter_domain.credentials.lifecycle import (
    CredentialLifecycleCommand,
    CredentialLifecycleError,
    decide_credential_lifecycle,
    decide_group_lifecycle,
)
from app.joysafeter_domain.credentials.policies import (
    CredentialGroupRestoreContext,
    CredentialPolicyError,
    CredentialPolicyErrorCode,
    canonicalize_mcp_auth_scheme,
    validate_mcp_credential_material,
)
from app.joysafeter_domain.credentials.resource import (
    CredentialGroupResource,
    CredentialMaterialDescriptor,
    CredentialResource,
    McpCredentialIdentity,
    ModelCredentialIdentity,
    ServiceCredentialIdentity,
)
from app.joysafeter_domain.credentials.types import (
    CredentialAuthScheme,
    CredentialFieldName,
    CredentialState,
    CredentialUsage,
    NormalizedMcpUrl,
    ProjectId,
    canonicalize_auth_scheme,
)
from app.joysafeter_domain.credentials.types import (
    CredentialKind as DomainCredentialKind,
)
from app.joysafeter_domain.models.joysafeter_credential import (
    JoySafeterCredential,
    JoySafeterCredentialGroup,
)
from app.joysafeter_domain.schemas.joysafeter_credential import (
    CREDENTIAL_DATA_MAX_FIELDS,
    CREDENTIAL_DATA_MAX_KEY_LENGTH,
    CREDENTIAL_DATA_MAX_VALUE_LENGTH,
    AddGroupCredentialRequest,
    CreateCredentialGroupRequest,
    CreateCredentialRequest,
    CredentialKind,
    UpdateCredentialGroupRequest,
    UpdateCredentialRequest,
)
from app.joysafeter_domain.services.joysafeter_credential_group_invariants import (
    credential_group_url_conflict,
    is_credential_group_url_integrity_error,
    reject_member_url_conflict_for_bound_sessions,
)
from app.joysafeter_shared.common.app_errors import (
    InvalidRequestError,
    NotFoundError,
    ResourceConflictError,
)
from app.joysafeter_shared.ids import CredentialGroupId, CredentialId, SessionId
from app.joysafeter_shared.mcp_url import normalize_mcp_url
from app.joysafeter_shared.security.credential_cipher import (
    CredentialCipherConfigurationError,
    CredentialCiphertextError,
)
from app.joysafeter_shared.utils.datetime import utc_now

MASKED_SECRET_PREFIX = "********"

# --- display-safe masking whitelist (ported verbatim; default-deny) -------------
_DISPLAY_SAFE_KEYS = frozenset(
    {"PROVIDER", "PROTOCOL", "MODEL", "BASE_URL", "REGION", "ENDPOINT", "API_VERSION", "VERSION"}
)
_DISPLAY_SAFE_SUFFIXES = (
    "_BASE_URL",
    "_MODEL",
    "_PROVIDER",
    "_PROTOCOL",
    "_REGION",
    "_ENDPOINT",
    "_API_VERSION",
    "_VERSION",
)


def _mcp_policy_request_error(error: CredentialPolicyError) -> InvalidRequestError:
    code = {
        CredentialPolicyErrorCode.UNSUPPORTED_SCHEME: "CREDENTIAL_AUTH_SCHEME_DISABLED",
        CredentialPolicyErrorCode.FIELD_MISSING: "CREDENTIAL_FIELD_MISSING",
        CredentialPolicyErrorCode.FIELD_INVALID: "CREDENTIAL_FIELD_INVALID",
    }.get(error.code, "CREDENTIAL_FIELD_INVALID")
    return InvalidRequestError(
        code=code,
        message=str(error),
        data=error.data,
        user_action="fix_input",
    )


def _canonicalize_mcp_auth_scheme_for_request(
    value: str | CredentialAuthScheme | None,
) -> CredentialAuthScheme:
    try:
        return canonicalize_mcp_auth_scheme(value)
    except CredentialPolicyError as error:
        raise _mcp_policy_request_error(error) from error
    except (TypeError, ValueError) as error:
        raise InvalidRequestError(
            code="CREDENTIAL_FIELD_INVALID",
            message=str(error),
            data={"field": "auth_scheme"},
            user_action="fix_input",
        ) from error


def _validate_mcp_credential_material_for_request(
    auth_scheme: CredentialAuthScheme,
    data: dict[str, str],
) -> dict[str, str]:
    try:
        return validate_mcp_credential_material(auth_scheme, data)
    except CredentialPolicyError as error:
        raise _mcp_policy_request_error(error) from error


def _is_display_safe_key(key: str) -> bool:
    """Whether a data key's value is safe to reveal in a masked response.

    Default-deny: only a small allowlist of non-sensitive config keys (base_url /
    model / provider / region / ...) is shown in cleartext. Every other key is
    masked, so a project reader can never read raw secret material via GET/list.
    """
    normalized = key.upper()
    return normalized in _DISPLAY_SAFE_KEYS or normalized.endswith(_DISPLAY_SAFE_SUFFIXES)


def _mask_value(value: str) -> str:
    if not value:
        return ""
    return MASKED_SECRET_PREFIX


def _contains_masked_placeholder(data: dict[str, str]) -> bool:
    return any(not _is_display_safe_key(key) and value.startswith(MASKED_SECRET_PREFIX) for key, value in data.items())


def _sanitize_display_value(key: str, value: str) -> str:
    if "URL" not in key.upper():
        return value
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return value
    hostname = parsed.hostname or ""
    if parsed.port is not None:
        hostname = f"{hostname}:{parsed.port}"
    return urlunsplit((parsed.scheme, hostname, parsed.path, "", ""))


def _config_references_credential(config: object, cred_id_str: str) -> bool:
    """Whether an environment ``config`` dict references the credential by id.

    Service credentials are referenced from ``environment_credential_ids`` and
    ``egress_services[].credential_ref``. Kept as a plain dict scan (no fragile
    JSONB path SQL); the set of environments per project is small.
    """
    from app.joysafeter_domain.credentials.references import CredentialReferenceCodec

    return any(
        str(credential_id) == cred_id_str
        for credential_id in CredentialReferenceCodec().decode_environment(config).credential_ids
    )


def _snapshot_references_credential(snapshot: object, cred_id_str: str) -> bool:
    """Whether a session ``agent_snapshot`` blob pins the credential by id.

    Covers the model connection (``model_credential_id``) and any credential ids
    embedded in the snapshot's frozen ``environment.config`` (a
    running session must keep a credential alive even after the agent is rebound).
    """
    from app.joysafeter_domain.credentials.references import CredentialReferenceCodec

    return any(
        str(credential_id) == cred_id_str
        for credential_id in CredentialReferenceCodec().decode_snapshot(snapshot).credential_ids
    )


def _environment_credential_usages(config: object, cred_id_str: str) -> set[CredentialUsage]:
    from app.joysafeter_domain.credentials.references import CredentialReferenceCodec

    decoded = CredentialReferenceCodec().decode_environment(config)
    usages: set[CredentialUsage] = set()
    if any(str(credential_id) == cred_id_str for credential_id in decoded.direct_credential_ids):
        usages.add(CredentialUsage.ENVIRONMENT_INJECTION)
    if any(str(reference.credential_id) == cred_id_str for reference in decoded.http_egress):
        usages.add(CredentialUsage.HTTP_EGRESS)
    return usages


def _snapshot_credential_usages(snapshot: object, cred_id_str: str) -> set[CredentialUsage]:
    from app.joysafeter_domain.credentials.references import CredentialReferenceCodec

    decoded = CredentialReferenceCodec().decode_snapshot(snapshot)
    usages: set[CredentialUsage] = set()
    if any(str(reference.credential_id) == cred_id_str for reference in decoded.environment_references):
        usages.add(CredentialUsage.ENVIRONMENT_INJECTION)
    if any(str(reference.credential_id) == cred_id_str for reference in decoded.http_egress):
        usages.add(CredentialUsage.HTTP_EGRESS)
    return usages


@dataclass
class CredentialDependencies:
    """The live consumers referencing a credential (agent/trigger/env/session)."""

    agent_ids: list = field(default_factory=list)
    trigger_ids: list = field(default_factory=list)
    environment_ids: list = field(default_factory=list)
    session_ids: list = field(default_factory=list)

    @property
    def in_use(self) -> bool:
        return bool(self.agent_ids or self.trigger_ids or self.environment_ids or self.session_ids)

    def as_data(self) -> dict:
        return {
            "agents": [str(x) for x in self.agent_ids],
            "triggers": [str(x) for x in self.trigger_ids],
            "environments": [str(x) for x in self.environment_ids],
            "sessions": [str(x) for x in self.session_ids],
        }


def _credential_state(row: JoySafeterCredential | JoySafeterCredentialGroup) -> CredentialState:
    if row.deleted_at is not None:
        return CredentialState.DELETED
    if row.archived_at is not None:
        return CredentialState.ARCHIVED
    return CredentialState.ACTIVE


def _auth_scheme(value: str | None) -> CredentialAuthScheme:
    return canonicalize_auth_scheme(value or CredentialAuthScheme.STATIC_BEARER)


def _require_stored_credential_data(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise CredentialCiphertextError("Stored credential data must be a JSON object")
    for key, stored_value in value.items():
        if not isinstance(key, str) or not isinstance(stored_value, str):
            raise CredentialCiphertextError("Stored credential key and value must be a string")
    return value


def map_credential_row(row: JoySafeterCredential) -> CredentialResource:
    kind = DomainCredentialKind(row.kind)
    if kind is DomainCredentialKind.MODEL:
        identity = ModelCredentialIdentity(provider_id=row.provider or "", protocol_id=row.protocol or "")
    elif kind is DomainCredentialKind.SERVICE:
        identity = ServiceCredentialIdentity(auth_scheme=_auth_scheme(row.credential_type))
    else:
        if row.group_id is None or row.normalized_mcp_server_url is None:
            raise ValueError("MCP credential row is missing group or normalized server URL")
        identity = McpCredentialIdentity(
            group_id=row.group_id,
            server_url=NormalizedMcpUrl(row.normalized_mcp_server_url),
            auth_scheme=_auth_scheme(row.credential_type),
        )
    return CredentialResource(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        kind=kind,
        identity=identity,
        material=CredentialMaterialDescriptor(
            frozenset(CredentialFieldName(field_name) for field_name in _require_stored_credential_data(row.data))
        ),
        state=_credential_state(row),
        is_default=row.is_default,
    )


def map_credential_group_row(row: JoySafeterCredentialGroup) -> CredentialGroupResource:
    return CredentialGroupResource(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        state=_credential_state(row),
    )


def _usage_for_kind(kind: str) -> CredentialUsage:
    if kind == DomainCredentialKind.MODEL.value:
        return CredentialUsage.MODEL_INFERENCE
    if kind == DomainCredentialKind.MCP.value:
        return CredentialUsage.MCP_EGRESS
    return CredentialUsage.HTTP_EGRESS


class SqlAlchemyCredentialRepository:
    def __init__(
        self,
        db: AsyncSession,
        *,
        material: CredentialMaterialStoragePort,
    ) -> None:
        self.db = db
        self._material = material
        self._pending_impacts: list[CredentialImpact] = []

    async def _finish_write(self) -> None:
        await self.db.flush()

    def _queue_impact(
        self,
        *,
        project_id: ProjectId,
        reason: str,
        source_type: str,
        source_id: str,
        usage: CredentialUsage,
    ) -> None:
        self._pending_impacts.append(
            CredentialImpact(
                usage=usage,
                source=source_type,
                source_id=source_id,
                reason=reason,
                project_id=project_id,
                affected_sandbox_ids=frozenset(),
                affected_session_ids=frozenset(),
                dispositions=runtime_impact_dispositions(usage),
            )
        )

    def take_pending_impacts(self) -> tuple[CredentialImpact, ...]:
        pending, self._pending_impacts = tuple(self._pending_impacts), []
        return pending

    def clear_pending_impacts(self) -> None:
        self._pending_impacts.clear()

    # --- data contract / crypto / masking ---------------------------------------

    @staticmethod
    def _validate_data_contract(data: dict[str, str] | None) -> dict[str, str]:
        """Enforce the flat ``dict[str, str]`` contract + size bounds.

        Rejects nested/non-string values and oversize maps with
        ``CREDENTIAL_FIELD_INVALID``.
        """
        raw = data or {}
        if len(raw) > CREDENTIAL_DATA_MAX_FIELDS:
            raise InvalidRequestError(
                code="CREDENTIAL_FIELD_INVALID",
                message=f"Credential data may not exceed {CREDENTIAL_DATA_MAX_FIELDS} fields",
                data={"field_count": len(raw), "max": CREDENTIAL_DATA_MAX_FIELDS},
                user_action="fix_input",
            )
        clean: dict[str, str] = {}
        for key, value in raw.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise InvalidRequestError(
                    code="CREDENTIAL_FIELD_INVALID",
                    message="Credential data must be a flat mapping of string keys to string values",
                    data={"key": str(key)},
                    user_action="fix_input",
                )
            if len(key) > CREDENTIAL_DATA_MAX_KEY_LENGTH:
                raise InvalidRequestError(
                    code="CREDENTIAL_FIELD_INVALID",
                    message=f"Credential data key length may not exceed {CREDENTIAL_DATA_MAX_KEY_LENGTH}",
                    data={"key": key[:32], "max": CREDENTIAL_DATA_MAX_KEY_LENGTH},
                    user_action="fix_input",
                )
            if len(value) > CREDENTIAL_DATA_MAX_VALUE_LENGTH:
                raise InvalidRequestError(
                    code="CREDENTIAL_FIELD_INVALID",
                    message=f"Credential data value length may not exceed {CREDENTIAL_DATA_MAX_VALUE_LENGTH}",
                    data={"key": key, "max": CREDENTIAL_DATA_MAX_VALUE_LENGTH},
                    user_action="fix_input",
                )
            clean[key] = value
        return clean

    def encrypt_data_for_storage(self, data: dict[str, str] | None) -> dict[str, str]:
        return self._material.protect_values(data)

    def decrypt_data(self, data: object) -> dict[str, str]:
        return self._material.reveal_values(_require_stored_credential_data(data))

    async def load_encrypted_material(
        self,
        credential_id: CredentialId,
        project_id: ProjectId,
    ) -> dict[str, str]:
        credential = await self._get_or_raise(
            credential_id,
            project_id=project_id,
        )
        return dict(_require_stored_credential_data(credential.data))

    def get_credential_data(self, cred: JoySafeterCredential | None) -> dict[str, str]:
        if not cred:
            return {}
        return self.decrypt_data(cred.data)

    def mask_data(self, data: dict[str, str]) -> dict[str, str]:
        return {key: value if _is_display_safe_key(key) else _mask_value(value) for key, value in data.items()}

    def get_masked(self, cred: JoySafeterCredential | None) -> dict[str, str]:
        if not cred:
            return {}
        masked: dict[str, str] = {}
        for key, encrypted_value in _require_stored_credential_data(cred.data).items():
            if not _is_display_safe_key(key):
                masked[key] = _mask_value(encrypted_value)
                continue
            try:
                value = self._material.reveal_values({key: encrypted_value})[key]
            except CredentialCiphertextError:
                masked[key] = MASKED_SECRET_PREFIX
            else:
                masked[key] = _sanitize_display_value(key, value)
        return masked

    def merge_update_plaintext(
        self,
        current_data: dict | None,
        requested_data: dict[str, str] | None,
        *,
        existing_plaintext: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Build update plaintext, preserving unchanged masked sensitive values.

        An incoming value equal to the masked form of the existing value keeps the
        ORIGINAL plaintext (never persists "********..."). A masked value for a key
        that is NOT present in the existing data is ambiguous → CREDENTIAL_MASK_CONFLICT.
        """
        existing_plain = existing_plaintext
        if existing_plain is None:
            existing_plain = self._decrypt_existing_material_for_update(current_data)
        next_data: dict[str, str] = {}
        for key, value in (requested_data or {}).items():
            key_str = str(key)
            value_str = str(value)
            looks_masked = not _is_display_safe_key(key_str) and value_str.startswith(MASKED_SECRET_PREFIX)
            if looks_masked and key_str in existing_plain and value_str == _mask_value(existing_plain[key_str]):
                next_data[key_str] = existing_plain[key_str]
            elif looks_masked and key_str not in existing_plain:
                raise InvalidRequestError(
                    code="CREDENTIAL_MASK_CONFLICT",
                    message="A masked value was submitted for a field with no stored value to preserve",
                    data={"key": key_str},
                    user_action="fix_input",
                )
            else:
                next_data[key_str] = value_str
        return next_data

    def _decrypt_existing_material_for_update(self, current_data: object) -> dict[str, str]:
        try:
            return self.decrypt_data(current_data)
        except (CredentialCipherConfigurationError, CredentialCiphertextError) as exc:
            raise InvalidRequestError(
                code="CREDENTIAL_MATERIAL_UNREADABLE",
                message="Stored credential material cannot be preserved; re-enter all fields to replace it",
                data={"required_action": "replace_all_fields"},
                user_action="fix_input",
            ) from exc

    # --- kind validation (mirror the DB CHECK) ----------------------------------

    @staticmethod
    def _validate_kind_identity_create(req: CreateCredentialRequest) -> None:
        kind = req.kind
        if kind is CredentialKind.MODEL:
            if not req.provider or not req.protocol:
                raise InvalidRequestError(
                    code="CREDENTIAL_FIELD_MISSING",
                    message="model credentials require provider and protocol",
                    data={"kind": kind.value},
                    user_action="fix_input",
                )
            if req.mcp_server_url is not None or req.group_id is not None:
                raise InvalidRequestError(
                    code="CREDENTIAL_FIELD_INVALID",
                    message="model credentials must not define mcp_server_url or group_id",
                    data={"kind": kind.value},
                    user_action="fix_input",
                )
        elif kind is CredentialKind.MCP:
            if not req.mcp_server_url or req.group_id is None:
                raise InvalidRequestError(
                    code="CREDENTIAL_FIELD_MISSING",
                    message="mcp credentials require mcp_server_url and group_id",
                    data={"kind": kind.value},
                    user_action="fix_input",
                )
            if req.provider is not None or req.protocol is not None:
                raise InvalidRequestError(
                    code="CREDENTIAL_FIELD_INVALID",
                    message="mcp credentials must not define provider or protocol",
                    data={"kind": kind.value},
                    user_action="fix_input",
                )
            if req.is_default:
                raise InvalidRequestError(
                    code="CREDENTIAL_FIELD_INVALID",
                    message="mcp credentials cannot be a default",
                    data={"kind": kind.value},
                    user_action="fix_input",
                )
        elif kind is CredentialKind.SERVICE:
            if (
                req.provider is not None
                or req.protocol is not None
                or req.mcp_server_url is not None
                or req.group_id is not None
            ):
                raise InvalidRequestError(
                    code="CREDENTIAL_FIELD_INVALID",
                    message="service credentials must not define provider/protocol/mcp_server_url/group_id",
                    data={"kind": kind.value},
                    user_action="fix_input",
                )
            if req.is_default:
                raise InvalidRequestError(
                    code="CREDENTIAL_FIELD_INVALID",
                    message="service credentials cannot be a default",
                    data={"kind": kind.value},
                    user_action="fix_input",
                )
        else:  # pragma: no cover - StrEnum is exhaustive
            raise InvalidRequestError(
                code="CREDENTIAL_KIND_INVALID",
                message=f"Unknown credential kind '{kind}'",
                data={"kind": str(kind)},
                user_action="fix_input",
            )

    # --- name conflict helpers ---------------------------------------------------

    @staticmethod
    def _name_conflict(name: str) -> ResourceConflictError:
        return ResourceConflictError(
            code="CREDENTIAL_NAME_EXISTS",
            message=f"A credential named '{name}' already exists for this kind in the project",
            data={"name": name},
            user_action="fix_input",
        )

    @staticmethod
    def _is_name_integrity_error(exc: IntegrityError) -> bool:
        message = str(getattr(exc, "orig", None) or exc).lower()
        return "uq_credentials_project_kind_name" in message or (
            "joysafeter_credentials" in message and "name" in message and "unique" in message
        )

    async def _name_exists(self, project_id: ProjectId, kind: str, name: str) -> bool:
        result = await self.db.execute(
            select(JoySafeterCredential.id).where(
                JoySafeterCredential.project_id == project_id,
                JoySafeterCredential.kind == kind,
                JoySafeterCredential.name == name,
                JoySafeterCredential.deleted_at.is_(None),
            )
        )
        return result.first() is not None

    # --- CRUD --------------------------------------------------------------------

    async def create(
        self,
        credential_id: CredentialId,
        req: CreateCredentialRequest,
        project_id: ProjectId,
    ) -> JoySafeterCredential:
        self._validate_kind_identity_create(req)
        plaintext = self._validate_data_contract(req.data)
        mcp_auth_scheme = None
        if req.kind is CredentialKind.MCP:
            mcp_auth_scheme = _canonicalize_mcp_auth_scheme_for_request(req.auth_scheme)
            plaintext = _validate_mcp_credential_material_for_request(mcp_auth_scheme, plaintext)

        normalized_url = None
        if req.kind is CredentialKind.MCP:
            assert req.mcp_server_url is not None
            assert req.group_id is not None
            normalized_url = normalize_mcp_url(req.mcp_server_url)
            await self.lock_credential_group(req.group_id, project_id=project_id)
            await self._require_member_group_active(req.group_id, project_id)
            await reject_member_url_conflict_for_bound_sessions(
                self.db,
                group_id=req.group_id,
                normalized_url=normalized_url,
                project_id=project_id,
            )
        if req.kind is CredentialKind.MODEL and req.is_default:
            await self.lock_default_scope(project_id=project_id, protocol=req.protocol or "")
            await self._clear_default(project_id=project_id, protocol=req.protocol or "")

        cred = JoySafeterCredential(
            id=credential_id,
            project_id=project_id,
            kind=req.kind.value,
            name=req.name,
            data=self.encrypt_data_for_storage(plaintext),
            provider=req.provider,
            protocol=req.protocol,
            is_default=req.is_default,
            mcp_server_url=req.mcp_server_url,
            normalized_mcp_server_url=normalized_url,
            credential_type=mcp_auth_scheme.value if mcp_auth_scheme is not None else None,
            group_id=req.group_id,
        )
        self.db.add(cred)
        try:
            await self.db.flush()
            if req.kind is CredentialKind.MCP:
                self._queue_impact(
                    project_id=project_id,
                    source_type="credential_group",
                    source_id=str(req.group_id),
                    reason="credential_group_member_created",
                    usage=CredentialUsage.MCP_EGRESS,
                )
            await self._finish_write()
        except IntegrityError as exc:
            if is_credential_group_url_integrity_error(exc):
                raise credential_group_url_conflict(normalized_url or "") from exc
            if self._is_name_integrity_error(exc):
                raise self._name_conflict(req.name) from exc
            raise
        await self.db.refresh(cred)
        return cred

    async def get(self, cred_id: CredentialId, project_id: ProjectId) -> Optional[JoySafeterCredential]:
        conditions: list[ColumnElement[bool]] = [
            JoySafeterCredential.id == cred_id,
            JoySafeterCredential.project_id == project_id,
            JoySafeterCredential.deleted_at.is_(None),
        ]
        result = await self.db.execute(select(JoySafeterCredential).where(and_(*conditions)))
        return result.scalar_one_or_none()

    async def get_resource(
        self,
        credential_id: CredentialId,
        project_id: ProjectId,
    ) -> CredentialResource | None:
        result = await self.db.execute(
            select(JoySafeterCredential).where(
                JoySafeterCredential.id == credential_id,
                JoySafeterCredential.project_id == project_id,
            )
        )
        row = result.scalar_one_or_none()
        return None if row is None else map_credential_row(row)

    async def get_group(self, group_id: CredentialGroupId, project_id: ProjectId) -> CredentialGroupResource | None:
        result = await self.db.execute(
            select(JoySafeterCredentialGroup).where(
                JoySafeterCredentialGroup.id == group_id,
                JoySafeterCredentialGroup.project_id == project_id,
            )
        )
        row = result.scalar_one_or_none()
        return None if row is None else map_credential_group_row(row)

    async def get_group_row(
        self, group_id: CredentialGroupId, project_id: ProjectId
    ) -> JoySafeterCredentialGroup | None:
        result = await self.db.execute(
            select(JoySafeterCredentialGroup).where(
                JoySafeterCredentialGroup.id == group_id,
                JoySafeterCredentialGroup.project_id == project_id,
                JoySafeterCredentialGroup.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def _get_group_lifecycle_or_raise(
        self, group_id: CredentialGroupId, project_id: ProjectId
    ) -> JoySafeterCredentialGroup:
        result = await self.db.execute(
            select(JoySafeterCredentialGroup).where(
                JoySafeterCredentialGroup.id == group_id,
                JoySafeterCredentialGroup.project_id == project_id,
            )
        )
        group = result.scalar_one_or_none()
        if group is None:
            raise NotFoundError(
                code="CREDENTIAL_GROUP_NOT_FOUND",
                message="Credential group not found",
                data={"credential_group_id": str(group_id)},
            )
        return group

    @staticmethod
    def _require_active_group(group: JoySafeterCredentialGroup) -> None:
        if group.deleted_at is not None:
            raise NotFoundError(
                code="CREDENTIAL_GROUP_NOT_FOUND",
                message="Credential group not found",
                data={"credential_group_id": str(group.id)},
            )
        if group.archived_at is not None:
            raise ResourceConflictError(
                code="CREDENTIAL_GROUP_ARCHIVED",
                message="Archived credential groups cannot be mutated",
                data={"credential_group_id": str(group.id)},
                user_action="refresh",
            )

    async def _require_member_group_active(
        self, group_id: CredentialGroupId | None, project_id: ProjectId
    ) -> JoySafeterCredentialGroup | None:
        if group_id is None:
            return None
        group = await self._get_group_lifecycle_or_raise(group_id, project_id)
        self._require_active_group(group)
        return group

    async def get_many(
        self,
        group_ids: tuple[CredentialGroupId, ...],
        project_id: ProjectId,
    ) -> tuple[CredentialGroupResource, ...]:
        result = await self.db.execute(
            select(JoySafeterCredentialGroup)
            .where(
                JoySafeterCredentialGroup.id.in_(group_ids),
                JoySafeterCredentialGroup.project_id == project_id,
            )
            .order_by(JoySafeterCredentialGroup.id)
        )
        return tuple(map_credential_group_row(row) for row in result.scalars().all())

    async def list_members(
        self,
        group_ids: tuple[CredentialGroupId, ...],
        project_id: ProjectId,
    ) -> tuple[CredentialResource, ...]:
        result = await self.db.execute(
            select(JoySafeterCredential)
            .where(
                JoySafeterCredential.group_id.in_(group_ids),
                JoySafeterCredential.project_id == project_id,
                JoySafeterCredential.archived_at.is_(None),
                JoySafeterCredential.deleted_at.is_(None),
            )
            .order_by(JoySafeterCredential.id)
        )
        return tuple(map_credential_row(row) for row in result.scalars().all())

    async def _get_or_raise(self, cred_id: CredentialId, project_id: ProjectId) -> JoySafeterCredential:
        cred = await self.get(cred_id, project_id=project_id)
        if cred is None:
            raise NotFoundError(
                code="CREDENTIAL_NOT_FOUND",
                message="Credential not found",
                data={"credential_id": str(cred_id)},
            )
        return cred

    async def _get_lifecycle_or_raise(self, cred_id: CredentialId, project_id: ProjectId) -> JoySafeterCredential:
        result = await self.db.execute(
            select(JoySafeterCredential).where(
                JoySafeterCredential.id == cred_id,
                JoySafeterCredential.project_id == project_id,
            )
        )
        credential = result.scalar_one_or_none()
        if credential is None:
            raise NotFoundError(
                code="CREDENTIAL_NOT_FOUND",
                message="Credential not found",
                data={"credential_id": str(cred_id)},
            )
        return credential

    @staticmethod
    def _require_active_credential(credential: JoySafeterCredential) -> None:
        if credential.deleted_at is not None:
            raise NotFoundError(
                code="CREDENTIAL_NOT_FOUND",
                message="Credential not found",
                data={"credential_id": str(credential.id)},
            )
        if credential.archived_at is not None:
            raise ResourceConflictError(
                code="CREDENTIAL_ARCHIVED",
                message="Archived credentials cannot be mutated",
                data={"credential_id": str(credential.id)},
                user_action="refresh",
            )

    async def lock_default_scope(self, *, project_id: ProjectId, protocol: str) -> None:
        scope = f"joysafeter:credential-default:{project_id}:{protocol}"
        await self.db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
            {"scope": scope},
        )

    async def _lock_default_selection(
        self,
        credential: JoySafeterCredential,
    ) -> JoySafeterCredential:
        if credential.protocol is None:
            return credential
        await self.lock_default_scope(
            project_id=credential.project_id,
            protocol=credential.protocol,
        )
        current_ids = (
            (
                await self.db.execute(
                    select(JoySafeterCredential.id).where(
                        JoySafeterCredential.project_id == credential.project_id,
                        JoySafeterCredential.kind == CredentialKind.MODEL.value,
                        JoySafeterCredential.protocol == credential.protocol,
                        JoySafeterCredential.is_default.is_(True),
                        JoySafeterCredential.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        await self.lock_credentials(
            [credential.id, *current_ids],
            project_id=credential.project_id,
        )
        return await self._get_lifecycle_or_raise(credential.id, credential.project_id)

    async def list(
        self,
        project_id: ProjectId,
        kind: CredentialKind | str | None = None,
        name: str | None = None,
        provider: str | None = None,
        protocol: str | None = None,
        compatible_engine: str | None = None,
        include_archived: bool | None = None,
        limit: int = 20,
        after_id: Optional[CredentialId] = None,
    ) -> tuple[list[JoySafeterCredential], bool]:
        q = select(JoySafeterCredential).where(
            JoySafeterCredential.project_id == project_id,
            JoySafeterCredential.deleted_at.is_(None),
        )
        if include_archived is False:
            q = q.where(JoySafeterCredential.archived_at.is_(None))
        if kind is not None:
            kind_value = kind.value if isinstance(kind, CredentialKind) else kind
            q = q.where(JoySafeterCredential.kind == kind_value)
        if name is not None:
            q = q.where(JoySafeterCredential.name == name)
        if provider is not None:
            q = q.where(JoySafeterCredential.provider == provider)
        if protocol is not None:
            q = q.where(JoySafeterCredential.protocol == protocol)
        if compatible_engine is not None:
            # Import locally to avoid coupling the service module to the LLM
            # catalog at import time.
            from app.joysafeter_domain.llm.compatibility import (
                compatible_provider_protocol_pairs,
            )

            pairs = compatible_provider_protocol_pairs(compatible_engine)
            q = q.where(
                JoySafeterCredential.kind == CredentialKind.MODEL.value,
                tuple_(JoySafeterCredential.provider, JoySafeterCredential.protocol).in_(pairs),
            )
        if after_id:
            cursor_is_default = (
                select(JoySafeterCredential.is_default).where(JoySafeterCredential.id == after_id).scalar_subquery()
            )
            cursor_created_at = (
                select(JoySafeterCredential.created_at).where(JoySafeterCredential.id == after_id).scalar_subquery()
            )
            q = q.where(
                or_(
                    JoySafeterCredential.is_default < cursor_is_default,
                    and_(
                        JoySafeterCredential.is_default == cursor_is_default,
                        or_(
                            JoySafeterCredential.created_at < cursor_created_at,
                            and_(
                                JoySafeterCredential.created_at == cursor_created_at,
                                JoySafeterCredential.id < after_id,
                            ),
                        ),
                    ),
                )
            )
        q = q.order_by(
            JoySafeterCredential.is_default.desc(),
            JoySafeterCredential.created_at.desc(),
            JoySafeterCredential.id.desc(),
        ).limit(limit + 1)
        result = await self.db.execute(q)
        rows = list(result.scalars().all())
        has_more = len(rows) > limit
        return rows[:limit], has_more

    async def update(
        self,
        cred_id: CredentialId,
        req: UpdateCredentialRequest,
        project_id: ProjectId,
    ) -> MutationOutcome[JoySafeterCredential]:
        preliminary = await self._get_lifecycle_or_raise(cred_id, project_id=project_id)
        if req.is_default:
            cred = await self._lock_default_selection(preliminary)
        else:
            await self.lock_credential_scope(cred_id, project_id=project_id)
            cred = await self._get_lifecycle_or_raise(cred_id, project_id=project_id)
        self._require_active_credential(cred)
        await self._require_member_group_active(cred.group_id, project_id)

        if req.is_default is not None and req.is_default and cred.kind != CredentialKind.MODEL.value:
            raise InvalidRequestError(
                code="CREDENTIAL_FIELD_INVALID",
                message="Only model credentials can be a default",
                data={"credential_id": str(cred_id), "kind": cred.kind},
                user_action="fix_input",
            )

        changed = False
        runtime_material_changed = False
        if req.name is not None and req.name != cred.name:
            if await self._name_exists(project_id, cred.kind, req.name):
                raise self._name_conflict(req.name)
            cred.name = req.name
            changed = True

        current_mcp_scheme = None
        target_mcp_scheme = None
        mcp_scheme_changed = False
        if cred.kind == CredentialKind.MCP.value:
            current_mcp_scheme = _canonicalize_mcp_auth_scheme_for_request(cred.credential_type)
            target_mcp_scheme = (
                current_mcp_scheme
                if req.auth_scheme is None
                else _canonicalize_mcp_auth_scheme_for_request(req.auth_scheme)
            )
            mcp_scheme_changed = target_mcp_scheme is not current_mcp_scheme

        if req.data is not None or mcp_scheme_changed:
            requested_data = self._validate_data_contract(req.data) if req.data is not None else None
            preserves_masked_values = requested_data is not None and _contains_masked_placeholder(requested_data)
            requires_current_plaintext = requested_data is None or preserves_masked_values
            if requires_current_plaintext:
                current_plaintext = self._decrypt_existing_material_for_update(cred.data)
            else:
                try:
                    current_plaintext = self.decrypt_data(cred.data)
                except (CredentialCipherConfigurationError, CredentialCiphertextError):
                    current_plaintext = None
            if mcp_scheme_changed:
                if requested_data is None:
                    assert current_plaintext is not None
                    merged = {"token_value": current_plaintext["token_value"]}
                elif preserves_masked_values:
                    assert current_plaintext is not None
                    merged = self.merge_update_plaintext(
                        cred.data,
                        requested_data,
                        existing_plaintext=current_plaintext,
                    )
                else:
                    merged = requested_data
            elif preserves_masked_values:
                assert current_plaintext is not None
                merged = self.merge_update_plaintext(
                    cred.data,
                    requested_data,
                    existing_plaintext=current_plaintext,
                )
            else:
                assert requested_data is not None
                merged = requested_data
            merged = self._validate_data_contract(merged)
            if cred.kind == CredentialKind.MCP.value:
                assert target_mcp_scheme is not None
                merged = _validate_mcp_credential_material_for_request(
                    target_mcp_scheme,
                    merged,
                )
            if current_plaintext is None or merged != current_plaintext:
                cred.data = self.encrypt_data_for_storage(merged)
                changed = True
                runtime_material_changed = True
            if mcp_scheme_changed:
                assert target_mcp_scheme is not None
                cred.credential_type = target_mcp_scheme.value
                changed = True
                runtime_material_changed = True

        if req.is_default is not None and cred.kind == CredentialKind.MODEL.value:
            if req.is_default != cred.is_default:
                if req.is_default:
                    await self._clear_default(project_id=project_id, protocol=cred.protocol or "")
                cred.is_default = req.is_default
                changed = True

        if not changed:
            return MutationOutcome(cred, False)
        cred.updated_at = utc_now()
        if runtime_material_changed:
            await self._mark_sandboxes_pending_for(cred, reason="credential_updated")
        try:
            await self._finish_write()
        except IntegrityError as exc:
            if req.name is not None and self._is_name_integrity_error(exc):
                raise self._name_conflict(req.name) from exc
            raise
        await self.db.refresh(cred)
        return MutationOutcome(cred, True)

    # --- default (model only) ----------------------------------------------------

    async def _mark_sandboxes_pending_for(self, cred: JoySafeterCredential, *, reason: str) -> None:
        if cred.kind == CredentialKind.MCP.value and cred.group_id is not None:
            self._queue_impact(
                project_id=cred.project_id,
                source_type="credential_group",
                source_id=str(cred.group_id),
                reason=reason,
                usage=CredentialUsage.MCP_EGRESS,
            )
            return
        if cred.kind == CredentialKind.SERVICE.value:
            usages = await self._service_credential_usages(cred)
            for usage in usages:
                self._queue_impact(
                    project_id=cred.project_id,
                    source_type="credential",
                    source_id=str(cred.id),
                    reason=reason,
                    usage=usage,
                )
            return
        self._queue_impact(
            project_id=cred.project_id,
            source_type="credential",
            source_id=str(cred.id),
            reason=reason,
            usage=_usage_for_kind(cred.kind),
        )

    async def _queue_mcp_group_impact_if_active(self, cred: JoySafeterCredential, *, reason: str) -> None:
        if cred.kind != CredentialKind.MCP.value or cred.group_id is None:
            return
        if not await self.active_group_session_ids(cred.group_id, cred.project_id):
            return
        self._queue_impact(
            project_id=cred.project_id,
            source_type="credential_group",
            source_id=str(cred.group_id),
            reason=reason,
            usage=CredentialUsage.MCP_EGRESS,
        )

    async def _service_credential_usages(
        self,
        cred: JoySafeterCredential,
    ) -> tuple[CredentialUsage, ...]:
        from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
        from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession

        cred_id_str = str(cred.id)
        usages: set[CredentialUsage] = set()
        environment_rows = await self.db.execute(
            select(JoySafeterEnvironment.config).where(
                JoySafeterEnvironment.project_id == cred.project_id,
                JoySafeterEnvironment.deleted_at.is_(None),
                JoySafeterEnvironment.archived_at.is_(None),
            )
        )
        for config in environment_rows.scalars().all():
            usages.update(_environment_credential_usages(config, cred_id_str))

        snapshot_rows = await self.db.execute(
            select(JoySafeterSession.agent_snapshot).where(
                JoySafeterSession.project_id == cred.project_id,
                JoySafeterSession.archived_at.is_(None),
                JoySafeterSession.status != "terminated",
                JoySafeterSession.environment_id.is_(None),
                JoySafeterSession.agent_snapshot.is_not(None),
            )
        )
        for snapshot in snapshot_rows.scalars().all():
            usages.update(_snapshot_credential_usages(snapshot, cred_id_str))

        return tuple(usage for usage in CredentialUsage if usage in usages)

    # --- default (model only) ----------------------------------------------------

    async def _clear_default(self, *, project_id: ProjectId, protocol: str) -> None:
        await self.db.execute(
            update(JoySafeterCredential)
            .where(
                JoySafeterCredential.project_id == project_id,
                JoySafeterCredential.kind == CredentialKind.MODEL.value,
                JoySafeterCredential.protocol == protocol,
                JoySafeterCredential.is_default.is_(True),
                JoySafeterCredential.deleted_at.is_(None),
            )
            .values(is_default=False, updated_at=utc_now())
        )
        await self.db.flush()

    async def set_default(self, cred_id: CredentialId, project_id: ProjectId) -> JoySafeterCredential:
        preliminary = await self._get_lifecycle_or_raise(cred_id, project_id=project_id)
        cred = await self._lock_default_selection(preliminary)
        self._require_active_credential(cred)
        if cred.kind != CredentialKind.MODEL.value or not cred.protocol:
            raise InvalidRequestError(
                code="CREDENTIAL_FIELD_INVALID",
                message="Only model credentials can be selected as defaults",
                data={"credential_id": str(cred_id), "kind": cred.kind},
                user_action="fix_input",
            )
        await self._clear_default(project_id=project_id, protocol=cred.protocol)
        cred.is_default = True
        cred.updated_at = utc_now()
        await self._mark_sandboxes_pending_for(cred, reason="credential_default_set")
        await self._finish_write()
        await self.db.refresh(cred)
        return cred

    async def clear_default(self, cred_id: CredentialId, project_id: ProjectId) -> JoySafeterCredential:
        await self.lock_credential_scope(cred_id, project_id=project_id)
        cred = await self._get_lifecycle_or_raise(cred_id, project_id=project_id)
        self._require_active_credential(cred)
        cred.is_default = False
        cred.updated_at = utc_now()
        await self._finish_write()
        await self.db.refresh(cred)
        return cred

    # --- cross-consumer dependency scan -----------------------------------------

    async def dependencies(self, cred_id: CredentialId, project_id: ProjectId) -> CredentialDependencies:
        """Find the live consumers that reference this credential.

        Union of: agent ``model_credential_id``, trigger
        ``webhook_auth_credential_id``, environment ``config`` (service credentials
        via ``environment_credential_ids`` / ``egress_services``), the session→group association (an
        mcp credential is reachable through its group), and ACTIVE session
        ``agent_snapshot`` blobs. Soft-deleted / archived
        consumers and terminated/archived sessions are excluded so lifecycle
        transitions are only blocked by genuinely live references.
        """
        from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
        from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
        from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
        from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger

        await self._get_or_raise(cred_id, project_id=project_id)
        cred_id_str = str(cred_id)
        deps = CredentialDependencies()

        # Agents (live model connection column).
        agent_rows = await self.db.execute(
            select(JoySafeterAgent.id).where(
                JoySafeterAgent.model_credential_id == cred_id,
                JoySafeterAgent.project_id == project_id,
                JoySafeterAgent.deleted_at.is_(None),
            )
        )
        deps.agent_ids = list(agent_rows.scalars().all())

        # Triggers (inbound webhook auth column).
        trigger_rows = await self.db.execute(
            select(JoySafeterTrigger.id).where(
                JoySafeterTrigger.webhook_auth_credential_id == cred_id,
                JoySafeterTrigger.project_id == project_id,
                JoySafeterTrigger.deleted_at.is_(None),
            )
        )
        deps.trigger_ids = list(trigger_rows.scalars().all())

        # Environments (service creds embedded in the JSONB config).
        env_query = select(JoySafeterEnvironment.id, JoySafeterEnvironment.config).where(
            JoySafeterEnvironment.project_id == project_id,
            JoySafeterEnvironment.deleted_at.is_(None),
        )
        env_rows = await self.db.execute(env_query)
        deps.environment_ids = [
            env_id for env_id, config in env_rows.all() if _config_references_credential(config, cred_id_str)
        ]

        # Sessions only block a Resource lifecycle when the frozen Snapshot pins
        # that Resource directly. Session→Group association blocks Group
        # lifecycle, but is refresh impact (not a member Resource blocker).
        session_ids: dict = {}  # ordered set
        snap_rows = await self.db.execute(
            select(JoySafeterSession.id, JoySafeterSession.agent_snapshot).where(
                JoySafeterSession.project_id == project_id,
                JoySafeterSession.archived_at.is_(None),
                JoySafeterSession.status != "terminated",
                JoySafeterSession.agent_snapshot.is_not(None),
            )
        )
        for session_id, snapshot in snap_rows.all():
            if _snapshot_references_credential(snapshot, cred_id_str):
                session_ids[session_id] = None
        deps.session_ids = list(session_ids.keys())

        return deps

    # --- lifecycle ---------------------------------------------------------------
    # archive/soft_delete reject when the credential is still referenced by a live
    # consumer (agent / trigger / environment / active session or its snapshot);
    # FK RESTRICT only guards a physical delete, so the service enforces the rest.

    async def archive(self, cred_id: CredentialId, project_id: ProjectId) -> MutationOutcome[JoySafeterCredential]:
        await self.lock_credential_scope(cred_id, project_id=project_id)
        cred = await self._get_lifecycle_or_raise(cred_id, project_id=project_id)
        await self._require_member_group_active(cred.group_id, project_id)
        resource = map_credential_row(cred)
        decision = decide_credential_lifecycle(resource, CredentialLifecycleCommand.ARCHIVE)
        if resource.state is decision.state:
            return MutationOutcome(cred, False)
        cred.archived_at = utc_now()
        if cred.is_default:
            cred.is_default = False
        cred.updated_at = utc_now()
        await self._queue_mcp_group_impact_if_active(cred, reason="credential_archived")
        await self._finish_write()
        await self.db.refresh(cred)
        return MutationOutcome(cred, True)

    async def restore(self, cred_id: CredentialId, project_id: ProjectId) -> MutationOutcome[JoySafeterCredential]:
        await self.lock_credential_scope(cred_id, project_id=project_id)
        cred = await self._get_lifecycle_or_raise(cred_id, project_id=project_id)
        await self._require_member_group_active(cred.group_id, project_id)
        resource = map_credential_row(cred)
        try:
            decision = decide_credential_lifecycle(resource, CredentialLifecycleCommand.RESTORE)
        except CredentialLifecycleError as exc:
            if "OAUTH2_LEGACY_DISABLED" in str(exc):
                raise InvalidRequestError(
                    code="CREDENTIAL_AUTH_SCHEME_DISABLED",
                    message="Legacy MCP OAuth credentials cannot be restored",
                    data={"credential_id": str(cred_id)},
                    user_action="fix_input",
                ) from exc
            raise ResourceConflictError(
                code="CREDENTIAL_STATE_INVALID",
                message=str(exc),
                data={"credential_id": str(cred_id)},
                user_action="refresh",
            ) from exc
        if resource.state is decision.state:
            return MutationOutcome(cred, False)
        if cred.kind == CredentialKind.MCP.value:
            assert cred.group_id is not None
            assert cred.normalized_mcp_server_url is not None
            await reject_member_url_conflict_for_bound_sessions(
                self.db,
                group_id=cred.group_id,
                normalized_url=cred.normalized_mcp_server_url,
                project_id=project_id,
            )
        cred.archived_at = None
        cred.updated_at = utc_now()
        # Restore re-enables a credential that environments may still reference,
        # so live sessions must refresh to pick up the reactivated material.
        # Archive/soft_delete intentionally do NOT mark SERVICE sandboxes: the
        # lifecycle coordinator blocks those while a session is live-referencing,
        # and refreshing an archived credential cannot succeed anyway.
        if cred.kind == CredentialKind.MCP.value:
            await self._queue_mcp_group_impact_if_active(cred, reason="credential_group_member_restored")
        elif cred.kind == CredentialKind.SERVICE.value:
            await self._mark_sandboxes_pending_for(cred, reason="credential_restored")
        await self._finish_write()
        await self.db.refresh(cred)
        return MutationOutcome(cred, True)

    async def soft_delete(self, cred_id: CredentialId, project_id: ProjectId) -> MutationOutcome[JoySafeterCredential]:
        await self.lock_credential_scope(cred_id, project_id=project_id)
        cred = await self._get_lifecycle_or_raise(cred_id, project_id=project_id)
        await self._require_member_group_active(cred.group_id, project_id)
        resource = map_credential_row(cred)
        decision = decide_credential_lifecycle(resource, CredentialLifecycleCommand.DELETE)
        if resource.state is decision.state:
            return MutationOutcome(cred, False)
        deleted_at = utc_now()
        cred.data = {}
        # oauth_config holds OAuth client_secret/refresh_token ciphertext for MCP
        # credentials; it is a material-bearing column and must be erased alongside
        # data so material_erased_at cannot falsely claim erasure.
        cred.oauth_config = None
        cred.material_erased_at = deleted_at
        cred.deleted_at = deleted_at
        if cred.is_default:
            cred.is_default = False
        cred.updated_at = utc_now()
        await self._queue_mcp_group_impact_if_active(cred, reason="credential_deleted")
        await self._finish_write()
        await self.db.refresh(cred)
        return MutationOutcome(cred, True)

    # --- concurrency lock --------------------------------------------------------

    async def lock_credentials(
        self,
        cred_ids: builtins.list[CredentialId],
        *,
        project_id: ProjectId | None = None,
    ) -> builtins.list[CredentialId]:
        """Lock credential rows in stable id order within the current transaction."""
        ordered_ids: builtins.list[CredentialId] = sorted(
            set(cred_ids),
            key=str,
        )
        if not ordered_ids:
            return []
        conditions: builtins.list[ColumnElement[bool]] = [JoySafeterCredential.id.in_(ordered_ids)]
        if project_id is not None:
            conditions.append(JoySafeterCredential.project_id == project_id)
        result = await self.db.execute(
            select(JoySafeterCredential.id).where(and_(*conditions)).order_by(JoySafeterCredential.id).with_for_update()
        )
        return list(result.scalars().all())

    async def lock_credential_groups(
        self,
        group_ids: builtins.list[CredentialGroupId],
        *,
        project_id: ProjectId | None = None,
    ) -> builtins.list[CredentialGroupId]:
        ordered_ids = sorted(
            set(group_ids),
            key=str,
        )
        if not ordered_ids:
            return []
        conditions: builtins.list[ColumnElement[bool]] = [JoySafeterCredentialGroup.id.in_(ordered_ids)]
        if project_id is not None:
            conditions.append(JoySafeterCredentialGroup.project_id == project_id)
        result = await self.db.execute(
            select(JoySafeterCredentialGroup.id)
            .where(and_(*conditions))
            .order_by(JoySafeterCredentialGroup.id)
            .with_for_update()
        )
        return list(result.scalars().all())

    async def lock_credential_group(
        self,
        group_id: CredentialGroupId | None,
        *,
        project_id: ProjectId | None = None,
    ) -> None:
        if group_id is None:
            return
        conditions = [JoySafeterCredentialGroup.id == group_id]
        if project_id is not None:
            conditions.append(JoySafeterCredentialGroup.project_id == project_id)
        await self.db.execute(select(JoySafeterCredentialGroup.id).where(and_(*conditions)).with_for_update())

    async def lock_credential_scope(
        self,
        cred_id: CredentialId,
        *,
        project_id: ProjectId,
    ) -> None:
        result = await self.db.execute(
            select(
                JoySafeterCredential.group_id,
                JoySafeterCredential.kind,
                JoySafeterCredential.protocol,
            ).where(
                JoySafeterCredential.id == cred_id,
                JoySafeterCredential.project_id == project_id,
            )
        )
        row = result.one_or_none()
        if row is None:
            return
        group_id, kind, protocol = row
        await self.lock_credential_group(group_id, project_id=project_id)
        if kind == CredentialKind.MODEL.value and protocol:
            await self.lock_default_scope(project_id=project_id, protocol=protocol)
        await self.lock_credential(cred_id, project_id=project_id)

    async def lock_credential(
        self,
        cred_id: CredentialId,
        *,
        project_id: ProjectId | None = None,
    ) -> None:
        """Acquire a row-level ``SELECT ... FOR UPDATE`` lock on the credential.

        Used by later concurrency-sensitive tasks (e.g. grant issuance) to
        serialize writers against a single credential row within a transaction.
        """
        await self.lock_credentials([cred_id], project_id=project_id)

    # --- credential groups ------------------------------------------------------

    async def create_group(
        self,
        group_id: CredentialGroupId,
        request: CreateCredentialGroupRequest,
        project_id: ProjectId,
    ) -> JoySafeterCredentialGroup:
        group = JoySafeterCredentialGroup(
            id=group_id,
            project_id=project_id,
            name=request.name,
            description=request.description,
            metadata_=request.metadata,
        )
        self.db.add(group)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            if "uq_credential_groups_project_name" in str(getattr(exc, "orig", exc)).lower():
                raise ResourceConflictError(
                    code="CREDENTIAL_GROUP_NAME_EXISTS",
                    message=f"A credential group named '{request.name}' already exists in this project",
                    data={"name": request.name},
                    user_action="fix_input",
                ) from exc
            raise
        await self.db.refresh(group)
        return group

    async def list_group_rows(
        self,
        project_id: ProjectId,
        *,
        limit: int = 20,
        after_id: CredentialGroupId | None = None,
        include_archived: bool = False,
    ) -> tuple[list[JoySafeterCredentialGroup], bool]:
        query = select(JoySafeterCredentialGroup).where(
            JoySafeterCredentialGroup.project_id == project_id,
            JoySafeterCredentialGroup.deleted_at.is_(None),
        )
        if not include_archived:
            query = query.where(JoySafeterCredentialGroup.archived_at.is_(None))
        if after_id is not None:
            cursor_created_at = (
                select(JoySafeterCredentialGroup.created_at)
                .where(JoySafeterCredentialGroup.id == after_id)
                .scalar_subquery()
            )
            query = query.where(
                or_(
                    JoySafeterCredentialGroup.created_at < cursor_created_at,
                    and_(
                        JoySafeterCredentialGroup.created_at == cursor_created_at,
                        JoySafeterCredentialGroup.id < after_id,
                    ),
                )
            )
        rows = (
            (
                await self.db.execute(
                    query.order_by(
                        JoySafeterCredentialGroup.created_at.desc(),
                        JoySafeterCredentialGroup.id.desc(),
                    ).limit(limit + 1)
                )
            )
            .scalars()
            .all()
        )
        return list(rows[:limit]), len(rows) > limit

    async def update_group(
        self,
        group_id: CredentialGroupId,
        request: UpdateCredentialGroupRequest,
        project_id: ProjectId,
    ) -> JoySafeterCredentialGroup:
        await self.lock_credential_group(group_id, project_id=project_id)
        group = await self._get_group_lifecycle_or_raise(group_id, project_id)
        self._require_active_group(group)
        if request.name is not None:
            group.name = request.name
        if request.description is not None:
            group.description = request.description
        if request.metadata is not None:
            group.metadata_ = request.metadata
        group.updated_at = utc_now()
        try:
            await self.db.flush()
        except IntegrityError as exc:
            if "uq_credential_groups_project_name" in str(getattr(exc, "orig", exc)).lower():
                raise ResourceConflictError(
                    code="CREDENTIAL_GROUP_NAME_EXISTS",
                    message=f"A credential group named '{request.name}' already exists in this project",
                    data={"name": request.name},
                    user_action="fix_input",
                ) from exc
            raise
        await self.db.refresh(group)
        return group

    async def active_group_session_ids(self, group_id: CredentialGroupId, project_id: ProjectId) -> list[SessionId]:
        from app.joysafeter_domain.models.joysafeter_credential import (
            JoySafeterSessionCredentialGroup,
        )
        from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession

        rows = await self.db.execute(
            select(JoySafeterSessionCredentialGroup.session_id)
            .join(JoySafeterSession, JoySafeterSession.id == JoySafeterSessionCredentialGroup.session_id)
            .where(
                JoySafeterSessionCredentialGroup.credential_group_id == group_id,
                JoySafeterSession.project_id == project_id,
                JoySafeterSession.archived_at.is_(None),
                JoySafeterSession.status != "terminated",
            )
        )
        return list(rows.scalars().all())

    async def archive_group(
        self, group_id: CredentialGroupId, project_id: ProjectId
    ) -> MutationOutcome[JoySafeterCredentialGroup]:
        await self.lock_credential_group(group_id, project_id=project_id)
        group = await self._get_group_lifecycle_or_raise(group_id, project_id)
        decision = decide_group_lifecycle(map_credential_group_row(group), CredentialLifecycleCommand.ARCHIVE)
        if map_credential_group_row(group).state is decision.state:
            return MutationOutcome(group, False)
        group.archived_at = utc_now()
        group.updated_at = utc_now()
        self._queue_impact(
            project_id=project_id,
            source_type="credential_group",
            source_id=str(group_id),
            reason="credential_group_archived",
            usage=CredentialUsage.MCP_EGRESS,
        )
        await self.db.flush()
        await self.db.refresh(group)
        return MutationOutcome(group, True)

    async def restore_group(
        self, group_id: CredentialGroupId, project_id: ProjectId
    ) -> MutationOutcome[JoySafeterCredentialGroup]:
        await self.lock_credential_group(group_id, project_id=project_id)
        group = await self._get_group_lifecycle_or_raise(group_id, project_id)
        group_resource = map_credential_group_row(group)
        if group_resource.state is CredentialState.ACTIVE:
            return MutationOutcome(group, False)
        member_rows = (
            (
                await self.db.execute(
                    select(JoySafeterCredential).where(
                        JoySafeterCredential.group_id == group_id,
                        JoySafeterCredential.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        members = tuple(map_credential_row(member) for member in member_rows)
        try:
            decide_group_lifecycle(
                group_resource,
                CredentialLifecycleCommand.RESTORE,
                restore_context=CredentialGroupRestoreContext(
                    project_id=project_id,
                    members=members,
                    occupied_server_urls=frozenset(),
                ),
            )
            for member in member_rows:
                if member.archived_at is not None:
                    continue
                await reject_member_url_conflict_for_bound_sessions(
                    self.db,
                    group_id=group_id,
                    normalized_url=member.normalized_mcp_server_url or "",
                    project_id=project_id,
                )
        except (CredentialLifecycleError, ValueError) as exc:
            raise ResourceConflictError(
                code="CREDENTIAL_STATE_INVALID",
                message=str(exc),
                data={"credential_group_id": str(group_id)},
                user_action="refresh",
            ) from exc
        group.archived_at = None
        group.updated_at = utc_now()
        self._queue_impact(
            project_id=project_id,
            source_type="credential_group",
            source_id=str(group_id),
            reason="credential_group_restored",
            usage=CredentialUsage.MCP_EGRESS,
        )
        await self.db.flush()
        await self.db.refresh(group)
        return MutationOutcome(group, True)

    async def delete_group(
        self, group_id: CredentialGroupId, project_id: ProjectId
    ) -> MutationOutcome[JoySafeterCredentialGroup]:
        await self.lock_credential_group(group_id, project_id=project_id)
        group = await self._get_group_lifecycle_or_raise(group_id, project_id)
        group_resource = map_credential_group_row(group)
        decision = decide_group_lifecycle(group_resource, CredentialLifecycleCommand.DELETE)
        if group_resource.state is decision.state:
            return MutationOutcome(group, False)
        deleted_at = utc_now()
        await self.db.execute(
            update(JoySafeterCredential)
            .where(
                JoySafeterCredential.group_id == group_id,
                JoySafeterCredential.project_id == project_id,
                JoySafeterCredential.deleted_at.is_(None),
            )
            .values(
                data={},
                oauth_config=None,
                material_erased_at=deleted_at,
                deleted_at=deleted_at,
                is_default=False,
                updated_at=deleted_at,
            )
        )
        group.deleted_at = deleted_at
        group.updated_at = deleted_at
        self._queue_impact(
            project_id=project_id,
            source_type="credential_group",
            source_id=str(group_id),
            reason="credential_group_deleted",
            usage=CredentialUsage.MCP_EGRESS,
        )
        await self.db.flush()
        await self.db.refresh(group)
        return MutationOutcome(group, True)

    async def add_group_member(
        self,
        group_id: CredentialGroupId,
        credential_id: CredentialId,
        request: AddGroupCredentialRequest,
        project_id: ProjectId,
    ) -> JoySafeterCredential:
        return await self.create(
            credential_id,
            CreateCredentialRequest(
                kind=CredentialKind.MCP,
                name=request.name,
                mcp_server_url=request.mcp_server_url,
                group_id=group_id,
                data=request.data,
                auth_scheme=request.auth_scheme,
            ),
            project_id,
        )

    async def list_group_member_rows(
        self,
        group_id: CredentialGroupId,
        project_id: ProjectId,
        *,
        include_archived: bool = True,
    ) -> list[JoySafeterCredential]:
        await self._get_group_lifecycle_or_raise(group_id, project_id)
        query = select(JoySafeterCredential).where(
            JoySafeterCredential.project_id == project_id,
            JoySafeterCredential.group_id == group_id,
            JoySafeterCredential.kind == CredentialKind.MCP.value,
            JoySafeterCredential.deleted_at.is_(None),
        )
        if not include_archived:
            query = query.where(JoySafeterCredential.archived_at.is_(None))
        rows = await self.db.execute(
            query.order_by(JoySafeterCredential.created_at.desc(), JoySafeterCredential.id.desc())
        )
        return list(rows.scalars().all())

    async def _get_member_or_raise(
        self, group_id: CredentialGroupId, credential_id: CredentialId, project_id: ProjectId
    ) -> JoySafeterCredential:
        credential = await self._get_lifecycle_or_raise(credential_id, project_id)
        if credential.group_id != group_id or credential.kind != CredentialKind.MCP.value:
            raise NotFoundError(
                code="CREDENTIAL_NOT_FOUND",
                message="Credential not found in group",
                data={
                    "credential_id": str(credential_id),
                    "credential_group_id": str(group_id),
                },
            )
        return credential

    async def validate_group_member_mutation(
        self, group_id: CredentialGroupId, credential_id: CredentialId, project_id: ProjectId
    ) -> JoySafeterCredential:
        await self._require_member_group_active(group_id, project_id)
        return await self._get_member_or_raise(group_id, credential_id, project_id)

    async def archive_group_member(
        self, group_id: CredentialGroupId, credential_id: CredentialId, project_id: ProjectId
    ) -> JoySafeterCredential:
        await self._get_member_or_raise(group_id, credential_id, project_id)
        return await self.archive(credential_id, project_id)

    async def delete_group_member(
        self, group_id: CredentialGroupId, credential_id: CredentialId, project_id: ProjectId
    ) -> JoySafeterCredential:
        await self._get_member_or_raise(group_id, credential_id, project_id)
        return await self.soft_delete(credential_id, project_id)
