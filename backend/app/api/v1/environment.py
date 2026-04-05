"""
Environment variable management API (path: /api/v1/environment)

- /api/v1/environment/user                 Get current user's environment variables (keys only, values masked)
- /api/v1/environment/user (PUT)           Update current user's environment variables
- /api/v1/environment/workspaces/{id}      Get workspace environment variables (admin+ required, masked)
- /api/v1/environment/workspaces/{id} (PUT)Update workspace environment variables (admin+ required)
"""

from __future__ import annotations

import uuid
from typing import Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user, require_workspace_role
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.models.workspace import WorkspaceMemberRole
from app.services.environment_service import EnvironmentService

router = APIRouter(prefix="/v1/environment", tags=["Environment"])


class EnvPayload(BaseModel):
    variables: Dict[str, str] = Field(default_factory=dict)


@router.get("/user")
async def get_user_environment(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = EnvironmentService(db)
    # Note: EnvironmentService expects uuid.UUID but user.id and Environment.user_id are both strings.
    # Converting str to UUID for compatibility with service signature
    import uuid as uuid_lib

    user_id = uuid_lib.UUID(current_user.id) if isinstance(current_user.id, str) else current_user.id
    variables = await service.get_user_env(user_id)
    return {"success": True, "variables": service.mask_variables(variables)}


@router.put("/user")
async def update_user_environment(
    payload: EnvPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = EnvironmentService(db)
    # Note: EnvironmentService expects uuid.UUID but user.id and Environment.user_id are both strings.
    # Converting str to UUID for compatibility with service signature
    import uuid as uuid_lib

    user_id = uuid_lib.UUID(current_user.id) if isinstance(current_user.id, str) else current_user.id
    variables = await service.upsert_user_env(user_id, payload.variables)
    return {"success": True, "variables": service.mask_variables(variables)}


@router.get("/workspaces/{workspace_id}")
async def get_workspace_environment(
    workspace_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_workspace_role(WorkspaceMemberRole.admin),
):
    service = EnvironmentService(db)
    variables = await service.get_workspace_env(workspace_id)
    return {"success": True, "variables": service.mask_variables(variables)}


@router.put("/workspaces/{workspace_id}")
async def update_workspace_environment(
    workspace_id: uuid.UUID,
    payload: EnvPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_workspace_role(WorkspaceMemberRole.admin),
):
    service = EnvironmentService(db)
    variables = await service.upsert_workspace_env(workspace_id, payload.variables)
    return {"success": True, "variables": service.mask_variables(variables)}
