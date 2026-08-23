from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.joysafeter_application.credentials.ports import (
    CredentialAccessAuditEntry,
    CredentialAccessResult,
    CredentialAuditActor,
)
from app.joysafeter_domain.credentials import (
    CredentialFieldName,
    CredentialUsage,
    ProjectId,
)
from app.joysafeter_domain.credentials import CredentialId as DomainCredentialId
from app.joysafeter_domain.models.joysafeter_credential_access_audit import JoySafeterCredentialAccessAudit
from app.joysafeter_infrastructure.credentials.access_audit_adapter import (
    SqlAlchemyCredentialAccessAuditAdapter,
)
from app.joysafeter_shared.ids import CredentialId as SqlCredentialId
from app.joysafeter_shared.ids import SessionId, TaskId


def _entry(*, result: CredentialAccessResult, error_code: str | None = None) -> CredentialAccessAuditEntry:
    credential_id = SqlCredentialId.new()
    return CredentialAccessAuditEntry(
        project_id=ProjectId("project-1"),
        credential_id=DomainCredentialId(str(credential_id)),
        credential_kind="service",
        usage=CredentialUsage.HTTP_EGRESS,
        consumer_type="sandbox",
        consumer_id=None,
        actor=CredentialAuditActor(
            user_id="user-1",
            principal_type="api_key",
            principal_id="key-1",
            ip_address="203.0.113.10",
            user_agent="credential-runtime/1.0",
            org_id="org-1",
            role="member",
        ),
        session_id=SessionId.new(),
        task_id=TaskId.new(),
        generation=4,
        field_names=(CredentialFieldName("TOKEN"),),
        result=result,
        error_code=error_code,
    )


@pytest.mark.asyncio
async def test_access_audit_writer_deduplicates_runtime_success(db_session) -> None:
    factory = async_sessionmaker(db_session.bind, class_=AsyncSession, expire_on_commit=False)
    adapter = SqlAlchemyCredentialAccessAuditAdapter(factory)
    entry = _entry(result=CredentialAccessResult.SUCCESS)

    assert await adapter.append(entry) is True
    assert await adapter.append(entry) is False

    count = await db_session.scalar(select(func.count()).select_from(JoySafeterCredentialAccessAudit))
    assert count == 1


@pytest.mark.asyncio
async def test_access_audit_writer_keeps_each_failure(db_session) -> None:
    factory = async_sessionmaker(db_session.bind, class_=AsyncSession, expire_on_commit=False)
    adapter = SqlAlchemyCredentialAccessAuditAdapter(factory)
    entry = _entry(result=CredentialAccessResult.FAILED, error_code="decrypt_failed")

    assert await adapter.append(entry) is True
    assert await adapter.append(entry) is True

    rows = (
        (
            await db_session.execute(
                select(JoySafeterCredentialAccessAudit).where(
                    JoySafeterCredentialAccessAudit.credential_id
                    == SqlCredentialId.from_public(str(entry.credential_id))
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert all(row.field_names == ["TOKEN"] for row in rows)
    assert all(row.error_code == "decrypt_failed" for row in rows)
    assert all(row.user_id == "user-1" for row in rows)
    assert all(row.org_id == "org-1" for row in rows)
    assert all(row.role == "member" for row in rows)
    assert all(row.ip_address == "203.0.113.10" for row in rows)
    assert all(row.user_agent == "credential-runtime/1.0" for row in rows)
