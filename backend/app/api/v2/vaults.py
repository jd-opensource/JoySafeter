import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.api.v2.id_helpers import parse_vault_id, parse_cred_id
from app.schemas.vault import (
    CreateCredentialRequest,
    CreateVaultRequest,
    UpdateCredentialRequest,
    UpdateVaultRequest,
    VaultCredentialResponse,
    VaultResponse,
)
from app.services.vault_service import VaultService

router = APIRouter(tags=["conductor-vaults"])


def _vault_to_response(vault) -> VaultResponse:
    return VaultResponse(
        id=vault.id,
        name=vault.name,
        description=vault.description,
        metadata=vault.metadata_,
        created_at=vault.created_at,
        updated_at=vault.updated_at,
        archived_at=vault.archived_at,
    )


@router.post("", status_code=201)
async def create_vault(
    req: CreateVaultRequest, db: AsyncSession = Depends(get_db)
) -> VaultResponse:
    svc = VaultService(db)
    vault = await svc.create_vault(req.name, req.description, req.metadata)
    return _vault_to_response(vault)


@router.get("")
async def list_vaults(
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[VaultResponse]:
    svc = VaultService(db)
    vaults, has_more = await svc.list_vaults(limit, after_id)
    return [_vault_to_response(v) for v in vaults]


@router.get("/{vault_id}")
async def get_vault(
    db: AsyncSession = Depends(get_db),
    vault_id: uuid.UUID = Depends(parse_vault_id),
) -> VaultResponse:
    svc = VaultService(db)
    vault = await svc.get_vault(vault_id)
    if not vault:
        raise HTTPException(404, "Vault not found")
    return _vault_to_response(vault)


@router.post("/{vault_id}")
async def update_vault(
    req: UpdateVaultRequest,
    db: AsyncSession = Depends(get_db),
    vault_id: uuid.UUID = Depends(parse_vault_id),
) -> VaultResponse:
    svc = VaultService(db)
    vault = await svc.update_vault(vault_id, description=req.description, metadata=req.metadata)
    if not vault:
        raise HTTPException(404, "Vault not found")
    return _vault_to_response(vault)


@router.delete("/{vault_id}")
async def delete_vault(
    db: AsyncSession = Depends(get_db),
    vault_id: uuid.UUID = Depends(parse_vault_id),
) -> dict:
    svc = VaultService(db)
    ok = await svc.delete_vault(vault_id)
    if not ok:
        raise HTTPException(404, "Vault not found")
    return {"deleted": True}


@router.post("/{vault_id}/archive")
async def archive_vault(
    db: AsyncSession = Depends(get_db),
    vault_id: uuid.UUID = Depends(parse_vault_id),
) -> dict:
    svc = VaultService(db)
    ok = await svc.archive_vault(vault_id)
    if not ok:
        raise HTTPException(404, "Vault not found")
    return {"status": "archived"}


# --- Credentials ---

@router.post("/{vault_id}/credentials", status_code=201)
async def create_credential(
    req: CreateCredentialRequest,
    db: AsyncSession = Depends(get_db),
    vault_id: uuid.UUID = Depends(parse_vault_id),
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
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    vault_id: uuid.UUID = Depends(parse_vault_id),
) -> list[VaultCredentialResponse]:
    svc = VaultService(db)
    creds, has_more = await svc.list_credentials(vault_id, limit, after_id)
    return [VaultCredentialResponse.model_validate(c) for c in creds]


@router.get("/{vault_id}/credentials/{cred_id}")
async def get_credential(
    db: AsyncSession = Depends(get_db),
    vault_id: uuid.UUID = Depends(parse_vault_id),
    cred_id: uuid.UUID = Depends(parse_cred_id),
) -> VaultCredentialResponse:
    svc = VaultService(db)
    cred = await svc.get_credential(cred_id)
    if not cred or cred.vault_id != vault_id:
        raise HTTPException(404, "Credential not found")
    return VaultCredentialResponse.model_validate(cred)


@router.post("/{vault_id}/credentials/{cred_id}")
async def update_credential(
    req: UpdateCredentialRequest,
    db: AsyncSession = Depends(get_db),
    vault_id: uuid.UUID = Depends(parse_vault_id),
    cred_id: uuid.UUID = Depends(parse_cred_id),
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


@router.delete("/{vault_id}/credentials/{cred_id}")
async def delete_credential(
    db: AsyncSession = Depends(get_db),
    vault_id: uuid.UUID = Depends(parse_vault_id),
    cred_id: uuid.UUID = Depends(parse_cred_id),
) -> dict:
    svc = VaultService(db)
    ok = await svc.delete_credential(cred_id)
    if not ok:
        raise HTTPException(404, "Credential not found")
    return {"deleted": True}
