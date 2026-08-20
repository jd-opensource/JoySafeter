"""Id-based ``/credential-groups`` REST routes (P0 refactor, Task 8).

Replaces the old name-based ``/vaults`` API. Backed by ``CredentialGroupService``.
Group members are kind=mcp credentials born into the group, so membership reads
are masked (``CredentialService.get_masked``) and never expose raw secret
material. Writes require ``require_joysafeter_write`` and emit an audit event
whose details carry only non-sensitive metadata (name / url / keys).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_credential import (
    JoySafeterCredential,
    JoySafeterCredentialGroup,
)
from app.joysafeter_domain.schemas.joysafeter_credential import (
    AddGroupCredentialRequest,
    CreateCredentialGroupRequest,
    CredentialGroupResponse,
    CredentialKind,
    CredentialResponse,
    UpdateCredentialGroupRequest,
)
from app.joysafeter_domain.services.joysafeter_credential_group_service import (
    CredentialGroupService,
)
from app.joysafeter_domain.services.joysafeter_credential_service import CredentialService
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    get_joysafeter_auth_context,
    require_joysafeter_write,
)
from app.joysafeter_shared.database import get_db
from app.joysafeter_shared.ids import CredentialGroupId, CredentialId

router = APIRouter(tags=["joysafeter-credential-groups"])


def _group_response(group: JoySafeterCredentialGroup) -> CredentialGroupResponse:
    return CredentialGroupResponse(
        id=group.id,
        name=group.name,
        description=group.description,
        metadata=group.metadata_,
        archived_at=group.archived_at,
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


def _member_response(cred: JoySafeterCredential, svc: CredentialService) -> CredentialResponse:
    return CredentialResponse(
        id=cred.id,
        kind=CredentialKind(cred.kind),
        name=cred.name,
        data=svc.get_masked(cred),
        provider=cred.provider,
        protocol=cred.protocol,
        is_default=cred.is_default,
        mcp_server_url=cred.mcp_server_url,
        group_id=cred.group_id,
        archived_at=cred.archived_at,
        created_at=cred.created_at,
        updated_at=cred.updated_at,
    )


# --- group CRUD ------------------------------------------------------------------


@router.post("", status_code=201)
async def create_credential_group(
    req: CreateCredentialGroupRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> CredentialGroupResponse:
    svc = CredentialGroupService(db, compatibility_mode=False)
    group = await svc.create_with_initial_members(req, project_id=auth_ctx.project_id)
    return _group_response(group)


@router.get("")
async def list_credential_groups(
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[CredentialGroupId] = Query(None),
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
):
    svc = CredentialGroupService(db)
    groups, has_more = await svc.list(
        project_id=auth_ctx.project_id,
        limit=limit,
        after_id=after_id,
        include_archived=include_archived,
    )
    items = [_group_response(g) for g in groups]
    return {
        "data": [item.model_dump(mode="json") for item in items],
        "has_more": has_more,
        "first_id": str(groups[0].id) if groups else None,
        "last_id": str(groups[-1].id) if groups else None,
    }


@router.get("/{group_id}")
async def get_credential_group(
    group_id: CredentialGroupId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> CredentialGroupResponse:
    svc = CredentialGroupService(db)
    group = await svc.get_or_raise(group_id, project_id=auth_ctx.project_id)
    return _group_response(group)


@router.patch("/{group_id}")
async def update_credential_group(
    req: UpdateCredentialGroupRequest,
    group_id: CredentialGroupId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> CredentialGroupResponse:
    svc = CredentialGroupService(db, compatibility_mode=False)
    group = await svc.update(group_id, req, project_id=auth_ctx.project_id)
    return _group_response(group)


@router.delete("/{group_id}", status_code=204)
async def delete_credential_group(
    group_id: CredentialGroupId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> None:
    svc = CredentialGroupService(db, compatibility_mode=False)
    # soft_delete raises CREDENTIAL_IN_USE (409) when bound to an active session.
    await svc.soft_delete(group_id, project_id=auth_ctx.project_id)


@router.post("/{group_id}/archive")
async def archive_credential_group(
    group_id: CredentialGroupId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> CredentialGroupResponse:
    svc = CredentialGroupService(db, compatibility_mode=False)
    # archive raises CREDENTIAL_IN_USE (409) when bound to an active session.
    group = await svc.archive(group_id, project_id=auth_ctx.project_id)
    return _group_response(group)


@router.post("/{group_id}/restore")
async def restore_credential_group(
    group_id: CredentialGroupId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> CredentialGroupResponse:
    group = await CredentialGroupService(db, compatibility_mode=False).restore(
        group_id,
        project_id=auth_ctx.project_id,
    )
    return _group_response(group)


# --- membership (mcp credentials born into the group) ----------------------------


@router.get("/{group_id}/members")
async def list_credential_group_members(
    group_id: CredentialGroupId,
    include_archived: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
):
    svc = CredentialGroupService(db)
    # Confirm the group exists / is visible in this project before listing.
    await svc.get_or_raise(group_id, project_id=auth_ctx.project_id)
    members = await svc.list_members(
        group_id,
        project_id=auth_ctx.project_id,
        include_archived=include_archived,
    )
    cred_svc = CredentialService(db)
    items = [_member_response(m, cred_svc) for m in members]
    return {"data": [item.model_dump(mode="json") for item in items]}


@router.post("/{group_id}/members", status_code=201)
async def add_credential_group_member(
    req: AddGroupCredentialRequest,
    group_id: CredentialGroupId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> CredentialResponse:
    svc = CredentialGroupService(db, compatibility_mode=False)
    cred = await svc.add_credential(group_id, req, project_id=auth_ctx.project_id)
    return _member_response(cred, CredentialService(db))


@router.post("/{group_id}/members/{credential_id}/archive")
async def archive_credential_group_member(
    group_id: CredentialGroupId,
    credential_id: CredentialId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> CredentialResponse:
    svc = CredentialGroupService(db, compatibility_mode=False)
    cred = await svc.archive_credential(
        group_id,
        credential_id,
        project_id=auth_ctx.project_id,
    )
    return _member_response(cred, CredentialService(db))


@router.delete("/{group_id}/members/{credential_id}", status_code=204)
async def remove_credential_group_member(
    group_id: CredentialGroupId,
    credential_id: CredentialId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> None:
    svc = CredentialGroupService(db, compatibility_mode=False)
    await svc.remove_credential(group_id, credential_id, project_id=auth_ctx.project_id)
