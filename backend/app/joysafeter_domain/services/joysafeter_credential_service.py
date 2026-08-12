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

from typing import Optional

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.joysafeter_api.api.v1.network_policy_refresh import mark_live_sandboxes_pending
from app.joysafeter_domain.models.joysafeter_credential import JoySafeterCredential
from app.joysafeter_domain.schemas.joysafeter_credential import (
    CREDENTIAL_DATA_MAX_FIELDS,
    CREDENTIAL_DATA_MAX_KEY_LENGTH,
    CREDENTIAL_DATA_MAX_VALUE_LENGTH,
    CreateCredentialRequest,
    CredentialKind,
    UpdateCredentialRequest,
)
from app.joysafeter_shared.common.app_errors import (
    InvalidRequestError,
    NotFoundError,
    ResourceConflictError,
)
from app.joysafeter_shared.ids import CredentialId
from app.joysafeter_shared.mcp_url import normalize_mcp_url
from app.joysafeter_shared.security.credential_cipher import CredentialCipher
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


class CredentialService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._cipher = _get_cipher()

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
        return {str(key): self._cipher.encrypt(str(value)) for key, value in (data or {}).items()}

    def decrypt_data(self, data: dict | None) -> dict[str, str]:
        return {str(key): self._cipher.decrypt_stored(str(value)) for key, value in (data or {}).items()}

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

        # Purge any soft-deleted row that would collide on the (project,kind,name)
        # partial unique index so re-creating a deleted name succeeds.
        await self.db.execute(
            delete(JoySafeterCredential).where(
                JoySafeterCredential.project_id == project_id,
                JoySafeterCredential.kind == req.kind.value,
                JoySafeterCredential.name == req.name,
                JoySafeterCredential.deleted_at.is_not(None),
            )
        )

        normalized_url = normalize_mcp_url(req.mcp_server_url) if req.kind is CredentialKind.MCP else None
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
            group_id=req.group_id,
        )
        self.db.add(cred)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
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
        limit: int = 20,
        after_id: Optional[CredentialId] = None,
    ) -> tuple[list[JoySafeterCredential], bool]:
        q = select(JoySafeterCredential).where(
            JoySafeterCredential.project_id == project_id,
            JoySafeterCredential.deleted_at.is_(None),
        )
        if kind is not None:
            kind_value = kind.value if isinstance(kind, CredentialKind) else kind
            q = q.where(JoySafeterCredential.kind == kind_value)
        if after_id:
            cursor_created_at = (
                select(JoySafeterCredential.created_at)
                .where(JoySafeterCredential.id == after_id)
                .scalar_subquery()
            )
            q = q.where(
                or_(
                    JoySafeterCredential.created_at < cursor_created_at,
                    and_(
                        JoySafeterCredential.created_at == cursor_created_at,
                        JoySafeterCredential.id < after_id,
                    ),
                )
            )
        q = q.order_by(
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
            cred.data = self.encrypt_data_for_storage(merged)

        if req.is_default is not None and cred.kind == CredentialKind.MODEL.value:
            if req.is_default:
                await self._clear_default(project_id=project_id, protocol=cred.protocol or "")
            cred.is_default = req.is_default

        cred.updated_at = utc_now()
        await self._mark_sandboxes_pending_for(cred)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            if req.name is not None and self._is_name_integrity_error(exc):
                raise self._name_conflict(req.name) from exc
            raise
        await self.db.refresh(cred)
        return cred

    # --- default (model only) ----------------------------------------------------

    async def _mark_sandboxes_pending_for(self, cred: JoySafeterCredential) -> None:
        """Mark live limited-networking sandboxes ``pending`` in THIS transaction.

        Called by the mutation methods that change already-referenced material
        (update/archive/soft_delete/set_default) BEFORE their own commit, so the
        credential change and the sandbox pending-mark commit together atomically.
        There is no window where the DB holds the new/rotated/revoked credential
        while a sandbox is never flagged for re-push (audit Blocker 5).

        No commit and no Redis nudge here: the caller commits, and the durable
        ``pending`` reconcile loop converges regardless. Post-commit nudging is
        left to the route/wrapper. ``create`` is intentionally excluded — a
        brand-new credential is not yet referenced by any live sandbox.
        """
        await mark_live_sandboxes_pending(
            self.db,
            project_id=cred.project_id,
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
        cred = await self._get_or_raise(cred_id, project_id=project_id)
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
        await self._mark_sandboxes_pending_for(cred)
        await self.db.commit()
        await self.db.refresh(cred)
        return cred

    async def clear_default(self, cred_id: CredentialId, project_id: str) -> JoySafeterCredential:
        cred = await self._get_or_raise(cred_id, project_id=project_id)
        cred.is_default = False
        cred.updated_at = utc_now()
        await self.db.commit()
        await self.db.refresh(cred)
        return cred

    # --- lifecycle ---------------------------------------------------------------
    # Cross-consumer in-use rejection is Task 9's responsibility (the consumer ID
    # columns do not exist yet); these methods just set the timestamps.

    async def archive(self, cred_id: CredentialId, project_id: str) -> JoySafeterCredential:
        cred = await self._get_or_raise(cred_id, project_id=project_id)
        cred.archived_at = utc_now()
        if cred.is_default:
            cred.is_default = False
        cred.updated_at = utc_now()
        await self._mark_sandboxes_pending_for(cred)
        await self.db.commit()
        await self.db.refresh(cred)
        return cred

    async def restore(self, cred_id: CredentialId, project_id: str) -> JoySafeterCredential:
        cred = await self._get_or_raise(cred_id, project_id=project_id)
        cred.archived_at = None
        cred.updated_at = utc_now()
        await self.db.commit()
        await self.db.refresh(cred)
        return cred

    async def soft_delete(self, cred_id: CredentialId, project_id: str) -> JoySafeterCredential:
        cred = await self._get_or_raise(cred_id, project_id=project_id)
        cred.deleted_at = utc_now()
        if cred.is_default:
            cred.is_default = False
        cred.updated_at = utc_now()
        await self._mark_sandboxes_pending_for(cred)
        await self.db.commit()
        await self.db.refresh(cred)
        return cred

    # --- concurrency lock --------------------------------------------------------

    async def lock_credential(self, cred_id: CredentialId) -> None:
        """Acquire a row-level ``SELECT ... FOR UPDATE`` lock on the credential.

        Used by later concurrency-sensitive tasks (e.g. grant issuance) to
        serialize writers against a single credential row within a transaction.
        """
        await self.db.execute(
            select(JoySafeterCredential.id)
            .where(JoySafeterCredential.id == cred_id)
            .with_for_update()
        )
