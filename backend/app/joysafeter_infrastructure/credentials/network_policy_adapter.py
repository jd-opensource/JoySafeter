from __future__ import annotations

from dataclasses import replace

from app.joysafeter_domain.credentials.dependencies import CredentialImpact
from app.joysafeter_infrastructure.network_policy.refresh import (
    mark_live_sandboxes_pending,
    nudge_sandbox_network_policy_refreshes,
)
from app.joysafeter_shared.ids import SandboxId


class SqlAlchemyCredentialImpactAdapter:
    def __init__(self, db: object) -> None:
        self._db = db
        self._pending: list[CredentialImpact] = []

    async def mark_pending(self, impact: CredentialImpact) -> CredentialImpact:
        if impact.source_id is None:
            raise ValueError("credential impact source_id is required")
        sandbox_ids = await mark_live_sandboxes_pending(
            self._db,
            project_id=str(impact.project_id),
            source_type=impact.source,
            source_id=impact.source_id,
        )
        resolved = replace(
            impact,
            affected_sandbox_ids=frozenset(str(sandbox_id) for sandbox_id in sandbox_ids),
        )
        self._pending.append(resolved)
        return resolved

    async def nudge_after_commit(self) -> None:
        pending, self._pending = self._pending, []
        for impact in pending:
            if impact.source_id is None:
                continue
            await nudge_sandbox_network_policy_refreshes(
                [SandboxId.from_public(sandbox_id) for sandbox_id in impact.affected_sandbox_ids],
                project_id=str(impact.project_id),
                reason=impact.reason or "credential_changed",
                source_type=impact.source,
                source_id=impact.source_id,
            )

    def clear_pending(self) -> None:
        self._pending.clear()
