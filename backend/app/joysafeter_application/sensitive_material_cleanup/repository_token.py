from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_session_repo import JoySafeterSessionRepo
from app.joysafeter_shared.utils.datetime import utc_now


async def erase_expired_repository_token_material(db: AsyncSession, *, limit: int = 100) -> int:
    if limit < 1:
        raise ValueError("limit must be positive")
    repo_ids = list(
        (
            await db.execute(
                select(JoySafeterSessionRepo.id)
                .where(
                    JoySafeterSessionRepo.encrypted_token != "",
                    JoySafeterSessionRepo.token_expires_at.is_not(None),
                    JoySafeterSessionRepo.token_expires_at <= utc_now(),
                )
                .order_by(JoySafeterSessionRepo.token_expires_at, JoySafeterSessionRepo.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars()
    )
    if not repo_ids:
        return 0
    now = utc_now()
    result = await db.execute(
        update(JoySafeterSessionRepo)
        .where(
            JoySafeterSessionRepo.id.in_(repo_ids),
            JoySafeterSessionRepo.encrypted_token != "",
        )
        .values(encrypted_token="", token_erased_at=now, updated_at=now)
    )
    return result.rowcount or 0
