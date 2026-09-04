"""Quickstart recommendation orchestration (application layer).

Composes the pure domain policies into the shared ``QuickstartRecommendation``
contract. ``understand`` ranks engines and ``secure`` derives deterministic
environment and credential setup recommendations.

Display copy and derived assurance state are intentionally absent from the wire
contract. The frontend localizes stable reason enums and verifies the resources
that were actually created.
"""

from __future__ import annotations

from typing import Optional

from app.joysafeter_application.quickstart.ports import QuickstartModelConnectionReaderPort
from app.joysafeter_domain.quickstart import (
    ConnectionInput,
    EngineInput,
    QuickstartPhase,
    recommend_engine_options,
    recommend_security,
)
from app.joysafeter_domain.schemas.joysafeter_quickstart import (
    QuickstartCredentialGroupRecommendation,
    QuickstartEngineOptionOut,
    QuickstartEngineRecommendation,
    QuickstartEnvironmentRecommendation,
    QuickstartMcpServerRecommendation,
    QuickstartRecommendation,
    QuickstartSecureRecommendation,
    QuickstartUnderstandRecommendation,
)
from app.joysafeter_shared.ids import ProjectId


class QuickstartRecommendationService:
    def __init__(
        self,
        *,
        engines: tuple[EngineInput, ...] = (),
        connection_reader: Optional[QuickstartModelConnectionReaderPort] = None,
    ) -> None:
        self._engines = engines
        self._connection_reader = connection_reader

    async def recommend(
        self,
        *,
        phase: QuickstartPhase,
        project_id: ProjectId,
        intent_text: str,
        agent_config: Optional[dict],
    ) -> QuickstartRecommendation:
        """Execute the phase-owned recommendation use case through one entry point."""
        if phase is QuickstartPhase.UNDERSTAND:
            connections = (
                await self._connection_reader.list_for_project(project_id)
                if self._connection_reader is not None
                else []
            )
            return self.recommend_engine(
                intent_text=intent_text,
                enabled_engines=list(self._engines),
                connections=connections,
            )
        if phase is QuickstartPhase.SECURE:
            return await self.recommend_security(
                intent_text=intent_text,
                agent_config=agent_config,
            )
        raise ValueError(f"phase {phase.value!r} does not provide recommendations")

    def recommend_engine(
        self,
        *,
        intent_text: str,
        enabled_engines: list[EngineInput],
        connections: list[ConnectionInput],
    ) -> QuickstartRecommendation:
        options = recommend_engine_options(enabled_engines, connections, intent_text)
        recommended = next((o.engine_id for o in options if o.recommended), None)
        return QuickstartUnderstandRecommendation(
            phase=QuickstartPhase.UNDERSTAND,
            engine=QuickstartEngineRecommendation(
                recommended_engine_id=recommended,
                options=[
                    QuickstartEngineOptionOut(
                        engine_id=o.engine_id,
                        readiness=o.readiness,
                        compatible_connection_count=o.compatible_connection_count,
                    )
                    for o in options
                ],
            ),
        )

    async def recommend_security(
        self, *, intent_text: str, agent_config: Optional[dict]
    ) -> QuickstartSecureRecommendation:
        rule = recommend_security([intent_text], agent_config)

        allowed_hosts = list(rule.recommended_hosts)
        mcp_servers = [
            QuickstartMcpServerRecommendation(
                name=server.name,
                url=server.url,
                auth_requirement=server.auth_requirement,
            )
            for server in rule.recommended_mcp_servers
        ]
        environment = QuickstartEnvironmentRecommendation(
            allowed_hosts=allowed_hosts,
            host_reason=rule.host_reason,
        )

        credential_group: Optional[QuickstartCredentialGroupRecommendation] = None
        if rule.external_tools_recommended:
            credential_group = QuickstartCredentialGroupRecommendation(
                mcp_servers=mcp_servers,
                external_tools_reason=rule.external_tools_reason,
            )

        return QuickstartSecureRecommendation(
            phase=QuickstartPhase.SECURE,
            environment=environment,
            credential_group=credential_group,
        )
