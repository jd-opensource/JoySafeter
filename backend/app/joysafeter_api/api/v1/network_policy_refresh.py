"""Helpers for event-driven sandbox network-policy refreshes."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_shared.ids import SandboxId
from app.joysafeter_shared.orchestrator_bridge.runtime_commands import publish_to_sandbox_owner_via_redis

logger = logging.getLogger(__name__)


async def mark_live_sandboxes_pending(
    db: AsyncSession,
    *,
    project_id: Optional[str],
    source_type: str,
    source_id: str,
) -> list[SandboxId]:
    """Flip live limited-networking sandboxes to ``pending`` WITHOUT committing.

    This is the atomic primitive shared by two callers:

    - The ``refresh_live_limited_sandbox_network_policies`` wrapper below, which
      commits and then fires a best-effort Redis nudge (non-atomic callers).
    - Credential mutation methods, which call this within their OWN transaction
      so the credential change and the pending mark commit together — no window
      where the DB holds the new credential but the sandbox is never re-pushed.

    Runs a single ``UPDATE ... RETURNING id`` (no select/update TOCTOU) over all
    live limited-networking sandboxes in the project, setting
    ``networking_status='pending'`` and clearing ``networking_last_error``. That
    row state IS the durable reconcile signal: the orchestrator's
    networking-reconcile loop scans ``pending`` every tick and re-pushes each
    policy, so convergence does not depend on any push. Marking a live sandbox
    ``pending`` does not disrupt it (nothing gates dispatch on
    ``networking_status``; the re-push is make-before-break).

    Returns the ids of the sandboxes marked (empty list if none). The caller is
    responsible for committing.
    """

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


async def refresh_live_limited_sandbox_network_policies(
    db: AsyncSession,
    *,
    project_id: Optional[str],
    reason: str,
    source_type: str,
    source_id: str,
) -> int:
    """Rebuild Envoy policy for live limited-networking sandboxes.

    This intentionally refreshes all live limited-networking sandboxes in the
    project. It is slightly broader than dependency-perfect targeting, but it is
    safe and prevents stale credential injection when vault/environment secrets
    are rotated, archived, or deleted.

    Convergence is durable, not push-dependent. We first mark the affected
    sandboxes ``networking_status='pending'`` in a single UPDATE. That row state
    IS the reconcile signal: the orchestrator's networking-reconcile loop scans
    ``pending`` sandboxes every tick and re-pushes their policy, so the refresh
    lands even if the Redis nudge below is lost (owner offline, Redis blip). The
    Redis publish is then a best-effort, fire-and-forget *accelerator* that turns
    "converges within one reconcile tick" into "converges almost immediately" —
    the API no longer blocks on per-sandbox ACKs.

    Marking a live sandbox ``pending`` does not disrupt it: nothing gates task
    dispatch on ``networking_status`` (it only drives a reuse-path skip
    optimization), and the re-push is make-before-break, so egress is not
    interrupted while the new policy warms.

    Returns the number of sandboxes marked for refresh.
    """

    # Durable reconcile signal, atomically: mark the targeted sandboxes 'pending'
    # (no select/update TOCTOU) and capture their ids. This row state IS what
    # guarantees convergence — the orchestrator's networking-reconcile loop scans
    # 'pending' every tick (oldest-first) and re-pushes each policy, independent
    # of the best-effort push below.
    sandbox_ids = await mark_live_sandboxes_pending(
        db,
        project_id=project_id,
        source_type=source_type,
        source_id=source_id,
    )
    await db.commit()
    if not sandbox_ids:
        return 0

    # Best-effort acceleration: nudge each owner orchestrator to reconcile now
    # instead of waiting for the next loop tick. Fire-and-forget — no ACK wait,
    # so a slow/absent owner never blocks the API. Delivery failures are benign
    # because the 'pending' marker above will be reconciled regardless.
    semaphore = asyncio.Semaphore(10)

    async def _nudge(sandbox_id) -> bool:
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
                        "project_id": project_id,
                        "source_type": source_type,
                        "source_id": source_id,
                    },
                    require_ack=False,
                )
            except Exception:
                # Never let a nudge failure surface — the pending marker converges.
                logger.debug(
                    "network policy refresh nudge failed; relying on reconcile loop",
                    extra={"sandbox_id": str(sandbox_id)},
                    exc_info=True,
                )
                return False

    nudge_results = await asyncio.gather(*(_nudge(sid) for sid in sandbox_ids))
    nudged = sum(1 for ok in nudge_results if ok)
    logger.info(
        "Marked sandboxes for network policy refresh",
        extra={
            "project_id": project_id,
            "reason": reason,
            "source_type": source_type,
            "source_id": source_id,
            "sandbox_count": len(sandbox_ids),
            "nudged_now": nudged,
        },
    )
    return len(sandbox_ids)
