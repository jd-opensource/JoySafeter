from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext
from app.joysafeter_shared.everos_scope import build_everos_session_user_metadata


async def merge_current_user_session_metadata(
    metadata: dict | None,
    *,
    db: AsyncSession,
    auth_ctx: JoySafeterAuthContext,
) -> dict:
    """Persist the current JoySafeter user identity on a new session."""
    merged = dict(metadata or {})
    result = await db.execute(
        select(AuthUser).where(AuthUser.id == auth_ctx.user_id).limit(1)
    )
    user = result.scalar_one_or_none()
    merged.update(
        build_everos_session_user_metadata(
            user_id=auth_ctx.user_id,
            user_name=getattr(user, "name", None),
            user_email=getattr(user, "email", None),
        )
    )
    return merged
