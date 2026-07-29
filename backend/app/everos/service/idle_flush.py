"""Idle-buffer auto-flush.

Scans conversation_status for sessions whose buffer has un-extracted
content and has been idle past a threshold, then forces boundary
extraction via memorize(is_final=True). Best-effort per session.
"""

from __future__ import annotations

import datetime as dt

from app.everos.core.observability.logging import get_logger
from app.everos.infra.persistence.sqlite.repos.conversation_status import (
    conversation_status_repo,
)
from app.everos.service.memorize import memorize

logger = get_logger(__name__)


async def scan_and_flush_idle(*, now: dt.datetime, threshold_seconds: int) -> int:
    """Flush every idle, un-extracted session. Returns count flushed."""
    cutoff = now - dt.timedelta(seconds=threshold_seconds)
    candidates = await conversation_status_repo.list_idle_candidates(cutoff)
    flushed = 0
    for app_id, project_id, session_id in candidates:
        try:
            await memorize(
                {
                    "session_id": session_id,
                    "app_id": app_id,
                    "project_id": project_id,
                    "messages": [],
                },
                is_final=True,
            )
            flushed += 1
        except Exception as exc:  # best-effort per session
            logger.warning(
                "idle_flush_failed",
                extra={"session_id": session_id, "project_id": project_id, "error": str(exc)},
            )
    if flushed:
        logger.info("idle_flush_completed", extra={"flushed": flushed})
    return flushed
