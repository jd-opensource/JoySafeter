"""Composition root for the quickstart application capability."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_application.credentials.application_service import CredentialService
from app.joysafeter_application.credentials.ports import CredentialAuditActor
from app.joysafeter_application.quickstart.design_service import QuickstartDesignService
from app.joysafeter_application.quickstart.recommendation_service import (
    QuickstartRecommendationService,
)
from app.joysafeter_domain.llm.catalog import get_llm_catalog
from app.joysafeter_domain.llm.compatibility import compatible_engine_ids
from app.joysafeter_domain.quickstart import ConnectionInput, EngineInput
from app.joysafeter_shared.ids import CredentialId, ProjectId


class _CredentialModelConnectionReader:
    def __init__(self, credentials: CredentialService) -> None:
        self._credentials = credentials

    async def list_for_project(self, project_id: ProjectId) -> list[ConnectionInput]:
        credentials = []
        after_id = None
        seen_cursors: set[CredentialId] = set()
        while True:
            page, has_more = await self._credentials.list(
                project_id=project_id,
                kind="model",
                include_archived=False,
                limit=100,
                after_id=after_id,
            )
            credentials.extend(page)
            if not has_more:
                break
            if not page:
                raise RuntimeError("Model Connection pagination returned has_more without data")
            next_after_id = page[-1].id
            if next_after_id == after_id or next_after_id in seen_cursors:
                raise RuntimeError("Model Connection pagination returned a repeated cursor")
            seen_cursors.add(next_after_id)
            after_id = next_after_id
        return [
            ConnectionInput(
                compatible_engine_ids=(
                    tuple(compatible_engine_ids(credential.provider, credential.protocol))
                    if credential.provider and credential.protocol
                    else ()
                ),
                is_default=credential.is_default,
                archived=credential.archived_at is not None,
            )
            for credential in credentials
        ]


def compose_quickstart_design_application() -> QuickstartDesignService:
    return QuickstartDesignService()


def compose_quickstart_application(
    db: AsyncSession,
    *,
    audit_actor: CredentialAuditActor,
) -> QuickstartRecommendationService:
    catalog = get_llm_catalog()
    engines = tuple(
        EngineInput(
            engine_id=engine.id,
            display_name=engine.display_name,
            enabled=engine.enabled,
        )
        for engine in catalog.engines
    )
    credentials = CredentialService(db, audit_actor=audit_actor)
    return QuickstartRecommendationService(
        engines=engines,
        connection_reader=_CredentialModelConnectionReader(credentials),
    )
