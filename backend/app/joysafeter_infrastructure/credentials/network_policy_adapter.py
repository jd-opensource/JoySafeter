from __future__ import annotations

from dataclasses import replace

from app.joysafeter_domain.credentials.dependencies import (
    CredentialImpact,
    DependencyDisposition,
)
from app.joysafeter_infrastructure.network_policy.refresh import (
    mark_live_sandboxes_pending,
    nudge_sandbox_network_policy_refreshes,
)
from app.joysafeter_infrastructure.runtime_configuration import (
    mark_live_sandboxes_restart_required,
)
from app.joysafeter_shared.ids import SandboxId


class SqlAlchemyCredentialImpactAdapter:
    def __init__(self, db: object) -> None:
        self._db = db
        self._pending: list[CredentialImpact] = []
        self._advanced_session_ids: set[str] = set()

    def begin_mutation(self) -> None:
        self._advanced_session_ids.clear()

    async def mark_pending(self, impact: CredentialImpact) -> CredentialImpact:
        if impact.source_id is None:
            raise ValueError("credential impact source_id is required")
        affected_sandbox_ids = set(impact.affected_sandbox_ids)
        affected_session_ids = set(impact.affected_session_ids)
        if DependencyDisposition.REVALIDATE_ON_ACTIVATION in impact.dispositions:
            runtime_session_ids, runtime_sandbox_ids = await mark_live_sandboxes_restart_required(
                self._db,
                impact,
                already_advanced_session_ids=frozenset(self._advanced_session_ids),
            )
            self._advanced_session_ids.update(str(session_id) for session_id in runtime_session_ids)
            affected_session_ids.update(str(session_id) for session_id in runtime_session_ids)
            affected_sandbox_ids.update(str(sandbox_id) for sandbox_id in runtime_sandbox_ids)
        if DependencyDisposition.REFRESH_RUNTIME_POLICY in impact.dispositions:
            network_sandbox_ids = await mark_live_sandboxes_pending(
                self._db,
                project_id=str(impact.project_id),
                source_type=impact.source,
                source_id=impact.source_id,
            )
            affected_sandbox_ids.update(str(sandbox_id) for sandbox_id in network_sandbox_ids)
            self._pending.append(
                replace(
                    impact,
                    affected_sandbox_ids=frozenset(str(sandbox_id) for sandbox_id in network_sandbox_ids),
                )
            )
        return replace(
            impact,
            affected_sandbox_ids=frozenset(affected_sandbox_ids),
            affected_session_ids=frozenset(affected_session_ids),
        )

    async def nudge_after_commit(self) -> None:
        pending, self._pending = self._pending, []
        try:
            for impact in pending:
                if impact.source_id is None:
                    continue
                sandbox_ids = [SandboxId.from_public(sandbox_id) for sandbox_id in impact.affected_sandbox_ids]
                nudged = await nudge_sandbox_network_policy_refreshes(
                    sandbox_ids,
                    project_id=str(impact.project_id),
                    reason=impact.reason or "credential_changed",
                    source_type=impact.source,
                    source_id=impact.source_id,
                )
                if nudged != len(sandbox_ids):
                    raise RuntimeError(f"credential impact nudge reached {nudged} of {len(sandbox_ids)} sandboxes")
        finally:
            self._advanced_session_ids.clear()

    def clear_pending(self) -> None:
        self._pending.clear()
        self._advanced_session_ids.clear()
