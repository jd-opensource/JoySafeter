"""Worker service startup hooks."""

from __future__ import annotations

from datetime import timedelta

from loguru import logger


async def run_worker_startup() -> None:
    await _check_docker_availability()
    await _recover_stuck_scanning_skills()


async def _check_docker_availability() -> None:
    from app.joysafeter_shared.runtime.lifecycle import _check_docker_availability as _check

    await _check()


async def _recover_stuck_scanning_skills() -> None:
    """Reset skills stuck in 'scanning' state from a previous process crash.

    A skill is considered stuck if security_status='scanning' AND
    updated_at < now() - 5 minutes (the max scan timeout is 120s,
    so 5 min provides a generous margin against false positives).
    """
    from sqlalchemy import update

    from app.joysafeter_domain.models.joysafeter_skill import JoySafeterSkill
    from app.joysafeter_shared.config.settings import settings
    from app.joysafeter_shared.database import AsyncSessionLocal
    from app.joysafeter_shared.utils.datetime import utc_now

    if not settings.skill_security_scan_enabled:
        return

    cutoff = utc_now() - timedelta(minutes=5)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(JoySafeterSkill)
            .where(
                JoySafeterSkill.security_status == "scanning",
                JoySafeterSkill.updated_at < cutoff,
            )
            .values(security_status="not_scanned")
            .returning(JoySafeterSkill.id)
        )
        recovered_ids = [row[0] for row in result.fetchall()]
        await db.commit()
        if recovered_ids:
            logger.info(
                "Recovered %d skill(s) stuck in 'scanning' state: %s",
                len(recovered_ids),
                [str(sid) for sid in recovered_ids],
            )


async def run_worker_shutdown() -> None:
    # The legacy execution_event_bus subscribers, CheckpointerManager
    # (LangGraph Postgres saver), and CLI container pool were removed
    # during prior cleanup waves. Nothing to tear down here for now; we
    # keep the symbol so callers don't need to special-case the absence
    # of a shutdown hook.
    return None
