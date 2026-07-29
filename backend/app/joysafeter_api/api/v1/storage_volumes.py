from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.schemas.joysafeter_storage_mount import (
    CreateStorageVolumeRequest,
    StorageCatalogItem,
    StorageMountAuditResponse,
    StorageOrganizationGrantInput,
    StorageOrganizationGrantResponse,
    StorageProjectGrantInput,
    StorageProjectGrantResponse,
    StorageVolumeResponse,
    UpdateStorageVolumeRequest,
)
from app.joysafeter_domain.services.joysafeter_storage_mount_service import StorageMountService, volume_to_response
from app.joysafeter_shared.common.app_errors import NotFoundError
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    get_joysafeter_auth_context,
    require_joysafeter_platform_admin,
    require_joysafeter_user_admin,
    require_joysafeter_write,
)
from app.joysafeter_shared.database import get_db

router = APIRouter(tags=["joysafeter-storage-volumes"])


@router.get("/catalog")
async def list_storage_catalog(
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> dict[str, list[StorageCatalogItem]]:
    items = await StorageMountService(db).catalog_for_project(auth_ctx.project_id)
    return {"data": [StorageCatalogItem(**item) for item in items]}


@router.get("")
async def list_storage_volumes(
    include_disabled: bool = Query(False),
    scope: str = Query("auto"),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_user_admin),
) -> dict[str, list[StorageVolumeResponse]]:
    svc = StorageMountService(db)
    org_scope = scope.strip().lower() in {"org", "organization"}
    volumes = (
        await svc.list_volumes(include_disabled=include_disabled)
        if auth_ctx.is_super_user and not org_scope
        else await svc.list_organization_volumes(auth_ctx.org_id, include_disabled=include_disabled)
    )
    data: list[StorageVolumeResponse] = []
    for volume in volumes:
        org_grants = await svc.list_organization_grants(volume.id) if auth_ctx.is_super_user else []
        grants = await svc.list_grants(volume.id) if auth_ctx.is_super_user else await svc.list_project_grants_for_org(volume.id, auth_ctx.org_id)
        data.append(volume_to_response(volume, grants, org_grants, include_runtime_specs=auth_ctx.is_super_user))
    return {"data": data}


@router.post("", status_code=201)
async def create_storage_volume(
    req: CreateStorageVolumeRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_platform_admin),
) -> StorageVolumeResponse:
    svc = StorageMountService(db)
    volume = await svc.create_volume(req, actor_user_id=auth_ctx.user_id)
    grants = await svc.list_grants(volume.id)
    org_grants = await svc.list_organization_grants(volume.id)
    return volume_to_response(volume, grants, org_grants)


@router.get("/audit/logs")
async def list_storage_mount_audit(
    volume_id: Optional[uuid.UUID] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_user_admin),
) -> dict[str, list[StorageMountAuditResponse]]:
    svc = StorageMountService(db)
    if auth_ctx.is_super_user:
        # Platform admin: see all audit logs (optionally filtered by volume).
        rows = await svc.list_audit(volume_id=volume_id, limit=limit)
    else:
        # Org admin: see audit logs scoped to their organization's projects.
        if volume_id is not None:
            await svc.ensure_project_volume_access(volume_id, auth_ctx.project_id)
        rows = await svc.list_audit(
            org_id=auth_ctx.org_id,
            volume_id=volume_id,
            limit=limit,
        )
    return {"data": [StorageMountAuditResponse.model_validate(row) for row in rows]}


@router.get("/{volume_id}")
async def get_storage_volume(
    volume_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_user_admin),
) -> StorageVolumeResponse:
    svc = StorageMountService(db)
    volume = await svc.get_volume(volume_id) if auth_ctx.is_super_user else await svc.get_organization_volume(volume_id, auth_ctx.org_id)
    if not volume:
        raise NotFoundError(code="STORAGE_VOLUME_NOT_FOUND", message="Storage volume not found")
    org_grants = await svc.list_organization_grants(volume.id) if auth_ctx.is_super_user else []
    grants = await svc.list_grants(volume.id) if auth_ctx.is_super_user else await svc.list_project_grants_for_org(volume.id, auth_ctx.org_id)
    return volume_to_response(volume, grants, org_grants, include_runtime_specs=auth_ctx.is_super_user)


@router.post("/{volume_id}")
async def update_storage_volume(
    req: UpdateStorageVolumeRequest,
    volume_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_platform_admin),
) -> StorageVolumeResponse:
    svc = StorageMountService(db)
    volume = await svc.update_volume(volume_id, req, actor_user_id=auth_ctx.user_id)
    grants = await svc.list_grants(volume.id)
    org_grants = await svc.list_organization_grants(volume.id)
    return volume_to_response(volume, grants, org_grants)


@router.delete("/{volume_id}")
async def delete_storage_volume(
    volume_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_platform_admin),
) -> dict[str, bool]:
    deleted = await StorageMountService(db).delete_volume(volume_id, actor_user_id=auth_ctx.user_id)
    if not deleted:
        raise NotFoundError(code="STORAGE_VOLUME_NOT_FOUND", message="Storage volume not found")
    return {"ok": True}


@router.post("/{volume_id}/grants", status_code=201)
async def upsert_storage_volume_grant(
    req: StorageProjectGrantInput,
    volume_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_user_admin),
) -> StorageProjectGrantResponse:
    return await StorageMountService(db).replace_grant(
        volume_id,
        req,
        actor_user_id=auth_ctx.user_id,
        org_id_scope=None if auth_ctx.is_super_user else auth_ctx.org_id,
    )


@router.delete("/{volume_id}/grants/{project_id}")
async def delete_storage_volume_grant(
    volume_id: uuid.UUID,
    project_id: str,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_user_admin),
) -> dict[str, bool]:
    deleted = await StorageMountService(db).delete_grant(
        volume_id,
        project_id,
        actor_user_id=auth_ctx.user_id,
        org_id_scope=None if auth_ctx.is_super_user else auth_ctx.org_id,
    )
    if not deleted:
        raise NotFoundError(code="STORAGE_GRANT_NOT_FOUND", message="Storage grant not found")
    return {"ok": True}


@router.post("/{volume_id}/organization-grants", status_code=201)
async def upsert_storage_volume_organization_grant(
    req: StorageOrganizationGrantInput,
    volume_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_platform_admin),
) -> StorageOrganizationGrantResponse:
    return await StorageMountService(db).replace_organization_grant(volume_id, req, actor_user_id=auth_ctx.user_id)


@router.delete("/{volume_id}/organization-grants/{org_id}")
async def delete_storage_volume_organization_grant(
    volume_id: uuid.UUID,
    org_id: str,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_platform_admin),
) -> dict[str, bool]:
    deleted = await StorageMountService(db).delete_organization_grant(volume_id, org_id, actor_user_id=auth_ctx.user_id)
    if not deleted:
        raise NotFoundError(code="STORAGE_ORGANIZATION_GRANT_NOT_FOUND", message="Storage organization grant not found")
    return {"ok": True}
