from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.joysafeter_application.credentials.ports import (
    CredentialAccessAuditEntry,
    CredentialAccessResult,
)
from app.joysafeter_domain.models.joysafeter_credential_access_audit import (
    JoySafeterCredentialAccessAudit,
)
from app.joysafeter_shared.ids import CredentialId as SqlCredentialId


class SqlAlchemyCredentialAccessAuditAdapter:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def append(self, entry: CredentialAccessAuditEntry) -> bool:
        values = {
            "project_id": str(entry.project_id),
            "credential_id": SqlCredentialId.from_public(str(entry.credential_id)),
            "credential_kind": entry.credential_kind,
            "usage": entry.usage.value,
            "consumer_type": entry.consumer_type,
            "consumer_id": entry.consumer_id,
            "principal_type": entry.actor.principal_type,
            "principal_id": entry.actor.principal_id,
            "user_id": entry.actor.user_id,
            "org_id": entry.actor.org_id,
            "role": entry.actor.role,
            "ip_address": entry.actor.ip_address,
            "user_agent": entry.actor.user_agent,
            "session_id": entry.session_id,
            "task_id": entry.task_id,
            "generation": entry.generation,
            "field_names": [str(field) for field in entry.field_names],
            "result": entry.result.value,
            "error_code": entry.error_code,
        }
        statement = insert(JoySafeterCredentialAccessAudit).values(**values)
        if (
            entry.result is CredentialAccessResult.SUCCESS
            and entry.session_id is not None
            and entry.generation is not None
        ):
            statement = statement.on_conflict_do_nothing(
                index_elements=(
                    "session_id",
                    "generation",
                    "credential_id",
                    "usage",
                    "consumer_type",
                    "consumer_id",
                ),
                index_where=text("result = 'success' AND session_id IS NOT NULL AND generation IS NOT NULL"),
            )
        async with self._session_factory() as db:
            result = await db.execute(statement)
            await db.commit()
            return result.rowcount == 1
