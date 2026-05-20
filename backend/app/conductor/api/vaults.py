import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.conductor.schemas.vault import (
    CreateCredentialRequest,
    CreateVaultRequest,
    UpdateCredentialRequest,
    UpdateVaultRequest,
    VaultCredentialResponse,
    VaultResponse,
)
from app.conductor.schemas.common import PaginatedResponse
from app.conductor.services.vault_service import VaultService

router = APIRouter(tags=["conductor-vaults"])


@router.post("", status_code=201)
async def create_vault(
    req: CreateVaultRequest, db: AsyncSession = Depends(get_db)
) -> VaultResponse:
    svc = VaultService(db)
    vault = await svc.create_vault(req.name, req.description, req.metadata)
    return VaultResponse.model_validate(vault)


@router.get("")
async def list_vaults(
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[VaultResponse]:
    svc = VaultService(db)
    vaults, has_more = await svc.list_vaults(limit, after_id)
    data = [VaultResponse.model_validate(v) for v in vaults]
    return PaginatedResponse(
        data=data,
        has_more=has_more,
        first_id=str(data[0].id) if data else None,
        last_id=str(data[-1].id) if data else None,
    )


@router.get("/{vault_id}")
async def get_vault(
    vault_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> VaultResponse:
    svc = VaultService(db)
    vault = await svc.get_vault(vault_id)
    if not vault:
        raise HTTPException(404, "Vault not found")
    return VaultResponse.model_validate(vault)


@router.post("/{vault_id}")
async def update_vault(
    vault_id: uuid.UUID,
    req: UpdateVaultRequest,
    db: AsyncSession = Depends(get_db),
) -> VaultResponse:
    svc = VaultService(db)
    vault = await svc.update_vault(vault_id, req.name, req.description, req.metadata)
    if not vault:
        raise HTTPException(404, "Vault not found")
    return VaultResponse.model_validate(vault)


@router.delete("/{vault_id}", status_code=204)
async def delete_vault(
    vault_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> None:
    svc = VaultService(db)
    ok = await svc.delete_vault(vault_id)
    if not ok:
        raise HTTPException(404, "Vault not found")


@router.post("/{vault_id}/archive")
async def archive_vault(
    vault_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict:
    svc = VaultService(db)
    ok = await svc.archive_vault(vault_id)
    if not ok:
        raise HTTPException(404, "Vault not found")
    return {"status": "archived"}


# --- Credentials ---

@router.post("/{vault_id}/credentials", status_code=201)
async def create_credential(
    vault_id: uuid.UUID,
    req: CreateCredentialRequest,
    db: AsyncSession = Depends(get_db),
) -> VaultCredentialResponse:
    svc = VaultService(db)
    vault = await svc.get_vault(vault_id)
    if not vault:
        raise HTTPException(404, "Vault not found")
    cred = await svc.create_credential(
        vault_id=vault_id,
        name=req.name,
        credential_type=req.credential_type,
        mcp_server_url=req.mcp_server_url,
        token_value=req.token_value,
        oauth_config=req.oauth_config.model_dump() if req.oauth_config else None,
    )
    return VaultCredentialResponse.model_validate(cred)


@router.get("/{vault_id}/credentials")
async def list_credentials(
    vault_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[VaultCredentialResponse]:
    svc = VaultService(db)
    creds, has_more = await svc.list_credentials(vault_id, limit, after_id)
    data = [VaultCredentialResponse.model_validate(c) for c in creds]
    return PaginatedResponse(
        data=data,
        has_more=has_more,
        first_id=str(data[0].id) if data else None,
        last_id=str(data[-1].id) if data else None,
    )


@router.get("/{vault_id}/credentials/{cred_id}")
async def get_credential(
    vault_id: uuid.UUID,
    cred_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> VaultCredentialResponse:
    svc = VaultService(db)
    cred = await svc.get_credential(cred_id)
    if not cred or cred.vault_id != vault_id:
        raise HTTPException(404, "Credential not found")
    return VaultCredentialResponse.model_validate(cred)


@router.post("/{vault_id}/credentials/{cred_id}")
async def update_credential(
    vault_id: uuid.UUID,
    cred_id: uuid.UUID,
    req: UpdateCredentialRequest,
    db: AsyncSession = Depends(get_db),
) -> VaultCredentialResponse:
    svc = VaultService(db)
    cred = await svc.get_credential(cred_id)
    if not cred or cred.vault_id != vault_id:
        raise HTTPException(404, "Credential not found")
    updated = await svc.update_credential(
        cred_id,
        name=req.name,
        token_value=req.token_value,
        oauth_config=req.oauth_config.model_dump() if req.oauth_config else None,
    )
    if not updated:
        raise HTTPException(404, "Credential not found")
    return VaultCredentialResponse.model_validate(updated)


@router.delete("/{vault_id}/credentials/{cred_id}", status_code=204)
async def delete_credential(
    vault_id: uuid.UUID,
    cred_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    svc = VaultService(db)
    ok = await svc.delete_credential(cred_id)
    if not ok:
        raise HTTPException(404, "Credential not found")
