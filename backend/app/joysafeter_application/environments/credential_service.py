from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_application.credentials.composition import compose_credential_application
from app.joysafeter_application.credentials.ports import (
    CredentialAuditActor,
    CredentialAuditEntry,
    combine_credential_impacts,
)
from app.joysafeter_domain.credentials.bindings import (
    EgressInjectKind,
    EgressInjectPolicy,
    EnvironmentInjectionBinding,
    HttpEgressBinding,
)
from app.joysafeter_domain.credentials.dependencies import CredentialImpact, runtime_impact_dispositions
from app.joysafeter_domain.credentials.references import CredentialReferenceCodec
from app.joysafeter_domain.credentials.types import (
    CredentialFieldName,
    CredentialUsage,
    NormalizedEndpoint,
    ProjectId,
)
from app.joysafeter_domain.credentials.types import CredentialId as DomainCredentialId
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.schemas.joysafeter_environment import (
    EnvironmentConfig,
    extract_environment_credential_references,
)
from app.joysafeter_domain.services.credential_binding_errors import raise_public_credential_error
from app.joysafeter_shared.common.app_errors import InvalidRequestError, NotFoundError

logger = logging.getLogger(__name__)

_IMPACT_SURFACE_PROJECT_ID = ProjectId("environment-impact-surface")
_REFERENCE_CODEC = CredentialReferenceCodec()


def _credential_binding_surfaces(config: dict[str, Any] | None) -> dict[CredentialUsage, frozenset[object]]:
    decoded = _REFERENCE_CODEC.decode_environment(config or {})
    direct = frozenset(
        EnvironmentInjectionBinding(
            project_id=_IMPACT_SURFACE_PROJECT_ID,
            credential_id=DomainCredentialId(str(credential_id)),
        )
        for credential_id in decoded.direct_credential_ids
    )
    egress_bindings = {
        HttpEgressBinding(
            project_id=_IMPACT_SURFACE_PROJECT_ID,
            credential_id=reference.credential_id,
            endpoint=NormalizedEndpoint(reference.endpoint),
            inject=EgressInjectPolicy(
                kind=EgressInjectKind(reference.inject_kind),
                credential_field=CredentialFieldName(reference.credential_field),
                header=reference.header,
                cookie_name=reference.cookie_name,
            ),
        )
        for reference in decoded.http_egress
    }
    return {
        CredentialUsage.ENVIRONMENT_INJECTION: direct,
        CredentialUsage.HTTP_EGRESS: frozenset(egress_bindings),
    }


def _changed_credential_binding_usages(
    old_config: dict[str, Any] | None,
    new_config: dict[str, Any] | None,
) -> tuple[CredentialUsage, ...]:
    old_surfaces = _credential_binding_surfaces(old_config)
    new_surfaces = _credential_binding_surfaces(new_config)
    return tuple(usage for usage in CredentialUsage if old_surfaces.get(usage) != new_surfaces.get(usage))


class EnvironmentCredentialService:
    """Coordinates environment credential validation, audit, and runtime impact."""

    def __init__(self, db: AsyncSession, *, audit_actor: CredentialAuditActor) -> None:
        self._db = db
        self._application = compose_credential_application(
            db,
            auto_commit=False,
            audit_actor=audit_actor,
        )

    async def validate_references(
        self,
        config: EnvironmentConfig,
        project_id: str | None,
    ) -> None:
        references = extract_environment_credential_references(config)
        if not references:
            return

        if project_id is None:
            reference = references[0]
            raise NotFoundError(
                code="CREDENTIAL_NOT_FOUND",
                message="Credential not found",
                data={
                    "credential_id": str(reference.credential_id),
                    "source": reference.source,
                },
                user_action="fix_input",
            )

        await self._application.uow.credentials.lock_credentials(
            list(dict.fromkeys(reference.credential_id for reference in references)),
            project_id=project_id,
        )
        for reference in references:
            reference_data = {
                "source": reference.source,
                "index": reference.index,
                "path": reference.path,
            }
            if reference.source == "environment_credential_ids":
                try:
                    binding = EnvironmentInjectionBinding(
                        ProjectId(project_id),
                        DomainCredentialId(str(reference.credential_id)),
                    )
                except (TypeError, ValueError) as exc:
                    raise_public_credential_error(
                        exc,
                        credential_id=reference.credential_id,
                        data=reference_data,
                    )
            else:
                service = config.egress_services[reference.index or 0]
                inject = service.inject
                if not inject.credential_field:
                    raise InvalidRequestError(
                        code="CREDENTIAL_FIELD_MISSING",
                        message="A required credential field is missing",
                        data={"credential_id": str(reference.credential_id), **reference_data},
                        user_action="fix_input",
                    )
                try:
                    credential_field = CredentialFieldName(inject.credential_field)
                except (TypeError, ValueError) as exc:
                    raise_public_credential_error(
                        exc,
                        credential_id=reference.credential_id,
                        data=reference_data,
                        constructor_error="field_missing",
                    )
                try:
                    binding = HttpEgressBinding(
                        ProjectId(project_id),
                        DomainCredentialId(str(reference.credential_id)),
                        NormalizedEndpoint(service.base_url),
                        EgressInjectPolicy(
                            EgressInjectKind(inject.type),
                            credential_field,
                            header=inject.header,
                            cookie_name=inject.cookie_name,
                        ),
                    )
                except (TypeError, ValueError) as exc:
                    raise_public_credential_error(
                        exc,
                        credential_id=reference.credential_id,
                        data=reference_data,
                    )
            try:
                await self._application.binding_service.validate_reference(binding)
            except Exception as exc:
                raise_public_credential_error(
                    exc,
                    credential_id=reference.credential_id,
                    data=reference_data,
                )

    async def commit_update(
        self,
        env: JoySafeterEnvironment,
        *,
        project_id: str,
        old_config: dict[str, Any] | None,
        new_config: dict[str, Any] | None,
    ) -> None:
        changed_usages = _changed_credential_binding_usages(old_config, new_config)
        impacted_usages = () if old_config is None else changed_usages
        runtime_restart_required = CredentialUsage.ENVIRONMENT_INJECTION in impacted_usages
        if changed_usages:
            await self._application.uow.audit.append(
                CredentialAuditEntry(
                    action="environment.credentials.updated",
                    project_id=project_id,
                    target_type="environment",
                    target_id=str(env.id),
                    details={
                        "environment_id": str(env.id),
                        "runtime_restart_required": runtime_restart_required,
                    },
                )
            )
        combined_impact = combine_credential_impacts(
            tuple(
                CredentialImpact(
                    usage=usage,
                    source="environment",
                    source_id=str(env.id),
                    reason="environment.updated",
                    project_id=ProjectId(project_id),
                    affected_sandbox_ids=frozenset(),
                    affected_session_ids=frozenset(),
                    dispositions=runtime_impact_dispositions(usage),
                )
                for usage in impacted_usages
            )
        )
        if combined_impact is not None:
            self._application.uow.impacts.begin_mutation()
            await self._application.uow.impacts.mark_pending(combined_impact)
        await self._application.uow.commit()
        await self._db.refresh(env)
        if impacted_usages:
            try:
                await self._application.uow.impacts.nudge_after_commit()
            except Exception:
                logger.warning("environment credential impact nudge failed after commit", exc_info=True)
