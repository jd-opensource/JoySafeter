from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_credential import (
    JoySafeterCredential,
    JoySafeterSessionCredentialGroup,
)
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_shared.common.app_errors import ResourceConflictError
from app.joysafeter_shared.ids import CredentialGroupId


def credential_group_url_conflict(normalized_url: str) -> ResourceConflictError:
    return ResourceConflictError(
        code="CREDENTIAL_GROUP_URL_CONFLICT",
        message="An mcp credential for this server url conflicts with the credential groups of an active session",
        data={"normalized_mcp_server_url": normalized_url},
        user_action="fix_input",
    )


def is_credential_group_url_integrity_error(exc: IntegrityError) -> bool:
    message = str(getattr(exc, "orig", None) or exc).lower()
    return "uq_credentials_group_url" in message or (
        "joysafeter_credentials" in message
        and "normalized_mcp_server_url" in message
        and "unique" in message
    )


async def reject_member_url_conflict_for_bound_sessions(
    db: AsyncSession,
    *,
    group_id: CredentialGroupId,
    normalized_url: str,
    project_id: str,
) -> None:
    active_session_ids = (
        select(JoySafeterSessionCredentialGroup.session_id)
        .join(
            JoySafeterSession,
            JoySafeterSession.id == JoySafeterSessionCredentialGroup.session_id,
        )
        .where(
            JoySafeterSessionCredentialGroup.credential_group_id == group_id,
            JoySafeterSession.project_id == project_id,
            JoySafeterSession.archived_at.is_(None),
            JoySafeterSession.status != "terminated",
        )
    )
    peer_group_ids = select(JoySafeterSessionCredentialGroup.credential_group_id).where(
        JoySafeterSessionCredentialGroup.session_id.in_(active_session_ids),
        JoySafeterSessionCredentialGroup.credential_group_id != group_id,
    )
    conflict = await db.execute(
        select(JoySafeterCredential.id)
        .where(
            JoySafeterCredential.project_id == project_id,
            JoySafeterCredential.group_id.in_(peer_group_ids),
            JoySafeterCredential.kind == "mcp",
            JoySafeterCredential.normalized_mcp_server_url == normalized_url,
            JoySafeterCredential.archived_at.is_(None),
            JoySafeterCredential.deleted_at.is_(None),
        )
        .limit(1)
    )
    if conflict.scalar_one_or_none() is not None:
        raise credential_group_url_conflict(normalized_url)
