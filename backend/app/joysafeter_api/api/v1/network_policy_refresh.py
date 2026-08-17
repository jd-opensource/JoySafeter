"""API compatibility wrapper for sandbox network-policy refreshes."""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_infrastructure.network_policy.refresh import (
    mark_live_sandboxes_pending,
    nudge_sandbox_network_policy_refreshes,
)

__all__ = [
    "mark_live_sandboxes_pending",
    "nudge_sandbox_network_policy_refreshes",
    "refresh_live_limited_sandbox_network_policies",
]


async def refresh_live_limited_sandbox_network_policies(
    db: AsyncSession,
    *,
    project_id: Optional[str],
    reason: str,
    source_type: str,
    source_id: str,
) -> int:
    sandbox_ids = await mark_live_sandboxes_pending(
        db,
        project_id=project_id,
        source_type=source_type,
        source_id=source_id,
    )
    await db.commit()
    if not sandbox_ids:
        return 0
    await nudge_sandbox_network_policy_refreshes(
        sandbox_ids,
        project_id=project_id,
        reason=reason,
        source_type=source_type,
        source_id=source_id,
    )
    return len(sandbox_ids)
