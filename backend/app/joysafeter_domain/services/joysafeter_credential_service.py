"""Unified CredentialService (P0 refactor).

Owns resource-level CRUD, the flat ``data`` contract (encrypt-on-write,
mask-on-read via a default-deny display-safe whitelist), the masked-value
preservation semantics on update, lifecycle (archive/restore/soft-delete), and a
row-level ``FOR UPDATE`` lock used by later concurrency-sensitive tasks.

Ported from ``joysafeter_secret_service.py`` (encrypt/decrypt/mask/
merge_update_plaintext/``_is_display_safe_secret_key``) and extended for the
three credential kinds (model/mcp/service) mirroring the DB CHECK constraint.

Out of scope here (owned by later tasks): cross-consumer dependency scanning +
in-use rejection (Task 9), group CRUD / mcp add-member flow (Task 6), and error
catalog registration (Task 11).
"""

from __future__ import annotations

import builtins
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import and_, or_, select, tuple_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.joysafeter_api.api.v1.network_policy_refresh import (
    mark_live_sandboxes_pending,
    nudge_sandbox_network_policy_refreshes,
)
from app.joysafeter_domain.models.joysafeter_credential import (
    JoySafeterCredential,
    JoySafeterCredentialGroup,
)
from app.joysafeter_domain.schemas.joysafeter_credential import (
    CREDENTIAL_DATA_MAX_FIELDS,
    CREDENTIAL_DATA_MAX_KEY_LENGTH,
    CREDENTIAL_DATA_MAX_VALUE_LENGTH,
    CreateCredentialRequest,
    CredentialKind,
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
from app.joysafeter_shared.ids import CredentialGroupId, CredentialId, SandboxId
from app.joysafeter_shared.mcp_url import normalize_mcp_url
from app.joysafeter_shared.security.credential_cipher import (
    CredentialCipher,
    CredentialCiphertextError,
)
from app.joysafeter_shared.utils.datetime import utc_now

MASKED_SECRET_PREFIX = "********"

_cipher: Optional[CredentialCipher] = None


def _get_cipher() -> CredentialCipher:
    global _cipher
    if _cipher is None:
        from app.joysafeter_shared.config.settings import joysafeter_config

        _cipher = CredentialCipher(joysafeter_config.vault_encryption_key)
    return _cipher


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
    suffix = value[-4:] if len(value) > 4 else ""
    return f"{MASKED_SECRET_PREFIX}{suffix}"


def _config_references_credential(config: object, cred_id_str: str) -> bool:
    """Whether an environment ``config`` dict references the credential by id.

    Service credentials are referenced from ``secret_refs`` (a list of ids) and
    ``egress_services[].service_credential_id`` — both are CredentialId strings
    since Task 9c. Kept as a plain dict scan (no fragile JSONB path SQL); the set
    of environments per project is small.
    """
    if not isinstance(config, dict):
        return False
    for ref in config.get("secret_refs") or []:
        if str(ref) == cred_id_str:
            return True
    for service in config.get("egress_services") or []:
        if isinstance(service, dict) and str(service.get("service_credential_id")) == cred_id_str:
            return True
    return False


def _snapshot_references_credential(snapshot: object, cred_id_str: str) -> bool:
    """Whether a session ``agent_snapshot`` blob pins the credential by id.

    Covers the model connection (``model_credential_id``) and any credential ids
    embedded in the snapshot's frozen ``environment.config`` (audit Blocker 1: a
    running session must keep a credential alive even after the agent is rebound).
    """
    if not isinstance(snapshot, dict):
        return False
    if str(snapshot.get("model_credential_id")) == cred_id_str:
        return True
    environment = snapshot.get("environment")
    if isinstance(environment, dict) and _config_references_credential(
        environment.get("config"), cred_id_str
    ):
        return True
    return False


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


class CredentialService:
    def __init__(self, db: AsyncSession, *, auto_commit: bool = True):
        self.db = db
        self._auto_commit = auto_commit
        self._pending_network_policy_refreshes: list[
            tuple[list[SandboxId], str, str, str, str]
        ] = []
        self._cipher = _get_cipher()

    async def _finish_write(self) -> None:
        if self._auto_commit:
            await self.db.commit()
            await self.nudge_pending_network_policy_refreshes()
        else:
            await self.db.flush()

    def _queue_network_policy_refresh(
        self,
        sandbox_ids: list[SandboxId],
        *,
        project_id: str,
        reason: str,
        source_type: str,
        source_id: str,
    ) -> None:
        if sandbox_ids:
            self._pending_network_policy_refreshes.append(
                (sandbox_ids, project_id, reason, source_type, source_id)
            )

    async def nudge_pending_network_policy_refreshes(self) -> None:
        pending, self._pending_network_policy_refreshes = (
            self._pending_network_policy_refreshes,
            [],
        )
        for sandbox_ids, project_id, reason, source_type, source_id in pending:
            await nudge_sandbox_network_policy_refreshes(
                sandbox_ids,
                project_id=project_id,
                reason=reason,
                source_type=source_type,
                source_id=source_id,
            )

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

    @staticmethod
    def _validate_mcp_static_bearer_data(data: dict[str, str]) -> dict[str, str]:
        token_value = data.get("token_value", "").strip()
        if not token_value:
            raise InvalidRequestError(
                code="CREDENTIAL_FIELD_MISSING",
                message="MCP static bearer credentials require data.token_value",
                data={"field": "data.token_value"},
                user_action="fix_input",
            )
        return {**data, "token_value": token_value}

    def encrypt_data_for_storage(self, data: dict[str, str] | None) -> dict[str, str]:
        return {str(key): self._cipher.encrypt(str(value)) for key, value in (data or {}).items()}

    def decrypt_data(self, data: dict | None) -> dict[str, str]:
        decrypted: dict[str, str] = {}
        for key, value in (data or {}).items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise CredentialCiphertextError("Stored credential key and value must be a string")
            decrypted[key] = self._cipher.decrypt_stored(value)
        return decrypted

    def get_credential_data(self, cred: JoySafeterCredential | None) -> dict[str, str]:
        if not cred:
            return {}
        return self.decrypt_data(cred.data or {})

    def mask_data(self, data: dict[str, str]) -> dict[str, str]:
        return {
            key: value if _is_display_safe_key(key) else _mask_value(value) for key, value in data.items()
        }

    def get_masked(self, cred: JoySafeterCredential | None) -> dict[str, str]:
        return self.mask_data(self.get_credential_data(cred))

    def merge_update_plaintext(
        self,
        current_data: dict | None,
        requested_data: dict[str, str] | None,
    ) -> dict[str, str]:
        """Build update plaintext, preserving unchanged masked sensitive values.

        An incoming value equal to the masked form of the existing value keeps the
        ORIGINAL plaintext (never persists "********..."). A masked value for a key
        that is NOT present in the existing data is ambiguous → CREDENTIAL_MASK_CONFLICT.
        """
        existing_plain = self.decrypt_data(current_data or {})
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

    async def _name_exists(self, project_id: str, kind: str, name: str) -> bool:
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

    async def create(self, req: CreateCredentialRequest, project_id: str) -> JoySafeterCredential:
        self._validate_kind_identity_create(req)
        plaintext = self._validate_data_contract(req.data)
        if req.kind is CredentialKind.MCP:
            plaintext = self._validate_mcp_static_bearer_data(plaintext)

        normalized_url = None
        if req.kind is CredentialKind.MCP:
            assert req.mcp_server_url is not None
            assert req.group_id is not None
            normalized_url = normalize_mcp_url(req.mcp_server_url)
            await self.lock_credential_group(req.group_id, project_id=project_id)
            await reject_member_url_conflict_for_bound_sessions(
                self.db,
                group_id=req.group_id,
                normalized_url=normalized_url,
                project_id=project_id,
            )
        if req.kind is CredentialKind.MODEL and req.is_default:
            await self._clear_default(project_id=project_id, protocol=req.protocol or "")

        cred = JoySafeterCredential(
            project_id=project_id,
            kind=req.kind.value,
            name=req.name,
            data=self.encrypt_data_for_storage(plaintext),
            provider=req.provider,
            protocol=req.protocol,
            is_default=req.is_default,
            mcp_server_url=req.mcp_server_url,
            normalized_mcp_server_url=normalized_url,
            credential_type="static_bearer" if req.kind is CredentialKind.MCP else None,
            group_id=req.group_id,
        )
        self.db.add(cred)
        try:
            await self.db.flush()
            if req.kind is CredentialKind.MCP:
                sandbox_ids = await mark_live_sandboxes_pending(
                    self.db,
                    project_id=project_id,
                    source_type="credential_group",
                    source_id=str(req.group_id),
                )
                self._queue_network_policy_refresh(
                    sandbox_ids,
                    project_id=project_id,
                    reason="credential_group_member_created",
                    source_type="credential_group",
                    source_id=str(req.group_id),
                )
            await self._finish_write()
        except IntegrityError as exc:
            await self.db.rollback()
            if is_credential_group_url_integrity_error(exc):
                raise credential_group_url_conflict(normalized_url or "") from exc
            if self._is_name_integrity_error(exc):
                raise self._name_conflict(req.name) from exc
            raise
        await self.db.refresh(cred)
        return cred

    async def get(self, cred_id: CredentialId, project_id: str) -> Optional[JoySafeterCredential]:
        conditions: list[ColumnElement[bool]] = [
            JoySafeterCredential.id == cred_id,
            JoySafeterCredential.project_id == project_id,
            JoySafeterCredential.deleted_at.is_(None),
        ]
        result = await self.db.execute(select(JoySafeterCredential).where(and_(*conditions)))
        return result.scalar_one_or_none()

    async def _get_or_raise(self, cred_id: CredentialId, project_id: str) -> JoySafeterCredential:
        cred = await self.get(cred_id, project_id=project_id)
        if cred is None:
            raise NotFoundError(
                code="CREDENTIAL_NOT_FOUND",
                message="Credential not found",
                data={"credential_id": str(cred_id)},
            )
        return cred

    async def list(
        self,
        project_id: str,
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
                select(JoySafeterCredential.is_default)
                .where(JoySafeterCredential.id == after_id)
                .scalar_subquery()
            )
            cursor_created_at = (
                select(JoySafeterCredential.created_at)
                .where(JoySafeterCredential.id == after_id)
                .scalar_subquery()
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
        project_id: str,
    ) -> JoySafeterCredential:
        await self.lock_credential_scope(cred_id, project_id=project_id)
        cred = await self._get_or_raise(cred_id, project_id=project_id)

        if req.is_default is not None and req.is_default and cred.kind != CredentialKind.MODEL.value:
            raise InvalidRequestError(
                code="CREDENTIAL_FIELD_INVALID",
                message="Only model credentials can be a default",
                data={"credential_id": str(cred_id), "kind": cred.kind},
                user_action="fix_input",
            )

        if req.name is not None and req.name != cred.name:
            if await self._name_exists(project_id, cred.kind, req.name):
                raise self._name_conflict(req.name)
            cred.name = req.name

        if req.data is not None:
            merged = self.merge_update_plaintext(cred.data, req.data)
            merged = self._validate_data_contract(merged)
            if cred.kind == CredentialKind.MCP.value:
                merged = self._validate_mcp_static_bearer_data(merged)
            cred.data = self.encrypt_data_for_storage(merged)

        if req.is_default is not None and cred.kind == CredentialKind.MODEL.value:
            if req.is_default:
                await self._clear_default(project_id=project_id, protocol=cred.protocol or "")
            cred.is_default = req.is_default

        cred.updated_at = utc_now()
        await self._mark_sandboxes_pending_for(cred, reason="credential_updated")
        try:
            await self._finish_write()
        except IntegrityError as exc:
            await self.db.rollback()
            if req.name is not None and self._is_name_integrity_error(exc):
                raise self._name_conflict(req.name) from exc
            raise
        await self.db.refresh(cred)
        return cred

    # --- default (model only) ----------------------------------------------------

    async def _mark_sandboxes_pending_for(
        self, cred: JoySafeterCredential, *, reason: str
    ) -> None:
        """Mark live limited-networking sandboxes ``pending`` in THIS transaction.

        Called by the mutation methods that change already-referenced material
        (update/archive/soft_delete/set_default) BEFORE their own commit, so the
        credential change and the sandbox pending-mark commit together atomically.
        There is no window where the DB holds the new/rotated/revoked credential
        while a sandbox is never flagged for re-push (audit Blocker 5).

        No commit and no Redis nudge here: the caller commits, and the durable
        ``pending`` reconcile loop converges regardless. Post-commit nudging is
        left to the route/wrapper. New model/service credentials are excluded;
        MCP member creation refreshes through its credential-group scope.
        """
        sandbox_ids = await mark_live_sandboxes_pending(
            self.db,
            project_id=cred.project_id,
            source_type="credential",
            source_id=str(cred.id),
        )
        self._queue_network_policy_refresh(
            sandbox_ids,
            project_id=cred.project_id,
            reason=reason,
            source_type="credential",
            source_id=str(cred.id),
        )

    # --- default (model only) ----------------------------------------------------

    async def _clear_default(self, *, project_id: str, protocol: str) -> None:
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

    async def set_default(self, cred_id: CredentialId, project_id: str) -> JoySafeterCredential:
        await self.lock_credential_scope(cred_id, project_id=project_id)
        cred = await self._get_or_raise(cred_id, project_id=project_id)
        if cred.kind != CredentialKind.MODEL.value or not cred.protocol:
            raise InvalidRequestError(
                code="CREDENTIAL_FIELD_INVALID",
                message="Only model credentials can be selected as defaults",
                data={"credential_id": str(cred_id), "kind": cred.kind},
                user_action="fix_input",
            )
        if cred.archived_at is not None:
            raise ResourceConflictError(
                code="CREDENTIAL_ARCHIVED",
                message="Archived credentials cannot be selected as defaults",
                data={"credential_id": str(cred_id)},
                user_action="refresh",
            )
        await self._clear_default(project_id=project_id, protocol=cred.protocol)
        cred.is_default = True
        cred.updated_at = utc_now()
        await self._mark_sandboxes_pending_for(cred, reason="credential_default_set")
        await self._finish_write()
        await self.db.refresh(cred)
        return cred

    async def clear_default(self, cred_id: CredentialId, project_id: str) -> JoySafeterCredential:
        await self.lock_credential_scope(cred_id, project_id=project_id)
        cred = await self._get_or_raise(cred_id, project_id=project_id)
        cred.is_default = False
        cred.updated_at = utc_now()
        await self._finish_write()
        await self.db.refresh(cred)
        return cred

    # --- cross-consumer dependency scan (Task 9) ---------------------------------

    async def dependencies(self, cred_id: CredentialId, project_id: str) -> CredentialDependencies:
        """Find the live consumers that reference this credential.

        Union of: agent ``model_credential_id``, trigger
        ``webhook_auth_credential_id``, environment ``config`` (service creds via
        ``secret_refs`` / ``egress_services``), the session→group association (an
        mcp credential is reachable through its group), and ACTIVE session
        ``agent_snapshot`` blobs (audit Blocker 1). Soft-deleted / archived
        consumers and terminated/archived sessions are excluded so lifecycle
        transitions are only blocked by genuinely live references.
        """
        from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
        from app.joysafeter_domain.models.joysafeter_credential import (
            JoySafeterSessionCredentialGroup,
        )
        from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
        from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
        from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger

        cred = await self._get_or_raise(cred_id, project_id=project_id)
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
            env_id
            for env_id, config in env_rows.all()
            if _config_references_credential(config, cred_id_str)
        ]

        # Sessions: an mcp credential is reachable via its group binding, and any
        # active session may pin this credential in its frozen snapshot.
        session_ids: dict = {}  # ordered set
        if cred.kind == CredentialKind.MCP.value and cred.group_id is not None:
            grp_rows = await self.db.execute(
                select(JoySafeterSessionCredentialGroup.session_id)
                .join(
                    JoySafeterSession,
                    JoySafeterSession.id == JoySafeterSessionCredentialGroup.session_id,
                )
                .where(
                    JoySafeterSessionCredentialGroup.credential_group_id == cred.group_id,
                    JoySafeterSession.project_id == project_id,
                    JoySafeterSession.archived_at.is_(None),
                    JoySafeterSession.status != "terminated",
                )
            )
            for session_id in grp_rows.scalars().all():
                session_ids[session_id] = None

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

    async def _reject_if_in_use(
        self, cred: JoySafeterCredential, project_id: str, *, verb: str
    ) -> None:
        deps = await self.dependencies(cred.id, project_id=project_id)
        if deps.in_use:
            raise ResourceConflictError(
                code="CREDENTIAL_IN_USE",
                message=f"Credential is still referenced and cannot be {verb}",
                data={"credential_id": str(cred.id), **deps.as_data()},
                user_action="fix_input",
            )

    # --- lifecycle ---------------------------------------------------------------
    # archive/soft_delete reject when the credential is still referenced by a live
    # consumer (agent / trigger / environment / active session or its snapshot);
    # FK RESTRICT only guards a physical delete, so the service enforces the rest.

    async def archive(self, cred_id: CredentialId, project_id: str) -> JoySafeterCredential:
        await self.lock_credential_scope(cred_id, project_id=project_id)
        cred = await self._get_or_raise(cred_id, project_id=project_id)
        await self._reject_if_in_use(cred, project_id, verb="archived")
        cred.archived_at = utc_now()
        if cred.is_default:
            cred.is_default = False
        cred.updated_at = utc_now()
        await self._mark_sandboxes_pending_for(cred, reason="credential_archived")
        await self._finish_write()
        await self.db.refresh(cred)
        return cred

    async def restore(self, cred_id: CredentialId, project_id: str) -> JoySafeterCredential:
        await self.lock_credential_scope(cred_id, project_id=project_id)
        cred = await self._get_or_raise(cred_id, project_id=project_id)
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
        if cred.kind == CredentialKind.MCP.value:
            sandbox_ids = await mark_live_sandboxes_pending(
                self.db,
                project_id=project_id,
                source_type="credential_group",
                source_id=str(cred.group_id),
            )
            self._queue_network_policy_refresh(
                sandbox_ids,
                project_id=project_id,
                reason="credential_group_member_restored",
                source_type="credential_group",
                source_id=str(cred.group_id),
            )
        await self._finish_write()
        await self.db.refresh(cred)
        return cred

    async def soft_delete(self, cred_id: CredentialId, project_id: str) -> JoySafeterCredential:
        await self.lock_credential_scope(cred_id, project_id=project_id)
        cred = await self._get_or_raise(cred_id, project_id=project_id)
        await self._reject_if_in_use(cred, project_id, verb="deleted")
        cred.deleted_at = utc_now()
        if cred.is_default:
            cred.is_default = False
        cred.updated_at = utc_now()
        await self._mark_sandboxes_pending_for(cred, reason="credential_deleted")
        await self._finish_write()
        await self.db.refresh(cred)
        return cred

    # --- concurrency lock --------------------------------------------------------

    async def lock_credentials(
        self,
        cred_ids: builtins.list[CredentialId],
        *,
        project_id: str | None = None,
    ) -> builtins.list[CredentialId]:
        """Lock credential rows in stable id order within the current transaction."""
        ordered_ids: builtins.list[CredentialId] = sorted(set(cred_ids), key=str)
        if not ordered_ids:
            return []
        conditions: builtins.list[ColumnElement[bool]] = [
            JoySafeterCredential.id.in_(ordered_ids)
        ]
        if project_id is not None:
            conditions.append(JoySafeterCredential.project_id == project_id)
        result = await self.db.execute(
            select(JoySafeterCredential.id)
            .where(and_(*conditions))
            .order_by(JoySafeterCredential.id)
            .with_for_update()
        )
        return list(result.scalars().all())

    async def lock_credential_group(
        self,
        group_id: CredentialGroupId | None,
        *,
        project_id: str | None = None,
    ) -> None:
        if group_id is None:
            return
        conditions = [JoySafeterCredentialGroup.id == group_id]
        if project_id is not None:
            conditions.append(JoySafeterCredentialGroup.project_id == project_id)
        await self.db.execute(
            select(JoySafeterCredentialGroup.id)
            .where(and_(*conditions))
            .with_for_update()
        )

    async def lock_credential_scope(
        self,
        cred_id: CredentialId,
        *,
        project_id: str,
    ) -> None:
        result = await self.db.execute(
            select(JoySafeterCredential.group_id).where(
                JoySafeterCredential.id == cred_id,
                JoySafeterCredential.project_id == project_id,
            )
        )
        group_id = result.scalar_one_or_none()
        await self.lock_credential_group(group_id, project_id=project_id)
        await self.lock_credential(cred_id, project_id=project_id)

    async def lock_credential(
        self,
        cred_id: CredentialId,
        *,
        project_id: str | None = None,
    ) -> None:
        """Acquire a row-level ``SELECT ... FOR UPDATE`` lock on the credential.

        Used by later concurrency-sensitive tasks (e.g. grant issuance) to
        serialize writers against a single credential row within a transaction.
        """
        await self.lock_credentials([cred_id], project_id=project_id)
