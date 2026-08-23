from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_application.credentials.application_service import CredentialService
from app.joysafeter_application.credentials.ports import CredentialAuditActor
from app.joysafeter_domain.llm.compatibility import resolve_credential_profile
from app.joysafeter_domain.models.joysafeter_credential import JoySafeterCredential
from app.joysafeter_domain.schemas.joysafeter_credential import ModelCredentialSummary
from app.joysafeter_shared.ids import CredentialId


def normalize_agent_model(value: object) -> dict[str, str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        model_id = value.strip()
        return {"id": model_id, "speed": "standard"} if model_id else None
    if isinstance(value, dict):
        model_id = value.get("id")
        if not isinstance(model_id, str) or not model_id.strip():
            return None
        speed = value.get("speed")
        return {
            "id": model_id.strip(),
            "speed": speed.strip() if isinstance(speed, str) and speed.strip() else "standard",
        }
    return None


def _model_from_credential(credential: JoySafeterCredential, service: CredentialService) -> str | None:
    profile = resolve_credential_profile(credential)
    if profile is None or profile.model_key is None:
        return None
    return service.get_masked(credential).get(profile.model_key) or None


def model_connection_summary(
    credential: JoySafeterCredential | None,
    service: CredentialService,
) -> ModelCredentialSummary | None:
    if credential is None or credential.kind != "model" or credential.deleted_at is not None:
        return None
    return ModelCredentialSummary(
        id=credential.id,
        name=credential.name,
        provider=credential.provider,
        protocol=credential.protocol,
        model=_model_from_credential(credential, service),
        is_default=credential.is_default,
        archived_at=credential.archived_at,
    )


def maybe_credential_id(value: CredentialId | str | None) -> CredentialId | None:
    if not value:
        return None
    if isinstance(value, CredentialId):
        return value
    try:
        return CredentialId.from_public(str(value))
    except ValueError:
        return None


async def load_model_connection_summaries(
    db: AsyncSession,
    credential_ids: Iterable[CredentialId | str | None],
    *,
    project_id: str | None,
) -> dict[CredentialId, ModelCredentialSummary]:
    ids = {parsed for credential_id in credential_ids if (parsed := maybe_credential_id(credential_id))}
    if not ids:
        return {}

    query = select(JoySafeterCredential).where(
        JoySafeterCredential.id.in_(ids),
        JoySafeterCredential.kind == "model",
        JoySafeterCredential.deleted_at.is_(None),
    )
    if project_id is not None:
        query = query.where(JoySafeterCredential.project_id == project_id)

    result = await db.execute(query)
    service = CredentialService(db, audit_actor=CredentialAuditActor.system("model_connection_summary"))
    summaries = [model_connection_summary(credential, service) for credential in result.scalars().all()]
    return {summary.id: summary for summary in summaries if summary is not None}
