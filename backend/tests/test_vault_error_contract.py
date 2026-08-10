import uuid

import pytest
from credential_test_helpers import decrypted_credential_value, encrypted_credential_value
from error_contract_helpers import handled_app_error_payload
from fastapi import Request
from sqlalchemy import func, select

from app.joysafeter_api.api.v1.vaults import (
    archive_credential,
    archive_vault,
    create_credential,
    delete_credential,
    delete_vault,
    get_credential,
    get_vault,
    list_credentials,
    update_credential,
    update_vault,
)
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_vault import JoySafeterVault, JoySafeterVaultCredential
from app.joysafeter_domain.schemas.joysafeter_vault import (
    CreateCredentialRequest,
    OAuthConfigSchema,
    UpdateCredentialRequest,
    UpdateVaultRequest,
)
from app.joysafeter_domain.services.joysafeter_vault_service import VaultService
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.ids import CredentialId, VaultId
from app.joysafeter_shared.security.credential_cipher import CredentialCipher
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


async def _credential(db_session, *, vault_id: VaultId, name: str | None = None) -> JoySafeterVaultCredential:
    cred = JoySafeterVaultCredential(
        vault_id=vault_id,
        name=name or f"cred-{uuid.uuid4()}",
        credential_type="static_bearer",
        mcp_server_url=f"https://mcp-{uuid.uuid4()}.example.com",
        token_value=encrypted_credential_value("token"),
    )
    db_session.add(cred)
    await db_session.commit()
    await db_session.refresh(cred)
    return cred


async def _session_referencing_vault(db_session, vault_id: VaultId, vault_ref: str) -> JoySafeterSession:
    agent = JoySafeterAgent(name=f"vault-session-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.flush()
    session = JoySafeterSession(agent_id=agent.id, status="idle", vault_ids=[vault_ref])
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    return session


async def _assert_vault_intact(db_session, vault_id: VaultId) -> JoySafeterVault:
    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterVault).where(JoySafeterVault.id == vault_id))).scalar_one()
    assert row.deleted_at is None
    return row


async def _assert_credential_intact(db_session, cred_id: CredentialId) -> JoySafeterVaultCredential:
    db_session.expire_all()
    row = (
        await db_session.execute(select(JoySafeterVaultCredential).where(JoySafeterVaultCredential.id == cred_id))
    ).scalar_one()
    assert row.deleted_at is None
    return row


@pytest.mark.asyncio
async def test_get_vault_missing_vault_returns_structured_error(db_session):
    vault_id = VaultId.new()

    with pytest.raises(AppError) as exc_info:
        await get_vault(vault_id, db_session, _auth_ctx())

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
    cred_id = CredentialId.new()

    with pytest.raises(AppError) as exc_info:
        await get_credential(vault.id, cred_id, db_session, _auth_ctx())

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
            vault_id,
            db_session,
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
    await _session_referencing_vault(db_session, vault.id, str(vault.id))

    with pytest.raises(AppError) as exc_info:
        await delete_vault(_request("DELETE"), vault.id, db_session, _auth_ctx())

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
async def test_archive_vault_rejects_bare_uuid_active_session_reference(db_session):
    vault = JoySafeterVault(name=f"active-session-bare-vault-{uuid.uuid4()}", description="")
    db_session.add(vault)
    await db_session.commit()
    await db_session.refresh(vault)
    await _session_referencing_vault(db_session, vault.id, str(vault.id))

    with pytest.raises(AppError) as exc_info:
        await archive_vault(_request("POST"), vault.id, db_session, _auth_ctx())

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
            vault_id,
            db_session,
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
async def test_create_credential_normalizes_static_bearer_storage(db_session):
    vault = JoySafeterVault(name=f"vault-{uuid.uuid4()}", description="")
    db_session.add(vault)
    await db_session.commit()
    await db_session.refresh(vault)

    created = await create_credential(
        CreateCredentialRequest(
            name="Normalized",
            credential_type=" STATIC_BEARER ",
            mcp_server_url="https://normalized.example.com",
            token_value="  normalized-token  ",
            oauth_config=OAuthConfigSchema(
                client_id="client-id",
                client_secret="client-secret",
                refresh_token="refresh-token",
                token_endpoint="https://auth.example.com/token",
            ),
        ),
        _request(),
        vault.id,
        db_session,
        _auth_ctx(),
    )

    stored = (
        await db_session.execute(
            select(JoySafeterVaultCredential).where(JoySafeterVaultCredential.id == created.id)
        )
    ).scalar_one()
    assert stored.credential_type == "static_bearer"
    assert decrypted_credential_value(stored.token_value) == "normalized-token"
    assert stored.oauth_config is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name_payload", "expected_name"),
    [
        pytest.param({}, "https://mcp-name.example.com/api", id="omitted"),
        pytest.param({"name": None}, "https://mcp-name.example.com/api", id="null"),
        pytest.param({"name": "   "}, "https://mcp-name.example.com/api", id="blank"),
        pytest.param({"name": "  Production MCP  "}, "Production MCP", id="explicit"),
    ],
)
async def test_create_credential_api_normalizes_optional_name_and_persists_it(
    db_session,
    name_payload,
    expected_name,
):
    vault = JoySafeterVault(name=f"vault-{uuid.uuid4()}", description="")
    db_session.add(vault)
    await db_session.commit()
    await db_session.refresh(vault)

    request = CreateCredentialRequest.model_validate(
        {
            **name_payload,
            "credential_type": "static_bearer",
            "mcp_server_url": "  https://mcp-name.example.com/api  ",
            "token_value": "token",
        }
    )
    created = await create_credential(request, _request(), vault.id, db_session, _auth_ctx())

    stored = (
        await db_session.execute(
            select(JoySafeterVaultCredential).where(JoySafeterVaultCredential.id == created.id)
        )
    ).scalar_one()
    assert request.name == name_payload.get("name")
    assert created.name == expected_name
    assert stored.name == expected_name


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "mcp_server_url", "expected_name", "expected_url"),
    [
        pytest.param(
            None,
            "  https://service-name.example.com/mcp  ",
            "https://service-name.example.com/mcp",
            "https://service-name.example.com/mcp",
            id="missing",
        ),
        pytest.param(
            " \t ",
            "https://service-name.example.com/mcp",
            "https://service-name.example.com/mcp",
            "https://service-name.example.com/mcp",
            id="blank",
        ),
        pytest.param(
            "  Service MCP  ",
            "https://service-name.example.com/mcp",
            "Service MCP",
            "https://service-name.example.com/mcp",
            id="explicit",
        ),
        pytest.param(None, "   ", "MCP Credential", "", id="blank-url-fallback"),
    ],
)
async def test_create_credential_service_normalizes_optional_name(
    db_session,
    name,
    mcp_server_url,
    expected_name,
    expected_url,
):
    vault = JoySafeterVault(name=f"vault-{uuid.uuid4()}", description="")
    db_session.add(vault)
    await db_session.commit()
    await db_session.refresh(vault)

    created = await VaultService(db_session).create_credential(
        vault_id=vault.id,
        name=name,
        credential_type="static_bearer",
        mcp_server_url=mcp_server_url,
        token_value="token",
    )

    assert created is not None
    assert created.name == expected_name
    assert created.mcp_server_url == expected_url


@pytest.mark.asyncio
@pytest.mark.parametrize("credential_type", ["mcp_oauth", "oauth", "custom"])
async def test_create_credential_rejects_unsupported_type(db_session, credential_type):
    vault = JoySafeterVault(name=f"vault-{uuid.uuid4()}", description="")
    db_session.add(vault)
    await db_session.commit()
    await db_session.refresh(vault)

    with pytest.raises(AppError) as exc_info:
        await create_credential(
            CreateCredentialRequest(
                name="Unsupported",
                credential_type=credential_type,
                mcp_server_url="https://mcp.example.com",
                token_value="token",
            ),
            _request(),
            vault.id,
            db_session,
            _auth_ctx(),
        )

    payload = await handled_app_error_payload(exc_info.value, status_code=400)
    assert payload["code"] == "VAULT_CREDENTIAL_TYPE_NOT_SUPPORTED"
    assert payload["data"] == {"credential_type": credential_type, "supported": ["static_bearer"]}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("credential_type", "token_value", "expected_code"),
    [
        pytest.param("mcp_oauth", "token", "VAULT_CREDENTIAL_TYPE_NOT_SUPPORTED", id="unsupported-type"),
        pytest.param("static_bearer", "   ", "VAULT_CREDENTIAL_TOKEN_REQUIRED", id="blank-token"),
    ],
)
async def test_rejected_credential_creation_skips_audit_and_network_refresh(
    db_session,
    monkeypatch,
    credential_type,
    token_value,
    expected_code,
):
    vault = JoySafeterVault(name=f"vault-{uuid.uuid4()}", description="")
    db_session.add(vault)
    await db_session.commit()
    await db_session.refresh(vault)

    async def unexpected_audit(*args, **kwargs):
        raise AssertionError("rejected credential creation must not write an audit event")

    async def unexpected_refresh(*args, **kwargs):
        raise AssertionError("rejected credential creation must not refresh network policies")

    monkeypatch.setattr("app.joysafeter_api.api.v1.vaults.audit_joysafeter_event", unexpected_audit)
    monkeypatch.setattr(
        "app.joysafeter_api.api.v1.vaults.refresh_live_limited_sandbox_network_policies",
        unexpected_refresh,
    )

    with pytest.raises(AppError) as exc_info:
        await create_credential(
            CreateCredentialRequest(
                name=None,
                credential_type=credential_type,
                mcp_server_url="https://mcp.example.com",
                token_value=token_value,
            ),
            _request(),
            vault.id,
            db_session,
            _auth_ctx(),
        )

    payload = await handled_app_error_payload(exc_info.value, status_code=400)
    assert payload["code"] == expected_code


@pytest.mark.asyncio
async def test_create_credential_rejects_blank_static_bearer_token(db_session):
    vault = JoySafeterVault(name=f"vault-{uuid.uuid4()}", description="")
    db_session.add(vault)
    await db_session.commit()
    await db_session.refresh(vault)

    with pytest.raises(AppError) as exc_info:
        await create_credential(
            CreateCredentialRequest(
                name="Blank token",
                credential_type="static_bearer",
                mcp_server_url="https://mcp.example.com",
                token_value="   ",
            ),
            _request(),
            vault.id,
            db_session,
            _auth_ctx(),
        )

    payload = await handled_app_error_payload(exc_info.value, status_code=400)
    assert payload["code"] == "VAULT_CREDENTIAL_TOKEN_REQUIRED"
    assert payload["data"] == {"credential_type": "static_bearer"}
    count = (
        await db_session.execute(
            select(func.count())
            .select_from(JoySafeterVaultCredential)
            .where(JoySafeterVaultCredential.vault_id == vault.id)
        )
    ).scalar_one()
    assert count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("credential_type", ["mcp_oauth", "oauth"])
async def test_historical_oauth_credential_remains_listable_readable_updatable_archivable_and_deletable(
    db_session, credential_type
):
    vault = JoySafeterVault(name=f"vault-{uuid.uuid4()}", description="")
    db_session.add(vault)
    await db_session.commit()
    await db_session.refresh(vault)

    historical = JoySafeterVaultCredential(
        vault_id=vault.id,
        name="Historical OAuth",
        credential_type=credential_type,
        mcp_server_url=f"https://historical-{credential_type}.example.com",
        token_value=encrypted_credential_value("historical-token"),
        oauth_config=None,
    )
    db_session.add(historical)
    await db_session.commit()
    await db_session.refresh(historical)
    historical_id = historical.id

    listed = await list_credentials(
        vault.id,
        limit=20,
        after_id=None,
        include_archived=True,
        db=db_session,
        auth_ctx=_auth_ctx(),
    )
    assert listed["has_more"] is False
    assert listed["first_id"] == str(historical_id)
    assert listed["last_id"] == str(historical_id)
    assert listed["data"][0]["id"] == str(historical_id)
    assert listed["data"][0]["vault_id"] == str(vault.id)
    assert listed["data"][0]["name"] == "Historical OAuth"
    assert listed["data"][0]["credential_type"] == credential_type
    assert listed["data"][0]["mcp_server_url"] == f"https://historical-{credential_type}.example.com"
    assert listed["data"][0]["token_value"] == "********"
    assert listed["data"][0]["oauth_config"] is None
    assert listed["data"][0]["archived_at"] is None
    response = await get_credential(vault.id, historical_id, db_session, _auth_ctx())
    assert response.credential_type == credential_type
    assert response.model_dump()["token_value"] == "********"
    updated = await update_credential(
        UpdateCredentialRequest(name="Updated Historical OAuth"),
        _request(),
        vault.id,
        historical_id,
        db_session,
        _auth_ctx(),
    )
    assert updated.name == "Updated Historical OAuth"
    assert updated.credential_type == credential_type
    assert await archive_credential(_request(), vault.id, historical_id, db_session, _auth_ctx()) == {"status": "archived"}

    historical.archived_at = None
    await db_session.commit()

    assert await delete_credential(_request("DELETE"), vault.id, historical_id, db_session, _auth_ctx()) == {
        "deleted": True
    }
    db_session.expire_all()
    deleted = (
        await db_session.execute(
            select(JoySafeterVaultCredential).where(JoySafeterVaultCredential.id == historical_id)
        )
    ).scalar_one()
    assert deleted.deleted_at is not None


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
        token_value=encrypted_credential_value("old-token"),
        archived_at=utc_now(),
    )
    db_session.add(cred)
    await db_session.commit()
    cred_id = cred.id

    with pytest.raises(AppError) as exc_info:
        await update_credential(
            UpdateCredentialRequest(name="Changed MCP", token_value="new-token"),
            _request("POST"),
            vault.id,
            cred_id,
            db_session,
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
    assert decrypted_credential_value(row.token_value) == "old-token"


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
        token_value=encrypted_credential_value("token"),
    )
    db_session.add(cred)
    await db_session.commit()
    cred_id = cred.id

    with pytest.raises(AppError) as exc_info:
        await delete_credential(_request("DELETE"), vault.id, cred_id, db_session, _auth_ctx())

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
            token_value=encrypted_credential_value("active-token"),
        )
    )
    await db_session.commit()
    db_session.add(
        JoySafeterVaultCredential(
            vault_id=active_vault.id,
            name="Archived Credential MCP",
            credential_type="static_bearer",
            mcp_server_url="https://archived-credential.example.com",
            token_value=encrypted_credential_value("archived-credential-token"),
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
            token_value=encrypted_credential_value("archived-vault-token"),
        )
    )
    await db_session.commit()

    resolved = await VaultService(db_session).resolve_mcp_credentials(
        [active_vault.id, archived_vault.id],
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
    cipher = CredentialCipher(CredentialCipher.generate_key())
    monkeypatch.setattr("app.joysafeter_domain.services.joysafeter_vault_service._cipher", cipher)

    vault = JoySafeterVault(name=f"encrypted-vault-{uuid.uuid4()}", description="")
    db_session.add(vault)
    await db_session.commit()
    await db_session.refresh(vault)
    vault_id = vault.id

    svc = VaultService(db_session)
    cred = JoySafeterVaultCredential(
        vault_id=vault_id,
        name="Encrypted MCP",
        credential_type="mcp_oauth",
        mcp_server_url="https://encrypted-mcp.example.com",
        token_value=cipher.encrypt("access-token"),
        oauth_config={
            "client_id": "client-id",
            "client_secret": cipher.encrypt("client-secret"),
            "refresh_token": cipher.encrypt("refresh-token"),
            "token_endpoint": "https://auth.example.com/token",
            "expires_at": "2999-01-01T00:00:00+00:00",
        },
    )
    db_session.add(cred)
    await db_session.commit()
    await db_session.refresh(cred)
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
        [vault_id],
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
        await get_vault(vault.id, db_session, _project_auth_ctx("project-a"))

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
    assert decrypted_credential_value(row.token_value) == "token"
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
    assert decrypted_credential_value(row.token_value) == "token"
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
            token_value=encrypted_credential_value("project-b-token"),
        )
    )
    await db_session.commit()

    unresolved = await VaultService(db_session).resolve_mcp_credentials(
        [vault_b.id],
        [{"name": "project-b", "url": "https://project-b-mcp.example.com", "headers": {}}],
        project_id="project-a",
    )
    resolved = await VaultService(db_session).resolve_mcp_credentials(
        [vault_b.id],
        [{"name": "project-b", "url": "https://project-b-mcp.example.com", "headers": {}}],
        project_id="project-b",
    )
    empty_project = await VaultService(db_session).resolve_mcp_credentials(
        [vault_a.id],
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
