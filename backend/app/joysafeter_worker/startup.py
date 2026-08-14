"""Worker service startup hooks."""

from __future__ import annotations

from datetime import timedelta

from loguru import logger


async def run_worker_startup() -> None:
    await _recover_stuck_scanning_skills()


async def _recover_stuck_scanning_skills() -> None:
    """Reset skills stuck in 'scanning' state from a previous process crash.

    A skill is considered stuck if security_status='scanning' AND
    updated_at < now() - 5 minutes (the max scan timeout is 120s,
    so 5 min provides a generous margin against false positives).
    """
    from sqlalchemy import update

    from app.joysafeter_domain.models.joysafeter_skill import JoySafeterSkill, JoySafeterSkillSecurityStatus
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
                JoySafeterSkill.security_status == JoySafeterSkillSecurityStatus.SCANNING.value,
                JoySafeterSkill.updated_at < cutoff,
            )
            .values(security_status=JoySafeterSkillSecurityStatus.NOT_SCANNED.value)
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
    return None
