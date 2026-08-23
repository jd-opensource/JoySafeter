from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_credential import JoySafeterCredential
from app.joysafeter_domain.models.joysafeter_session_repo import JoySafeterSessionRepo
from app.joysafeter_domain.models.joysafeter_task_identity import JoySafeterTaskIdentityContext
from app.joysafeter_infrastructure.sensitive_material.versioned import VersionedMaterialProtector
from app.joysafeter_shared.security.credential_cipher import CredentialCiphertextError
from app.joysafeter_shared.utils.datetime import utc_now

_OAUTH_SECRET_FIELDS = frozenset({"client_secret", "refresh_token"})


@dataclass(frozen=True, slots=True)
class SensitiveMaterialRewrapResult:
    managed_credentials: int = 0
    task_identities: int = 0
    repository_tokens: int = 0

    @classmethod
    def empty(cls) -> SensitiveMaterialRewrapResult:
        return cls()

    @property
    def total(self) -> int:
        return self.managed_credentials + self.task_identities + self.repository_tokens


def _normalize_object(
    protector: VersionedMaterialProtector,
    value: object,
    *,
    location: str,
    keys: frozenset[str] | None = None,
) -> dict:
    if not isinstance(value, dict):
        raise CredentialCiphertextError(f"Sensitive material at {location} is not an object")
    normalized = dict(value)
    selected_keys = value.keys() if keys is None else (key for key in keys if key in value)
    for key in selected_keys:
        normalized[key] = _normalize_encrypted_value(
            protector,
            value[key],
            location=f"{location}.{key}",
        )
    return normalized


def _normalize_encrypted_value(
    protector: VersionedMaterialProtector,
    value: object,
    *,
    location: str,
) -> str:
    if not isinstance(value, str):
        raise CredentialCiphertextError(f"Sensitive material at {location} is not a string envelope")
    if value and not value.startswith("enc:"):
        raise CredentialCiphertextError(f"Sensitive material at {location} is not an encrypted envelope")
    return protector.normalize(value)


async def _rewrap_managed_credentials(
    db: AsyncSession,
    protector: VersionedMaterialProtector,
    *,
    limit: int,
) -> int:
    active_prefix = protector.active_envelope_prefix
    candidates = list(
        (
            await db.execute(
                select(JoySafeterCredential)
                .where(
                    JoySafeterCredential.material_erased_at.is_(None),
                    text(
                        "(jsonb_typeof(joysafeter_credentials.data) IS DISTINCT FROM 'object' "
                        "OR EXISTS ("
                        "SELECT 1 FROM jsonb_each_text("
                        "CASE WHEN jsonb_typeof(joysafeter_credentials.data) = 'object' "
                        "THEN joysafeter_credentials.data ELSE '{}'::jsonb END"
                        ") AS item "
                        "WHERE item.value IS NULL OR (item.value <> '' "
                        "AND left(item.value, length(:active_prefix)) <> :active_prefix)"
                        ") OR (joysafeter_credentials.oauth_config IS NOT NULL AND ("
                        "jsonb_typeof(joysafeter_credentials.oauth_config) IS DISTINCT FROM 'object' "
                        "OR EXISTS ("
                        "SELECT 1 FROM jsonb_each_text("
                        "CASE WHEN jsonb_typeof(joysafeter_credentials.oauth_config) = 'object' "
                        "THEN joysafeter_credentials.oauth_config ELSE '{}'::jsonb END"
                        ") AS item "
                        "WHERE item.key IN ('client_secret', 'refresh_token') "
                        "AND (item.value IS NULL OR (item.value <> '' "
                        "AND left(item.value, length(:active_prefix)) <> :active_prefix))"
                        "))))"
                    ),
                )
                .order_by(JoySafeterCredential.id)
                .limit(limit)
                .with_for_update(skip_locked=True),
                {"active_prefix": active_prefix},
            )
        )
        .scalars()
        .all()
    )
    changed = 0
    for credential in candidates:
        location = f"managed_credential.data[id={credential.id}]"
        normalized_data = _normalize_object(
            protector,
            credential.data,
            location=location,
        )
        normalized_oauth = (
            None
            if credential.oauth_config is None
            else _normalize_object(
                protector,
                credential.oauth_config,
                location=f"managed_credential.oauth_config[id={credential.id}]",
                keys=_OAUTH_SECRET_FIELDS,
            )
        )
        if normalized_data != credential.data or normalized_oauth != credential.oauth_config:
            credential.data = normalized_data
            credential.oauth_config = normalized_oauth
            changed += 1
    return changed


async def _rewrap_task_identities(
    db: AsyncSession,
    protector: VersionedMaterialProtector,
    *,
    limit: int,
) -> int:
    active_prefix = protector.active_envelope_prefix
    rows = list(
        (
            await db.execute(
                select(JoySafeterTaskIdentityContext)
                .where(
                    JoySafeterTaskIdentityContext.encrypted_credential.is_not(None),
                    JoySafeterTaskIdentityContext.encrypted_credential != "",
                    JoySafeterTaskIdentityContext.expires_at > utc_now(),
                    text(
                        "left(joysafeter_task_identity_contexts.encrypted_credential, "
                        "length(:active_prefix)) <> :active_prefix"
                    ),
                )
                .order_by(JoySafeterTaskIdentityContext.task_id)
                .limit(limit)
                .with_for_update(skip_locked=True),
                {"active_prefix": active_prefix},
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        assert row.encrypted_credential is not None
        row.encrypted_credential = _normalize_encrypted_value(
            protector,
            row.encrypted_credential,
            location=f"task_identity[task_id={row.task_id}].encrypted_credential",
        )
    return len(rows)


async def _rewrap_repository_tokens(
    db: AsyncSession,
    protector: VersionedMaterialProtector,
    *,
    limit: int,
) -> int:
    active_prefix = protector.active_envelope_prefix
    rows = list(
        (
            await db.execute(
                select(JoySafeterSessionRepo)
                .where(
                    JoySafeterSessionRepo.encrypted_token != "",
                    or_(
                        JoySafeterSessionRepo.token_expires_at.is_(None),
                        JoySafeterSessionRepo.token_expires_at > utc_now(),
                    ),
                    text("left(joysafeter_session_repos.encrypted_token, length(:active_prefix)) <> :active_prefix"),
                )
                .order_by(JoySafeterSessionRepo.id)
                .limit(limit)
                .with_for_update(skip_locked=True),
                {"active_prefix": active_prefix},
            )
        )
        .scalars()
        .all()
    )
    rotated_at = utc_now()
    for row in rows:
        row.encrypted_token = _normalize_encrypted_value(
            protector,
            row.encrypted_token,
            location=f"repository_token[id={row.id}].encrypted_token",
        )
        row.token_rotated_at = rotated_at
    return len(rows)


async def rewrap_sensitive_material(
    db: AsyncSession,
    protector: VersionedMaterialProtector,
    *,
    limit_per_store: int = 100,
) -> SensitiveMaterialRewrapResult:
    if limit_per_store < 1:
        raise ValueError("limit_per_store must be positive")
    protector.require_enabled()
    async with db.begin_nested():
        return SensitiveMaterialRewrapResult(
            managed_credentials=await _rewrap_managed_credentials(db, protector, limit=limit_per_store),
            task_identities=await _rewrap_task_identities(db, protector, limit=limit_per_store),
            repository_tokens=await _rewrap_repository_tokens(db, protector, limit=limit_per_store),
        )
