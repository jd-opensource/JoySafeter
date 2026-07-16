import uuid

import pytest
from error_contract_helpers import handled_app_error_payload
from fastapi import Request
from sqlalchemy import func, select

from app.joysafeter_api.api.v1.vaults import (
    create_credential,
    delete_credential,
    get_credential,
    get_vault,
    update_credential,
    update_vault,
)
from app.joysafeter_api.services import VaultService
from app.joysafeter_domain.models.joysafeter_vault import JoySafeterVault, JoySafeterVaultCredential
from app.joysafeter_domain.schemas.joysafeter_vault import (
    CreateCredentialRequest,
    UpdateCredentialRequest,
    UpdateVaultRequest,
)
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.utils.datetime import utc_now


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.DEVELOPER,
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
            select(func.count()).select_from(JoySafeterVaultCredential).where(JoySafeterVaultCredential.vault_id == vault_id)
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
