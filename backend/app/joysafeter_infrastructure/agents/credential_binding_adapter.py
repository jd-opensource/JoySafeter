from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_application.credentials.composition import compose_credential_application
from app.joysafeter_application.credentials.ports import CredentialAuditActor
from app.joysafeter_domain.credentials.types import CredentialId as DomainCredentialId
from app.joysafeter_domain.credentials.types import ProjectId
from app.joysafeter_domain.llm.catalog import get_llm_catalog
from app.joysafeter_domain.llm.model_inference_policy import build_model_inference_policy
from app.joysafeter_domain.services.credential_binding_errors import raise_public_credential_error
from app.joysafeter_shared.ids import CredentialId


class AgentCredentialBindingAdapter:
    def __init__(self, db: AsyncSession) -> None:
        self._application = compose_credential_application(
            db,
            auto_commit=False,
            audit_actor=CredentialAuditActor.system("agent_binding"),
        )

    async def lock_credentials(self, credential_ids: Sequence[CredentialId], *, project_id: str) -> None:
        await self._application.uow.credentials.lock_credentials(credential_ids, project_id=project_id)

    async def validate_model_reference(
        self,
        credential_id: CredentialId,
        *,
        project_id: str,
        engine_kind: str,
        model_id: Optional[str],
    ) -> None:
        try:
            binding = build_model_inference_policy(
                get_llm_catalog(),
                project_id=ProjectId(project_id),
                credential_id=DomainCredentialId(str(credential_id)),
                engine_kind=engine_kind,
                model_id=model_id,
            )
            await self._application.binding_service.validate_model_inference_reference(binding)
        except Exception as exc:
            raise_public_credential_error(exc, credential_id=credential_id)


__all__ = ["AgentCredentialBindingAdapter"]
