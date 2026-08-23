from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_task_identity import JoySafeterTaskIdentityContext
from app.joysafeter_shared.utils.datetime import utc_now


async def erase_expired_task_identity_material(db: AsyncSession, *, limit: int = 100) -> int:
    if limit < 1:
        raise ValueError("limit must be positive")
    task_ids = list(
        (
            await db.execute(
                select(JoySafeterTaskIdentityContext.task_id)
                .where(
                    JoySafeterTaskIdentityContext.encrypted_credential.is_not(None),
                    JoySafeterTaskIdentityContext.expires_at <= utc_now(),
                )
                .order_by(JoySafeterTaskIdentityContext.expires_at, JoySafeterTaskIdentityContext.task_id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars()
    )
    if not task_ids:
        return 0
    result = await db.execute(
        update(JoySafeterTaskIdentityContext)
        .where(
            JoySafeterTaskIdentityContext.task_id.in_(task_ids),
            JoySafeterTaskIdentityContext.encrypted_credential.is_not(None),
        )
        .values(encrypted_credential=None, erased_at=utc_now(), updated_at=utc_now())
    )
    return result.rowcount or 0
