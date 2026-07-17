import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_api.api.v1.audit import audit_joysafeter_event
from app.joysafeter_api.api.v1.id_helpers import parse_cred_id, parse_vault_id
from app.joysafeter_api.services import VaultService
from app.joysafeter_domain.schemas.joysafeter_vault import (
    CreateCredentialRequest,
    CreateVaultRequest,
    UpdateCredentialRequest,
    UpdateVaultRequest,
    VaultCredentialResponse,
    VaultResponse,
)
from app.joysafeter_shared.common.app_errors import AppError, NotFoundError, ResourceConflictError
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    get_joysafeter_auth_context,
    require_joysafeter_write,
)
from app.joysafeter_shared.database import get_db

router = APIRouter(tags=["joysafeter-vaults"])


def _vault_not_found_error(vault_id: uuid.UUID) -> AppError:
    return NotFoundError(
        code="VAULT_NOT_FOUND",
        message="Vault not found",
        data={"vault_id": str(vault_id)},
        user_action="refresh",
    )


def _vault_credential_not_found_error(vault_id: uuid.UUID, cred_id: uuid.UUID) -> AppError:
    return NotFoundError(
        code="VAULT_CREDENTIAL_NOT_FOUND",
        message="Credential not found",
        data={"vault_id": str(vault_id), "credential_id": str(cred_id)},
        user_action="refresh",
    )


def _vault_archived_error(vault_id: uuid.UUID) -> AppError:
    return ResourceConflictError(
        code="VAULT_ARCHIVED",
        message="Vault is archived",
        data={"vault_id": str(vault_id)},
        retryable=False,
        user_action="refresh",
    )


def _vault_credential_archived_error(vault_id: uuid.UUID, cred_id: uuid.UUID) -> AppError:
    return ResourceConflictError(
        code="VAULT_CREDENTIAL_ARCHIVED",
        message="Credential is archived",
        data={"vault_id": str(vault_id), "credential_id": str(cred_id)},
        retryable=False,
        user_action="refresh",
    )


async def _get_vault_or_404(svc: VaultService, vault_id: uuid.UUID, project_id: str):
    vault = await svc.get_vault(vault_id, project_id=project_id)
    if not vault:
        raise _vault_not_found_error(vault_id)
    return vault


def _ensure_vault_mutable(vault) -> None:
    if vault.archived_at is not None:
        raise _vault_archived_error(vault.id)


async def _get_mutable_vault_or_404(svc: VaultService, vault_id: uuid.UUID, project_id: str):
    vault = await _get_vault_or_404(svc, vault_id, project_id)
    _ensure_vault_mutable(vault)
    return vault


def _ensure_credential_mutable(vault_id: uuid.UUID, cred) -> None:
    if cred.archived_at is not None:
        raise _vault_credential_archived_error(vault_id, cred.id)


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
    req: CreateVaultRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> VaultResponse:
    svc = VaultService(db)
    vault = await svc.create_vault(req.name, req.description, req.metadata, project_id=auth_ctx.project_id)
    await audit_joysafeter_event(
        db,
        request,
        auth_ctx,
        event_type="vault.created",
        target_type="vault",
        target_id=str(vault.id),
        details={"name": vault.name},
    )
    return _vault_to_response(vault)


@router.get("")
async def list_vaults(
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[uuid.UUID] = Query(None),
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
):
    svc = VaultService(db)
    vaults, has_more = await svc.list_vaults(
        limit, after_id, project_id=auth_ctx.project_id, include_archived=include_archived
    )
    items = [_vault_to_response(v) for v in vaults]
    return {
        "data": [item.model_dump(mode="json") for item in items],
        "has_more": has_more,
        "first_id": str(items[0].id) if items else None,
        "last_id": str(items[-1].id) if items else None,
    }


@router.get("/{vault_id}")
async def get_vault(
    db: AsyncSession = Depends(get_db),
    vault_id: uuid.UUID = Depends(parse_vault_id),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> VaultResponse:
    svc = VaultService(db)
    vault = await _get_vault_or_404(svc, vault_id, auth_ctx.project_id)
    return _vault_to_response(vault)


@router.post("/{vault_id}")
async def update_vault(
    req: UpdateVaultRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    vault_id: uuid.UUID = Depends(parse_vault_id),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> VaultResponse:
    svc = VaultService(db)
    await _get_mutable_vault_or_404(svc, vault_id, auth_ctx.project_id)
    vault = await svc.update_vault(
        vault_id,
        description=req.description,
        metadata=req.metadata,
        project_id=auth_ctx.project_id,
    )
    if not vault:
        raise _vault_not_found_error(vault_id)
    await audit_joysafeter_event(
        db,
        request,
        auth_ctx,
        event_type="vault.updated",
        target_type="vault",
        target_id=str(vault.id),
        details={"name": vault.name},
    )
    return _vault_to_response(vault)


@router.delete("/{vault_id}")
async def delete_vault(
    request: Request,
    db: AsyncSession = Depends(get_db),
    vault_id: uuid.UUID = Depends(parse_vault_id),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> dict:
    svc = VaultService(db)
    await _get_mutable_vault_or_404(svc, vault_id, auth_ctx.project_id)
    ok = await svc.delete_vault(vault_id, project_id=auth_ctx.project_id)
    if not ok:
        raise _vault_not_found_error(vault_id)
    await audit_joysafeter_event(
        db,
        request,
        auth_ctx,
        event_type="vault.deleted",
        target_type="vault",
        target_id=str(vault_id),
    )
    return {"deleted": True}


@router.post("/{vault_id}/archive")
async def archive_vault(
    request: Request,
    db: AsyncSession = Depends(get_db),
    vault_id: uuid.UUID = Depends(parse_vault_id),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> dict:
    svc = VaultService(db)
    await _get_vault_or_404(svc, vault_id, auth_ctx.project_id)
    ok = await svc.archive_vault(vault_id, project_id=auth_ctx.project_id)
    if not ok:
        raise _vault_not_found_error(vault_id)
    await audit_joysafeter_event(
        db,
        request,
        auth_ctx,
        event_type="vault.archived",
        target_type="vault",
        target_id=str(vault_id),
    )
    return {"status": "archived"}


# --- Credentials ---


@router.post("/{vault_id}/credentials", status_code=201)
async def create_credential(
    req: CreateCredentialRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    vault_id: uuid.UUID = Depends(parse_vault_id),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> VaultCredentialResponse:
    svc = VaultService(db)
    await _get_mutable_vault_or_404(svc, vault_id, auth_ctx.project_id)
    cred = await svc.create_credential(
        vault_id=vault_id,
        name=req.name,
        credential_type=req.credential_type,
        mcp_server_url=req.mcp_server_url,
        token_value=req.token_value,
        oauth_config=req.oauth_config.model_dump(mode="json") if req.oauth_config else None,
        project_id=auth_ctx.project_id,
    )
    if not cred:
        raise _vault_not_found_error(vault_id)
    await audit_joysafeter_event(
        db,
        request,
        auth_ctx,
        event_type="vault_credential.created",
        target_type="vault_credential",
        target_id=str(cred.id),
        details={"vault_id": str(vault_id), "name": cred.name, "credential_type": cred.credential_type},
    )
    return VaultCredentialResponse.model_validate(cred)


@router.get("/{vault_id}/credentials")
async def list_credentials(
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[uuid.UUID] = Query(None),
    include_archived: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    vault_id: uuid.UUID = Depends(parse_vault_id),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
):
    svc = VaultService(db)
    await _get_vault_or_404(svc, vault_id, auth_ctx.project_id)
    creds, has_more = await svc.list_credentials(
        vault_id,
        limit,
        after_id,
        include_archived=include_archived,
        project_id=auth_ctx.project_id,
    )
    items = [VaultCredentialResponse.model_validate(c) for c in creds]
    return {
        "data": [item.model_dump(mode="json") for item in items],
        "has_more": has_more,
        "first_id": str(items[0].id) if items else None,
        "last_id": str(items[-1].id) if items else None,
    }


@router.get("/{vault_id}/credentials/{cred_id}")
async def get_credential(
    db: AsyncSession = Depends(get_db),
    vault_id: uuid.UUID = Depends(parse_vault_id),
    cred_id: uuid.UUID = Depends(parse_cred_id),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> VaultCredentialResponse:
    svc = VaultService(db)
    await _get_vault_or_404(svc, vault_id, auth_ctx.project_id)
    cred = await svc.get_credential(cred_id, vault_id=vault_id, project_id=auth_ctx.project_id)
    if not cred:
        raise _vault_credential_not_found_error(vault_id, cred_id)
    return VaultCredentialResponse.model_validate(cred)


@router.post("/{vault_id}/credentials/{cred_id}")
async def update_credential(
    req: UpdateCredentialRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    vault_id: uuid.UUID = Depends(parse_vault_id),
    cred_id: uuid.UUID = Depends(parse_cred_id),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> VaultCredentialResponse:
    svc = VaultService(db)
    await _get_mutable_vault_or_404(svc, vault_id, auth_ctx.project_id)
    cred = await svc.get_credential(cred_id, vault_id=vault_id, project_id=auth_ctx.project_id)
    if not cred:
        raise _vault_credential_not_found_error(vault_id, cred_id)
    _ensure_credential_mutable(vault_id, cred)
    updated = await svc.update_credential(
        cred_id,
        name=req.name,
        token_value=req.token_value,
        oauth_config=req.oauth_config.model_dump(mode="json") if req.oauth_config else None,
        vault_id=vault_id,
        project_id=auth_ctx.project_id,
    )
    if not updated:
        raise _vault_credential_not_found_error(vault_id, cred_id)
    await audit_joysafeter_event(
        db,
        request,
        auth_ctx,
        event_type="vault_credential.updated",
        target_type="vault_credential",
        target_id=str(updated.id),
        details={"vault_id": str(vault_id), "name": updated.name, "credential_type": updated.credential_type},
    )
    return VaultCredentialResponse.model_validate(updated)


@router.post("/{vault_id}/credentials/{cred_id}/archive")
async def archive_credential(
    request: Request,
    db: AsyncSession = Depends(get_db),
    vault_id: uuid.UUID = Depends(parse_vault_id),
    cred_id: uuid.UUID = Depends(parse_cred_id),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> dict:
    svc = VaultService(db)
    await _get_mutable_vault_or_404(svc, vault_id, auth_ctx.project_id)
    cred = await svc.get_credential(cred_id, vault_id=vault_id, project_id=auth_ctx.project_id)
    if not cred:
        raise _vault_credential_not_found_error(vault_id, cred_id)
    _ensure_credential_mutable(vault_id, cred)
    ok = await svc.archive_credential(cred_id, vault_id=vault_id, project_id=auth_ctx.project_id)
    if not ok:
        raise _vault_credential_not_found_error(vault_id, cred_id)
    await audit_joysafeter_event(
        db,
        request,
        auth_ctx,
        event_type="vault_credential.archived",
        target_type="vault_credential",
        target_id=str(cred_id),
        details={"vault_id": str(vault_id), "name": cred.name, "credential_type": cred.credential_type},
    )
    return {"status": "archived"}


@router.delete("/{vault_id}/credentials/{cred_id}")
async def delete_credential(
    request: Request,
    db: AsyncSession = Depends(get_db),
    vault_id: uuid.UUID = Depends(parse_vault_id),
    cred_id: uuid.UUID = Depends(parse_cred_id),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> dict:
    svc = VaultService(db)
    await _get_mutable_vault_or_404(svc, vault_id, auth_ctx.project_id)
    cred = await svc.get_credential(cred_id, vault_id=vault_id, project_id=auth_ctx.project_id)
    if not cred:
        raise _vault_credential_not_found_error(vault_id, cred_id)
    _ensure_credential_mutable(vault_id, cred)
    ok = await svc.delete_credential(cred_id, vault_id=vault_id, project_id=auth_ctx.project_id)
    if not ok:
        raise _vault_credential_not_found_error(vault_id, cred_id)
    await audit_joysafeter_event(
        db,
        request,
        auth_ctx,
        event_type="vault_credential.deleted",
        target_type="vault_credential",
        target_id=str(cred_id),
        details={"vault_id": str(vault_id), "name": cred.name, "credential_type": cred.credential_type},
    )
    return {"deleted": True}
