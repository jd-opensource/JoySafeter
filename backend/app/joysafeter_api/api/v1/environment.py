"""
Environment variable management API (path: /api/v1/environment)

- /api/v1/environment/user                 Get current user's environment variables (keys only, values masked)
- /api/v1/environment/user (PUT)           Update current user's environment variables
- /api/v1/environment/projects/{id}        Get project environment variables (admin+ required, masked)
- /api/v1/environment/projects/{id} (PUT)  Update project environment variables (admin+ required)
"""

from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_shared.common.dependencies import get_current_user
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, get_joysafeter_auth_context, require_joysafeter_admin
from app.joysafeter_shared.database import get_db
from app.joysafeter_domain.models.auth import AuthUser as User
from app.joysafeter_api.services import EnvironmentService

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


@router.get("/projects/{project_id}")
@router.get("/workspaces/{project_id}", include_in_schema=False)
async def get_project_environment(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_admin),
):
    """Get project environment variables."""
    service = EnvironmentService(db)
    variables = await service.get_project_env(auth_ctx.project_id)
    return {"success": True, "variables": service.mask_variables(variables)}


@router.put("/projects/{project_id}")
@router.put("/workspaces/{project_id}", include_in_schema=False)
async def update_project_environment(
    payload: EnvPayload,
    project_id: str,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_admin),
):
    """Update project environment variables."""
    service = EnvironmentService(db)
    variables = await service.upsert_project_env(auth_ctx.project_id, payload.variables)
    return {"success": True, "variables": service.mask_variables(variables)}
