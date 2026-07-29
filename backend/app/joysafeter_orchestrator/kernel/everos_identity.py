from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Member
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_shared.everos_scope import (
    EVEROS_SESSION_USER_EMAIL_METADATA_KEY,
    EVEROS_SESSION_USER_ID_METADATA_KEY,
    EVEROS_SESSION_USER_NAME_METADATA_KEY,
    compose_everos_user_id,
)


@dataclass(frozen=True)
class EverOSUserIdentity:
    joysafeter_user_id: str | None
    joysafeter_user_name: str | None
    joysafeter_user_email: str | None

    @property
    def everos_user_id(self) -> str:
        return compose_everos_user_id(
            user_name=self.joysafeter_user_name,
            user_id=self.joysafeter_user_id,
        )


def identity_from_session_metadata(metadata: dict | None) -> EverOSUserIdentity | None:
    if not isinstance(metadata, dict):
        return None
    user_id = metadata.get(EVEROS_SESSION_USER_ID_METADATA_KEY)
    user_name = metadata.get(EVEROS_SESSION_USER_NAME_METADATA_KEY)
    user_email = metadata.get(EVEROS_SESSION_USER_EMAIL_METADATA_KEY)
    if not (user_id or user_name):
        return None
    return EverOSUserIdentity(
        joysafeter_user_id=str(user_id) if user_id else None,
        joysafeter_user_name=str(user_name) if user_name else None,
        joysafeter_user_email=str(user_email) if user_email else None,
    )


async def resolve_everos_user_identity_for_session(
    db: AsyncSession,
    session_id: uuid.UUID | None,
    *,
    session: JoySafeterSession | None = None,
    project_id: Any | None = None,
) -> EverOSUserIdentity:
    """Resolve the JoySafeter user that owns EverOS user memories for a session."""
    if session is None and session_id is not None:
        session = await db.get(JoySafeterSession, session_id)

    identity = identity_from_session_metadata(
        getattr(session, "metadata_", None) if session is not None else None
    )
    if identity is not None:
        return identity

    project_id = project_id or getattr(session, "project_id", None)
    if project_id:
        identity = await _resolve_single_project_member_identity(db, str(project_id))
        if identity is not None:
            return identity

    return EverOSUserIdentity(
        joysafeter_user_id=None,
        joysafeter_user_name=None,
        joysafeter_user_email=None,
    )


async def resolve_everos_user_id_for_session(
    db: AsyncSession,
    session_id: uuid.UUID | None,
    *,
    session: JoySafeterSession | None = None,
    project_id: Any | None = None,
) -> str:
    identity = await resolve_everos_user_identity_for_session(
        db,
        session_id,
        session=session,
        project_id=project_id,
    )
    return identity.everos_user_id


async def _resolve_single_project_member_identity(
    db: AsyncSession,
    project_id: str,
) -> EverOSUserIdentity | None:
    project_result = await db.execute(
        select(Project.org_id).where(Project.id == project_id).limit(1)
    )
    org_id = project_result.scalar_one_or_none()
    if not org_id:
        return None

    result = await db.execute(
        select(AuthUser)
        .join(Member, Member.user_id == AuthUser.id)
        .where(Member.organization_id == org_id)
        .order_by(AuthUser.name.asc(), AuthUser.id.asc())
        .limit(2)
    )
    users = list(result.scalars().all())
    if len(users) != 1:
        return None
    user = users[0]
    return EverOSUserIdentity(
        joysafeter_user_id=str(user.id),
        joysafeter_user_name=str(user.name) if user.name else None,
        joysafeter_user_email=str(user.email) if user.email else None,
    )
