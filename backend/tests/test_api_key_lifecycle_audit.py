import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select
from starlette.requests import Request

from app.joysafeter_api.api.v1 import auth
from app.joysafeter_api.api.v1.audit import audit_joysafeter_event
from app.joysafeter_domain.models.joysafeter_api_key import JoySafeterApiKey
from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Member, Organization
from app.joysafeter_domain.models.joysafeter_project import Project, ProjectMember
from app.joysafeter_domain.models.joysafeter_security_audit_log import SecurityAuditLog
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.common.joysafeter_auth import dependencies as auth_dependencies
from app.joysafeter_shared.ids import (
    ApiKeyId,
    OrganizationId,
    OrganizationMemberId,
    ProjectId,
    ProjectMemberId,
    UserId,
)

APP_ROOT = Path(__file__).resolve().parents[1] / "app"


def _request(method: str = "POST") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/api/v1/auth/projects/project/api-keys",
            "headers": [(b"user-agent", b"api-key-lifecycle-test")],
            "client": ("127.0.0.1", 4321),
        }
    )


@pytest.mark.no_db
def test_api_key_api_depends_on_the_application_service():
    api_source = (APP_ROOT / "joysafeter_api/api/v1/auth.py").read_text()

    assert "from app.joysafeter_application.api_keys import" in api_source
    assert "ApiKeyService(db)" in api_source


async def _seed_project(db_session):
    suffix = uuid.uuid4().hex
    user = AuthUser(id=UserId.new(), name="Owner", email=f"{suffix}@example.com")
    organization = Organization(id=OrganizationId.new(), name="Org", slug=f"org-{suffix}")
    project = Project(
        id=ProjectId.new(),
        org_id=organization.id,
        created_by_user_id=user.id,
        name="Project",
        slug=f"project-{suffix}",
        is_default=False,
    )
    db_session.add_all([user, organization, project])
    await db_session.flush()
    db_session.add_all(
        [
            Member(
                id=OrganizationMemberId.new(),
                user_id=user.id,
                organization_id=organization.id,
                role="owner",
            ),
            ProjectMember(id=ProjectMemberId.new(), project_id=project.id, user_id=user.id, role="admin"),
        ]
    )
    await db_session.commit()
    return user, organization, project


def _auth_context(user: AuthUser, organization: Organization, project: Project) -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id=user.id,
        org_id=organization.id,
        project_id=project.id,
        role=JoySafeterRole.OWNER,
        project_role="admin",
    )


@pytest.mark.asyncio
async def test_api_key_create_rolls_back_when_audit_write_fails(db_session, monkeypatch):
    user, organization, project = await _seed_project(db_session)
    project_id = project.id

    async def fail_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(auth, "audit_joysafeter_event", fail_audit)

    with pytest.raises(RuntimeError, match="audit unavailable"):
        await auth.create_project_api_key(
            project_id,
            auth.CreateApiKeyRequest(name="deploy", role="viewer"),
            _request(),
            db_session,
            _auth_context(user, organization, project),
        )

    count = await db_session.scalar(
        select(func.count()).select_from(JoySafeterApiKey).where(JoySafeterApiKey.project_id == project_id)
    )
    assert count == 0


@pytest.mark.asyncio
async def test_api_key_creation_uses_uuid7(db_session):
    user, organization, project = await _seed_project(db_session)

    created = await auth.create_project_api_key(
        project.id,
        auth.CreateApiKeyRequest(name="uuid7", role="viewer"),
        _request(),
        db_session,
        _auth_context(user, organization, project),
    )

    assert created.id.uuid.version == 7


@pytest.mark.asyncio
async def test_api_key_create_persists_expiry_and_returns_active_status(db_session):
    user, organization, project = await _seed_project(db_session)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    created = await auth.create_project_api_key(
        project.id,
        auth.CreateApiKeyRequest(name="expiring", role="viewer", expires_at=expires_at),
        _request(),
        db_session,
        _auth_context(user, organization, project),
    )

    assert created.status == "active"
    assert created.expires_at == expires_at
    assert created.revoked_at is None


@pytest.mark.asyncio
async def test_api_key_list_includes_active_expired_and_revoked_history(db_session):
    user, organization, project = await _seed_project(db_session)
    now = datetime.now(timezone.utc)
    await _seed_api_key(db_session, user, organization, project, name="active")
    await _seed_api_key(
        db_session,
        user,
        organization,
        project,
        name="expired",
        created_at=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),
    )
    await _seed_api_key(
        db_session,
        user,
        organization,
        project,
        name="revoked",
        revoked_at=now - timedelta(minutes=30),
    )

    response = await auth.list_project_api_keys(
        project.id,
        50,
        None,
        db_session,
        _auth_context(user, organization, project),
    )

    assert {item.name: item.status for item in response.data} == {
        "active": "active",
        "expired": "expired",
        "revoked": "revoked",
    }


@pytest.mark.asyncio
async def test_api_key_revoke_rolls_back_when_audit_write_fails(db_session, monkeypatch):
    user, organization, project = await _seed_project(db_session)
    raw_key = f"existing-{uuid.uuid4().hex}"
    api_key = JoySafeterApiKey(
        id=ApiKeyId.new(),
        project_id=project.id,
        org_id=organization.id,
        name="deploy",
        key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
        key_prefix=raw_key[:16],
        created_by=user.id,
        role="viewer",
    )
    db_session.add(api_key)
    await db_session.commit()
    key_id = api_key.id

    async def fail_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(auth, "audit_joysafeter_event", fail_audit)

    with pytest.raises(RuntimeError, match="audit unavailable"):
        await auth.revoke_project_api_key(
            project.id,
            key_id,
            _request("DELETE"),
            db_session,
            _auth_context(user, organization, project),
        )

    revoked_at = await db_session.scalar(select(JoySafeterApiKey.revoked_at).where(JoySafeterApiKey.id == key_id))
    assert revoked_at is None


@pytest.mark.asyncio
async def test_repeated_api_key_revoke_preserves_timestamp_and_single_audit(db_session):
    user, organization, project = await _seed_project(db_session)
    api_key, _ = await _seed_api_key(db_session, user, organization, project)
    key_id = api_key.id
    context = _auth_context(user, organization, project)

    await auth.revoke_project_api_key(project.id, key_id, _request("DELETE"), db_session, context)
    first_revoked_at = await db_session.scalar(select(JoySafeterApiKey.revoked_at).where(JoySafeterApiKey.id == key_id))

    await auth.revoke_project_api_key(project.id, key_id, _request("DELETE"), db_session, context)
    second_revoked_at = await db_session.scalar(
        select(JoySafeterApiKey.revoked_at).where(JoySafeterApiKey.id == key_id)
    )
    audit_count = await db_session.scalar(
        select(func.count())
        .select_from(SecurityAuditLog)
        .where(
            SecurityAuditLog.event_type == "api_key.revoked",
            SecurityAuditLog.details["target_id"].astext == str(key_id),
        )
    )

    assert second_revoked_at == first_revoked_at
    assert audit_count == 1


@pytest.mark.asyncio
async def test_audit_event_records_api_key_principal_identity(db_session):
    user, organization, project = await _seed_project(db_session)
    key_id = ApiKeyId.new()
    context = JoySafeterAuthContext(
        user_id=user.id,
        org_id=organization.id,
        project_id=project.id,
        role=JoySafeterRole.MEMBER,
        principal_type="api_key",
        principal_id=str(key_id),
        project_role="editor",
    )

    await audit_joysafeter_event(
        db_session,
        _request(),
        context,
        event_type="test.api_key_actor",
        target_type="test",
        target_id="target",
    )

    entry = await db_session.scalar(select(SecurityAuditLog).where(SecurityAuditLog.event_type == "test.api_key_actor"))
    assert entry is not None
    assert entry.user_id == user.id
    assert entry.details["principal_type"] == "api_key"
    assert entry.details["principal_id"] == str(key_id)


async def _seed_api_key(db_session, user: AuthUser, organization: Organization, project: Project, **values):
    raw_key = f"existing-{uuid.uuid4().hex}"
    name = values.pop("name", "runtime")
    api_key = JoySafeterApiKey(
        id=ApiKeyId.new(),
        project_id=project.id,
        org_id=organization.id,
        name=name,
        key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
        key_prefix=raw_key[:16],
        created_by=user.id,
        role="viewer",
        **values,
    )
    db_session.add(api_key)
    await db_session.commit()
    return api_key, raw_key


@pytest.mark.asyncio
async def test_api_key_auth_survives_last_used_commit_failure(db_session, monkeypatch):
    user, organization, project = await _seed_project(db_session)
    api_key, raw_key = await _seed_api_key(db_session, user, organization, project)
    user_id = user.id
    key_id = api_key.id

    async def fail_commit():
        raise RuntimeError("last-used write unavailable")

    monkeypatch.setattr(db_session, "commit", fail_commit)

    context = await auth_dependencies._auth_via_api_key(raw_key, db_session)

    assert context is not None
    assert context.user_id == user_id
    assert context.principal_type == "api_key"
    assert context.principal_id == str(key_id)


@pytest.mark.asyncio
async def test_api_key_last_used_timestamp_never_moves_backwards(db_session):
    user, organization, project = await _seed_project(db_session)
    future = datetime.now(timezone.utc) + timedelta(days=1)
    api_key, raw_key = await _seed_api_key(
        db_session,
        user,
        organization,
        project,
        last_used_at=future,
    )

    context = await auth_dependencies._auth_via_api_key(raw_key, db_session)

    assert context is not None
    last_used_at = await db_session.scalar(
        select(JoySafeterApiKey.last_used_at).where(JoySafeterApiKey.id == api_key.id)
    )
    assert last_used_at == future


@pytest.mark.asyncio
async def test_api_key_auth_rejects_exact_expiry_boundary(db_session, monkeypatch):
    user, organization, project = await _seed_project(db_session)
    boundary = datetime.now(timezone.utc) + timedelta(minutes=5)
    _, raw_key = await _seed_api_key(
        db_session,
        user,
        organization,
        project,
        created_at=boundary - timedelta(hours=1),
        expires_at=boundary,
    )

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return boundary if tz is not None else boundary.replace(tzinfo=None)

    monkeypatch.setattr(auth_dependencies, "datetime", FrozenDateTime)

    assert await auth_dependencies._auth_via_api_key(raw_key, db_session) is None
