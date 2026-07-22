import uuid

import pytest
from error_contract_helpers import handled_app_error_payload
from fastapi import Request
from sqlalchemy import func, select

from app.joysafeter_api.api.v1.vaults import (
    archive_vault,
    create_credential,
    delete_credential,
    delete_vault,
    get_credential,
    get_vault,
    update_credential,
    update_vault,
)
from app.joysafeter_api.services import VaultService
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_vault import JoySafeterVault, JoySafeterVaultCredential
from app.joysafeter_domain.schemas.joysafeter_vault import (
    CreateCredentialRequest,
    UpdateCredentialRequest,
    UpdateVaultRequest,
)
from app.joysafeter_domain.services.joysafeter_vault_cipher import VaultCipher
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.utils.datetime import utc_now


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.MEMBER,
    )


def _project_auth_ctx(project_id: str) -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=project_id,
        role=JoySafeterRole.MEMBER,
    )


def _request(method: str = "POST") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/api/v1/vaults",
            "headers": [],
            "client": ("testclient", 50000),
        }
    )


async def _project_vault(db_session, *, project_id: str, name: str | None = None) -> JoySafeterVault:
    existing = await db_session.get(Project, project_id)
    if not existing:
        org = await db_session.get(Organization, "test-org")
        if not org:
            org = Organization(id="test-org", name="Test Org", slug="test-org")
            db_session.add(org)
        db_session.add(
            Project(
                id=project_id,
                org_id="test-org",
                name=project_id,
                slug=project_id,
                is_default=False,
            )
        )
        await db_session.commit()

    vault = JoySafeterVault(name=name or f"vault-{uuid.uuid4()}", description="", project_id=project_id)
    db_session.add(vault)
    await db_session.commit()
    await db_session.refresh(vault)
    return vault


async def _credential(db_session, *, vault_id: uuid.UUID, name: str | None = None) -> JoySafeterVaultCredential:
    cred = JoySafeterVaultCredential(
        vault_id=vault_id,
        name=name or f"cred-{uuid.uuid4()}",
        credential_type="static_bearer",
        mcp_server_url=f"https://mcp-{uuid.uuid4()}.example.com",
        token_value="token",
    )
    db_session.add(cred)
    await db_session.commit()
    await db_session.refresh(cred)
    return cred


async def _session_referencing_vault(db_session, vault_id: uuid.UUID, vault_ref: str) -> JoySafeterSession:
    agent = JoySafeterAgent(name=f"vault-session-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.flush()
    session = JoySafeterSession(agent_id=agent.id, status="idle", vault_ids=[vault_ref])
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    return session


async def _assert_vault_intact(db_session, vault_id: uuid.UUID) -> JoySafeterVault:
    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterVault).where(JoySafeterVault.id == vault_id))).scalar_one()
    assert row.deleted_at is None
    return row


async def _assert_credential_intact(db_session, cred_id: uuid.UUID) -> JoySafeterVaultCredential:
    db_session.expire_all()
    row = (
        await db_session.execute(select(JoySafeterVaultCredential).where(JoySafeterVaultCredential.id == cred_id))
    ).scalar_one()
    assert row.deleted_at is None
    return row


@pytest.mark.asyncio
async def test_get_vault_missing_vault_returns_structured_error(db_session):
    vault_id = uuid.uuid4()

    with pytest.raises(AppError) as exc_info:
        await get_vault(db_session, vault_id, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "VAULT_NOT_FOUND",
        "message": "Vault not found",
        "data": {"vault_id": str(vault_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_get_credential_missing_credential_returns_structured_error(db_session):
    vault = JoySafeterVault(name=f"vault-{uuid.uuid4()}", description="")
    db_session.add(vault)
    await db_session.commit()
    await db_session.refresh(vault)
    cred_id = uuid.uuid4()

    with pytest.raises(AppError) as exc_info:
        await get_credential(db_session, vault.id, cred_id, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "VAULT_CREDENTIAL_NOT_FOUND",
        "message": "Credential not found",
        "data": {"vault_id": str(vault.id), "credential_id": str(cred_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_update_archived_vault_rejects_without_mutating_metadata(db_session):
    vault = JoySafeterVault(
        name=f"archived-vault-{uuid.uuid4()}",
        description="original",
        metadata_={"tier": "prod"},
        archived_at=utc_now(),
    )
    db_session.add(vault)
    await db_session.commit()
    vault_id = vault.id

    with pytest.raises(AppError) as exc_info:
        await update_vault(
            UpdateVaultRequest(description="changed", metadata={"tier": "dev"}),
            _request("POST"),
            db_session,
            vault_id,
            _auth_ctx(),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "VAULT_ARCHIVED",
        "message": "Vault is archived",
        "data": {"vault_id": str(vault_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }

    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterVault).where(JoySafeterVault.id == vault_id))).scalar_one()
    assert row.description == "original"
    assert row.metadata_ == {"tier": "prod"}


@pytest.mark.asyncio
async def test_delete_vault_rejects_active_session_reference_without_deleting_row(db_session):
    vault = JoySafeterVault(name=f"active-session-vault-{uuid.uuid4()}", description="")
    db_session.add(vault)
    await db_session.commit()
    await db_session.refresh(vault)
    await _session_referencing_vault(db_session, vault.id, f"vault_{vault.id}")

    with pytest.raises(AppError) as exc_info:
        await delete_vault(_request("DELETE"), db_session, vault.id, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "VAULT_ACTIVE_SESSION_REFERENCE",
        "message": "Vault is referenced by one or more active sessions.",
        "data": {"vault_id": str(vault.id)},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }
    await _assert_vault_intact(db_session, vault.id)


@pytest.mark.asyncio
async def test_archive_vault_rejects_vlt_prefixed_active_session_reference(db_session):
    vault = JoySafeterVault(name=f"active-session-vlt-vault-{uuid.uuid4()}", description="")
    db_session.add(vault)
    await db_session.commit()
    await db_session.refresh(vault)
    await _session_referencing_vault(db_session, vault.id, f"vlt_{vault.id}")

    with pytest.raises(AppError) as exc_info:
        await archive_vault(_request("POST"), db_session, vault.id, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "VAULT_ACTIVE_SESSION_REFERENCE",
        "message": "Vault is referenced by one or more active sessions.",
        "data": {"vault_id": str(vault.id)},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }
    row = await _assert_vault_intact(db_session, vault.id)
    assert row.archived_at is None


@pytest.mark.asyncio
async def test_create_credential_rejects_archived_vault_without_creating_row(db_session):
    vault = JoySafeterVault(name=f"archived-credential-vault-{uuid.uuid4()}", description="", archived_at=utc_now())
    db_session.add(vault)
    await db_session.commit()
    vault_id = vault.id

    with pytest.raises(AppError) as exc_info:
        await create_credential(
            CreateCredentialRequest(
                name="Prod MCP",
                credential_type="static_bearer",
                mcp_server_url="https://mcp.example.com",
                token_value="secret-token",
            ),
            _request("POST"),
            db_session,
            vault_id,
            _auth_ctx(),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "VAULT_ARCHIVED",
        "message": "Vault is archived",
        "data": {"vault_id": str(vault_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
    count = (
        await db_session.execute(
            select(func.count())
            .select_from(JoySafeterVaultCredential)
            .where(JoySafeterVaultCredential.vault_id == vault_id)
        )
    ).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_update_archived_credential_rejects_without_mutating_secret(db_session):
    vault = JoySafeterVault(name=f"vault-{uuid.uuid4()}", description="")
    db_session.add(vault)
    await db_session.commit()
    await db_session.refresh(vault)
    cred = JoySafeterVaultCredential(
        vault_id=vault.id,
        name="Prod MCP",
        credential_type="static_bearer",
        mcp_server_url="https://mcp.example.com",
        token_value="old-token",
        archived_at=utc_now(),
    )
    db_session.add(cred)
    await db_session.commit()
    cred_id = cred.id

    with pytest.raises(AppError) as exc_info:
        await update_credential(
            UpdateCredentialRequest(name="Changed MCP", token_value="new-token"),
            _request("POST"),
            db_session,
            vault.id,
            cred_id,
            _auth_ctx(),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "VAULT_CREDENTIAL_ARCHIVED",
        "message": "Credential is archived",
        "data": {"vault_id": str(vault.id), "credential_id": str(cred_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }

    db_session.expire_all()
    row = (
        await db_session.execute(select(JoySafeterVaultCredential).where(JoySafeterVaultCredential.id == cred_id))
    ).scalar_one()
    assert row.name == "Prod MCP"
    assert row.token_value == "old-token"


@pytest.mark.asyncio
async def test_delete_credential_rejects_archived_vault_without_soft_deleting_row(db_session):
    vault = JoySafeterVault(name=f"archived-delete-vault-{uuid.uuid4()}", description="", archived_at=utc_now())
    db_session.add(vault)
    await db_session.commit()
    await db_session.refresh(vault)
    cred = JoySafeterVaultCredential(
        vault_id=vault.id,
        name="Prod MCP",
        credential_type="static_bearer",
        mcp_server_url="https://mcp-delete.example.com",
        token_value="token",
    )
    db_session.add(cred)
    await db_session.commit()
    cred_id = cred.id

    with pytest.raises(AppError) as exc_info:
        await delete_credential(_request("DELETE"), db_session, vault.id, cred_id, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "VAULT_ARCHIVED",
        "message": "Vault is archived",
        "data": {"vault_id": str(vault.id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }

    db_session.expire_all()
    row = (
        await db_session.execute(select(JoySafeterVaultCredential).where(JoySafeterVaultCredential.id == cred_id))
    ).scalar_one()
    assert row.deleted_at is None


@pytest.mark.asyncio
async def test_resolve_mcp_credentials_ignores_archived_vaults_and_credentials(db_session):
    active_vault = JoySafeterVault(name=f"active-vault-{uuid.uuid4()}", description="")
    archived_vault = JoySafeterVault(
        name=f"archived-vault-{uuid.uuid4()}",
        description="",
        archived_at=utc_now(),
    )
    db_session.add(active_vault)
    await db_session.commit()
    await db_session.refresh(active_vault)
    db_session.add(archived_vault)
    await db_session.commit()
    await db_session.refresh(archived_vault)

    db_session.add(
        JoySafeterVaultCredential(
            vault_id=active_vault.id,
            name="Active MCP",
            credential_type="static_bearer",
            mcp_server_url="https://active-mcp.example.com",
            token_value="active-token",
        )
    )
    await db_session.commit()
    db_session.add(
        JoySafeterVaultCredential(
            vault_id=active_vault.id,
            name="Archived Credential MCP",
            credential_type="static_bearer",
            mcp_server_url="https://archived-credential.example.com",
            token_value="archived-credential-token",
            archived_at=utc_now(),
        )
    )
    await db_session.commit()
    db_session.add(
        JoySafeterVaultCredential(
            vault_id=archived_vault.id,
            name="Archived Vault MCP",
            credential_type="static_bearer",
            mcp_server_url="https://archived-vault.example.com",
            token_value="archived-vault-token",
        )
    )
    await db_session.commit()

    resolved = await VaultService(db_session).resolve_mcp_credentials(
        [f"vault_{active_vault.id}", f"vault_{archived_vault.id}"],
        [
            {"name": "active", "url": "https://active-mcp.example.com", "headers": {}},
            {"name": "archived-credential", "url": "https://archived-credential.example.com", "headers": {}},
            {"name": "archived-vault", "url": "https://archived-vault.example.com", "headers": {}},
        ],
    )

    assert resolved == [
        {
            "name": "active",
            "url": "https://active-mcp.example.com",
            "headers": {"Authorization": "Bearer active-token"},
        },
        {"name": "archived-credential", "url": "https://archived-credential.example.com", "headers": {}},
        {"name": "archived-vault", "url": "https://archived-vault.example.com", "headers": {}},
    ]


@pytest.mark.asyncio
async def test_vault_credentials_keep_encrypted_storage_during_read_archive_and_resolution(db_session, monkeypatch):
    cipher = VaultCipher(VaultCipher.generate_key())
    monkeypatch.setattr("app.joysafeter_domain.services.joysafeter_vault_service._cipher", cipher)

    vault = JoySafeterVault(name=f"encrypted-vault-{uuid.uuid4()}", description="")
    db_session.add(vault)
    await db_session.commit()
    await db_session.refresh(vault)
    vault_id = vault.id

    svc = VaultService(db_session)
    cred = await svc.create_credential(
        vault_id=vault_id,
        name="Encrypted MCP",
        credential_type="mcp_oauth",
        mcp_server_url="https://encrypted-mcp.example.com",
        token_value="access-token",
        oauth_config={
            "client_id": "client-id",
            "client_secret": "client-secret",
            "refresh_token": "refresh-token",
            "token_endpoint": "https://auth.example.com/token",
            "expires_at": "2999-01-01T00:00:00+00:00",
        },
    )
    cred_id = cred.id

    db_session.expire_all()
    stored = (
        await db_session.execute(select(JoySafeterVaultCredential).where(JoySafeterVaultCredential.id == cred_id))
    ).scalar_one()
    assert stored.token_value.startswith("enc:")
    assert stored.oauth_config["client_secret"].startswith("enc:")
    assert stored.oauth_config["refresh_token"].startswith("enc:")

    await svc.get_credential(cred_id)
    resolved = await svc.resolve_mcp_credentials(
        [f"vault_{vault_id}"],
        [{"name": "encrypted", "url": "https://encrypted-mcp.example.com", "headers": {}}],
    )
    assert resolved == [
        {
            "name": "encrypted",
            "url": "https://encrypted-mcp.example.com",
            "headers": {"Authorization": "Bearer access-token"},
        }
    ]
    await svc.archive_credential(cred_id)

    db_session.expire_all()
    after = (
        await db_session.execute(select(JoySafeterVaultCredential).where(JoySafeterVaultCredential.id == cred_id))
    ).scalar_one()
    assert after.token_value.startswith("enc:")
    assert after.token_value != "access-token"
    assert after.oauth_config["client_secret"].startswith("enc:")
    assert after.oauth_config["refresh_token"].startswith("enc:")


@pytest.mark.asyncio
async def test_get_vault_route_rejects_cross_project_vault(db_session):
    vault = await _project_vault(db_session, project_id="project-b")

    with pytest.raises(AppError) as exc_info:
        await get_vault(db_session, vault.id, _project_auth_ctx("project-a"))

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "VAULT_NOT_FOUND",
        "message": "Vault not found",
        "data": {"vault_id": str(vault.id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_vault_writes_reject_cross_project_at_service_boundary(db_session):
    vault = await _project_vault(db_session, project_id="project-b")
    cred = await _credential(db_session, vault_id=vault.id)
    cred_id = cred.id

    updated = await VaultService(db_session).update_vault(
        vault.id,
        description="changed",
        metadata={"tier": "dev"},
        project_id="project-a",
    )
    archived = await VaultService(db_session).archive_vault(vault.id, project_id="project-a")
    deleted = await VaultService(db_session).delete_vault(vault.id, project_id="project-a")

    assert updated is None
    assert archived is False
    assert deleted is False
    row = await _assert_vault_intact(db_session, vault.id)
    assert row.description == ""
    assert row.metadata_ == {}
    assert row.archived_at is None
    await _assert_credential_intact(db_session, cred_id)


@pytest.mark.asyncio
async def test_credential_writes_reject_wrong_parent_vault_at_service_boundary(db_session):
    vault_a = await _project_vault(db_session, project_id="project-a")
    vault_b = await _project_vault(db_session, project_id="project-b")
    cred = await _credential(db_session, vault_id=vault_b.id, name="Project B MCP")

    updated = await VaultService(db_session).update_credential(
        cred.id,
        name="Changed MCP",
        token_value="new-token",
        vault_id=vault_a.id,
    )
    archived = await VaultService(db_session).archive_credential(cred.id, vault_id=vault_a.id)
    deleted = await VaultService(db_session).delete_credential(cred.id, vault_id=vault_a.id)

    assert updated is None
    assert archived is False
    assert deleted is False
    row = await _assert_credential_intact(db_session, cred.id)
    assert row.name == "Project B MCP"
    assert row.token_value == "token"
    assert row.archived_at is None


@pytest.mark.asyncio
async def test_credential_children_reject_cross_project_parent_at_service_boundary(db_session):
    vault_b = await _project_vault(db_session, project_id="project-b")
    cred = await _credential(db_session, vault_id=vault_b.id, name="Project B MCP")
    vault_b_id = vault_b.id
    cred_id = cred.id
    svc = VaultService(db_session)

    listed, has_more = await svc.list_credentials(vault_b_id, project_id="project-a")
    found = await svc.get_credential(cred_id, vault_id=vault_b_id, project_id="project-a")
    created = await svc.create_credential(
        vault_id=vault_b_id,
        name="Project A write",
        credential_type="static_bearer",
        mcp_server_url="https://cross-project.example.com",
        token_value="new-token",
        project_id="project-a",
    )
    updated = await svc.update_credential(
        cred_id,
        name="Changed MCP",
        token_value="new-token",
        vault_id=vault_b_id,
        project_id="project-a",
    )
    archived = await svc.archive_credential(cred_id, vault_id=vault_b_id, project_id="project-a")
    deleted = await svc.delete_credential(cred_id, vault_id=vault_b_id, project_id="project-a")

    assert listed == []
    assert has_more is False
    assert found is None
    assert created is None
    assert updated is None
    assert archived is False
    assert deleted is False

    row = await _assert_credential_intact(db_session, cred_id)
    assert row.name == "Project B MCP"
    assert row.token_value == "token"
    assert row.archived_at is None
    total = (
        await db_session.execute(
            select(func.count())
            .select_from(JoySafeterVaultCredential)
            .where(JoySafeterVaultCredential.vault_id == vault_b_id)
        )
    ).scalar_one()
    assert total == 1


@pytest.mark.asyncio
async def test_create_vault_purges_only_same_project_soft_deleted_name(db_session):
    stale_other_project = await _project_vault(db_session, project_id="project-b", name="shared-vault")
    stale_same_project = await _project_vault(db_session, project_id="project-a", name="shared-vault")
    stale_other_project_id = stale_other_project.id
    stale_same_project_id = stale_same_project.id
    stale_other_project.deleted_at = utc_now()
    stale_same_project.deleted_at = utc_now()
    await db_session.commit()

    created = await VaultService(db_session).create_vault(
        "shared-vault",
        description="replacement",
        project_id="project-a",
    )

    assert created.project_id == "project-a"
    db_session.expire_all()
    other_project_row = (
        await db_session.execute(select(JoySafeterVault).where(JoySafeterVault.id == stale_other_project_id))
    ).scalar_one()
    same_project_row = (
        await db_session.execute(select(JoySafeterVault).where(JoySafeterVault.id == stale_same_project_id))
    ).scalar_one_or_none()
    assert other_project_row.deleted_at is not None
    assert same_project_row is None


@pytest.mark.asyncio
async def test_resolve_mcp_credentials_filters_vaults_by_project_when_provided(db_session):
    vault_a = await _project_vault(db_session, project_id="project-a")
    vault_b = await _project_vault(db_session, project_id="project-b")
    db_session.add(
        JoySafeterVaultCredential(
            vault_id=vault_b.id,
            name="Project B MCP",
            credential_type="static_bearer",
            mcp_server_url="https://project-b-mcp.example.com",
            token_value="project-b-token",
        )
    )
    await db_session.commit()

    unresolved = await VaultService(db_session).resolve_mcp_credentials(
        [f"vault_{vault_b.id}"],
        [{"name": "project-b", "url": "https://project-b-mcp.example.com", "headers": {}}],
        project_id="project-a",
    )
    resolved = await VaultService(db_session).resolve_mcp_credentials(
        [f"vault_{vault_b.id}"],
        [{"name": "project-b", "url": "https://project-b-mcp.example.com", "headers": {}}],
        project_id="project-b",
    )
    empty_project = await VaultService(db_session).resolve_mcp_credentials(
        [f"vault_{vault_a.id}"],
        [{"name": "project-b", "url": "https://project-b-mcp.example.com", "headers": {}}],
        project_id="project-a",
    )

    assert unresolved == [{"name": "project-b", "url": "https://project-b-mcp.example.com", "headers": {}}]
    assert resolved == [
        {
            "name": "project-b",
            "url": "https://project-b-mcp.example.com",
            "headers": {"Authorization": "Bearer project-b-token"},
        }
    ]
    assert empty_project == [{"name": "project-b", "url": "https://project-b-mcp.example.com", "headers": {}}]
