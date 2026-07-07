import uuid

import pytest
from error_contract_helpers import handled_app_error_payload

from app.joysafeter_api.api.v1.vaults import get_credential, get_vault
from app.joysafeter_domain.models.joysafeter_vault import JoySafeterVault
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.DEVELOPER,
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
