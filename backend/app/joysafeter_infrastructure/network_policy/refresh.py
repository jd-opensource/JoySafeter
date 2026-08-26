from __future__ import annotations

import asyncio
import logging

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_shared.ids import ProjectId, SandboxId
from app.joysafeter_shared.orchestrator_bridge.runtime_commands import publish_to_sandbox_owner_via_redis

logger = logging.getLogger(__name__)


async def mark_live_sandboxes_pending(
    db: AsyncSession,
    *,
    project_id: ProjectId | None,
    source_type: str,
    source_id: str,
) -> list[SandboxId]:
    conditions = [
        JoySafeterSandbox.destroyed_at.is_(None),
        JoySafeterSandbox.status.in_(["idle", "running", "creating", "provisioning"]),
        JoySafeterSandbox.config["fingerprint"]["networking"]["type"].astext == "limited",
    ]
    if project_id is not None:
        conditions.append(JoySafeterSandbox.project_id == project_id)
    marked = await db.execute(
        update(JoySafeterSandbox)
        .where(*conditions)
        .values(networking_status="pending", networking_last_error=None)
        .returning(JoySafeterSandbox.id)
        .execution_options(synchronize_session=False)
    )
    return [row[0] for row in marked.all()]


async def nudge_sandbox_network_policy_refreshes(
    sandbox_ids: list[SandboxId],
    *,
    project_id: ProjectId | None,
    reason: str,
    source_type: str,
    source_id: str,
) -> int:
    if not sandbox_ids:
        return 0

    semaphore = asyncio.Semaphore(10)

    async def nudge(sandbox_id: SandboxId) -> bool:
        async with semaphore:
            try:
                return await publish_to_sandbox_owner_via_redis(
                    sandbox_id,
                    command={
                        "type": "network_policy_refresh",
                        "reason": reason,
                        "source_type": source_type,
                        "source_id": source_id,
                    },
                    boundary="network_policy_refresh",
                    operation="refresh_sandbox_network_policy",
                    failure_code="NETWORK_POLICY_REFRESH_RELAY_FAILED",
                    failure_message="Failed to relay network policy refresh command",
                    data={
                        "project_id": str(project_id) if project_id is not None else None,
                        "source_type": source_type,
                        "source_id": source_id,
                    },
                    require_ack=False,
                )
            except Exception:
                logger.debug(
                    "network policy refresh nudge failed; relying on reconcile loop",
                    extra={"sandbox_id": str(sandbox_id)},
                    exc_info=True,
                )
                return False

    results = await asyncio.gather(*(nudge(sandbox_id) for sandbox_id in sandbox_ids))
    return sum(1 for result in results if result)
