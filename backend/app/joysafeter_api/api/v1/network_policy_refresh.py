"""Helpers for event-driven sandbox network-policy refreshes."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_api.runtime_commands import publish_to_sandbox_owner_via_redis
from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox

logger = logging.getLogger(__name__)


async def refresh_live_limited_sandbox_network_policies(
    db: AsyncSession,
    *,
    project_id: Optional[str],
    reason: str,
    source_type: str,
    source_id: str,
) -> int:
    """Ask owner orchestrators to rebuild Envoy policy for live limited sandboxes.

    This intentionally refreshes all live limited-networking sandboxes in the
    project. It is slightly broader than dependency-perfect targeting, but it is
    safe and prevents stale credential injection when vault/environment secrets
    are rotated, archived, or deleted.
    """

    conditions = [
        JoySafeterSandbox.destroyed_at.is_(None),
        JoySafeterSandbox.status.in_(["idle", "running", "creating", "provisioning"]),
        JoySafeterSandbox.config["fingerprint"]["networking"]["type"].astext == "limited",
    ]
    if project_id is not None:
        conditions.append(JoySafeterSandbox.project_id == project_id)

    result = await db.execute(select(JoySafeterSandbox.id).where(*conditions))
    sandbox_ids = [row[0] for row in result.all()]
    semaphore = asyncio.Semaphore(10)

    async def _publish(sandbox_id) -> bool:
        async with semaphore:
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
                    "project_id": project_id,
                    "source_type": source_type,
                    "source_id": source_id,
                },
                require_ack=True,
                ack_timeout_seconds=15,
            )

    results = await asyncio.gather(*(_publish(sandbox_id) for sandbox_id in sandbox_ids))
    delivered = sum(1 for ok in results if ok)
    if sandbox_ids:
        logger.info(
            "Relayed network policy refresh commands",
            extra={
                "project_id": project_id,
                "reason": reason,
                "source_type": source_type,
                "source_id": source_id,
                "sandbox_count": len(sandbox_ids),
                "delivered": delivered,
            },
        )
    return delivered
