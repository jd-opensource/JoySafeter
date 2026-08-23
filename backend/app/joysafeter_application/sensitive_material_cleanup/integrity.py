from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_credential import JoySafeterCredential
from app.joysafeter_domain.models.joysafeter_session_repo import JoySafeterSessionRepo
from app.joysafeter_domain.models.joysafeter_task_identity import JoySafeterTaskIdentityContext
from app.joysafeter_infrastructure.sensitive_material import VersionedMaterialProtector
from app.joysafeter_shared.security.credential_cipher import (
    CredentialCipherConfigurationError,
    CredentialCiphertextError,
)

_MANAGED_DATA_SURFACE = "managed_credential.data"
_MANAGED_OAUTH_SURFACE = "managed_credential.oauth_config"
_TASK_IDENTITY_SURFACE = "task_identity"
_REPOSITORY_TOKEN_SURFACE = "repository_token"
_OAUTH_SECRET_FIELDS = ("client_secret", "refresh_token")


@dataclass(frozen=True, slots=True)
class SensitiveMaterialIntegrityIssue:
    surface: str
    record_id: str
    field: str
    category: str


@dataclass(frozen=True, slots=True)
class SensitiveMaterialIntegrityResult:
    checked_values: int
    valid_values: int
    invalid_values: int
    issues: tuple[SensitiveMaterialIntegrityIssue, ...]


class _IntegrityCollector:
    def __init__(self, protector: VersionedMaterialProtector) -> None:
        self._protector = protector
        self.checked_values = 0
        self.valid_values = 0
        self.issues: list[SensitiveMaterialIntegrityIssue] = []

    def invalid_container(self, *, surface: str, record_id: object, field: str) -> None:
        self.checked_values += 1
        self._append_issue(
            surface=surface,
            record_id=record_id,
            field=field,
            category="invalid-container-shape",
        )

    def verify(self, *, surface: str, record_id: object, field: str, value: object) -> None:
        if value == "":
            return
        self.checked_values += 1
        if not isinstance(value, str):
            self._append_issue(
                surface=surface,
                record_id=record_id,
                field=field,
                category="invalid-value-type",
            )
            return
        try:
            self._protector.reveal(value)
        except CredentialCipherConfigurationError:
            self._append_issue(
                surface=surface,
                record_id=record_id,
                field=field,
                category="cipher-configuration-error",
            )
        except (CredentialCiphertextError, TypeError):
            self._append_issue(
                surface=surface,
                record_id=record_id,
                field=field,
                category="ciphertext-invalid",
            )
        else:
            self.valid_values += 1

    def result(self) -> SensitiveMaterialIntegrityResult:
        issues = tuple(self.issues)
        return SensitiveMaterialIntegrityResult(
            checked_values=self.checked_values,
            valid_values=self.valid_values,
            invalid_values=len(issues),
            issues=issues,
        )

    def _append_issue(
        self,
        *,
        surface: str,
        record_id: object,
        field: str,
        category: str,
    ) -> None:
        self.issues.append(
            SensitiveMaterialIntegrityIssue(
                surface=surface,
                record_id=str(record_id),
                field=field,
                category=category,
            )
        )


async def _verify_managed_credentials(
    db: AsyncSession,
    collector: _IntegrityCollector,
    *,
    batch_size: int,
) -> None:
    cursor: object | None = None
    while True:
        statement = select(
            JoySafeterCredential.id,
            JoySafeterCredential.data,
            func.jsonb_typeof(JoySafeterCredential.data).label("data_type"),
            JoySafeterCredential.oauth_config,
            func.jsonb_typeof(JoySafeterCredential.oauth_config).label("oauth_config_type"),
        ).order_by(JoySafeterCredential.id)
        if cursor is not None:
            statement = statement.where(JoySafeterCredential.id > cursor)
        rows = (await db.execute(statement.limit(batch_size))).all()
        if not rows:
            return
        for row in rows:
            record_id = row.id
            if row.data_type != "object" or not isinstance(row.data, Mapping):
                collector.invalid_container(
                    surface=_MANAGED_DATA_SURFACE,
                    record_id=record_id,
                    field="data",
                )
            else:
                for field, value in row.data.items():
                    collector.verify(
                        surface=_MANAGED_DATA_SURFACE,
                        record_id=record_id,
                        field=str(field),
                        value=value,
                    )

            if row.oauth_config_type is None and row.oauth_config is None:
                continue
            if row.oauth_config_type != "object" or not isinstance(row.oauth_config, Mapping):
                collector.invalid_container(
                    surface=_MANAGED_OAUTH_SURFACE,
                    record_id=record_id,
                    field="oauth_config",
                )
                continue
            for field in _OAUTH_SECRET_FIELDS:
                if field in row.oauth_config:
                    collector.verify(
                        surface=_MANAGED_OAUTH_SURFACE,
                        record_id=record_id,
                        field=field,
                        value=row.oauth_config[field],
                    )
        cursor = rows[-1].id


async def _verify_task_identities(
    db: AsyncSession,
    collector: _IntegrityCollector,
    *,
    batch_size: int,
) -> None:
    cursor: object | None = None
    while True:
        statement = (
            select(
                JoySafeterTaskIdentityContext.task_id,
                JoySafeterTaskIdentityContext.encrypted_credential,
            )
            .where(
                JoySafeterTaskIdentityContext.encrypted_credential.is_not(None),
                JoySafeterTaskIdentityContext.encrypted_credential != "",
            )
            .order_by(JoySafeterTaskIdentityContext.task_id)
        )
        if cursor is not None:
            statement = statement.where(JoySafeterTaskIdentityContext.task_id > cursor)
        rows = (await db.execute(statement.limit(batch_size))).all()
        if not rows:
            return
        for row in rows:
            collector.verify(
                surface=_TASK_IDENTITY_SURFACE,
                record_id=row.task_id,
                field="encrypted_credential",
                value=row.encrypted_credential,
            )
        cursor = rows[-1].task_id


async def _verify_repository_tokens(
    db: AsyncSession,
    collector: _IntegrityCollector,
    *,
    batch_size: int,
) -> None:
    cursor: object | None = None
    while True:
        statement = (
            select(JoySafeterSessionRepo.id, JoySafeterSessionRepo.encrypted_token)
            .where(JoySafeterSessionRepo.encrypted_token != "")
            .order_by(JoySafeterSessionRepo.id)
        )
        if cursor is not None:
            statement = statement.where(JoySafeterSessionRepo.id > cursor)
        rows = (await db.execute(statement.limit(batch_size))).all()
        if not rows:
            return
        for row in rows:
            collector.verify(
                surface=_REPOSITORY_TOKEN_SURFACE,
                record_id=row.id,
                field="encrypted_token",
                value=row.encrypted_token,
            )
        cursor = rows[-1].id


async def verify_sensitive_material_integrity(
    db: AsyncSession,
    protector: VersionedMaterialProtector,
    *,
    batch_size: int = 500,
) -> SensitiveMaterialIntegrityResult:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    protector.require_enabled()
    collector = _IntegrityCollector(protector)
    await _verify_managed_credentials(db, collector, batch_size=batch_size)
    await _verify_task_identities(db, collector, batch_size=batch_size)
    await _verify_repository_tokens(db, collector, batch_size=batch_size)
    return collector.result()
