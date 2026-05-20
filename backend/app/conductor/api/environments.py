import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.conductor.schemas.environment import (
    CreateEnvironmentRequest,
    EnvironmentResponse,
    UpdateEnvironmentRequest,
)
from app.conductor.schemas.common import PaginatedResponse
from app.conductor.services.environment_service import EnvironmentService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["conductor-environments"])


async def _try_build_image(env) -> None:
    """Attempt to build a custom image for the environment if packages are configured."""
    from app.conductor.lifespan import get_image_builder

    builder = get_image_builder()
    if not builder:
        return

    config = env.config or {}
    packages = config.get("packages", {}) if isinstance(config, dict) else {}
    if not packages:
        return

    try:
        version = getattr(env, "image_version", 0) or 0
        tag = await builder.build_environment_image(env.id, version + 1, packages)
        if tag:
            from app.core.database import AsyncSessionLocal
            from app.conductor.services.environment_service import EnvironmentService as ES

            async with AsyncSessionLocal() as db:
                svc = ES(db)
                e = await svc.get_environment(env.id)
                if e:
                    e.image_tag = tag
                    e.image_version = version + 1
                    await db.commit()
            logger.info("Built environment image %s for env %s", tag, env.id)
    except Exception as e:
        logger.warning("Failed to build image for environment %s: %s", env.id, e)


def _env_to_response(env) -> EnvironmentResponse:
    return EnvironmentResponse(
        id=env.id,
        name=env.name,
        description=env.description,
        metadata=env.metadata_,
        config=env.config,
        created_at=env.created_at,
        updated_at=env.updated_at,
        archived_at=env.archived_at,
    )


@router.post("", status_code=201)
async def create_environment(
    req: CreateEnvironmentRequest, db: AsyncSession = Depends(get_db)
) -> EnvironmentResponse:
    svc = EnvironmentService(db)
    env = await svc.create_environment(req)

    # Auto-build image if packages are specified
    await _try_build_image(env)

    return _env_to_response(env)


@router.get("")
async def list_environments(
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[EnvironmentResponse]:
    svc = EnvironmentService(db)
    envs, has_more = await svc.list_environments(limit, after_id)
    data = [_env_to_response(e) for e in envs]
    return PaginatedResponse(
        data=data,
        has_more=has_more,
        first_id=str(data[0].id) if data else None,
        last_id=str(data[-1].id) if data else None,
    )


@router.get("/{env_id}")
async def get_environment(
    env_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> EnvironmentResponse:
    svc = EnvironmentService(db)
    env = await svc.get_environment(env_id)
    if not env:
        raise HTTPException(404, "Environment not found")
    return _env_to_response(env)


@router.post("/{env_id}")
async def update_environment(
    env_id: uuid.UUID,
    req: UpdateEnvironmentRequest,
    db: AsyncSession = Depends(get_db),
) -> EnvironmentResponse:
    svc = EnvironmentService(db)
    env = await svc.update_environment(env_id, req)
    if not env:
        raise HTTPException(404, "Environment not found")

    # Auto-build image if packages changed
    if req.config is not None:
        await _try_build_image(env)

    return _env_to_response(env)


@router.delete("/{env_id}", status_code=204)
async def delete_environment(
    env_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> None:
    svc = EnvironmentService(db)
    ok = await svc.delete_environment(env_id)
    if not ok:
        raise HTTPException(404, "Environment not found")


@router.post("/{env_id}/archive")
async def archive_environment(
    env_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict:
    svc = EnvironmentService(db)
    ok = await svc.archive_environment(env_id)
    if not ok:
        raise HTTPException(404, "Environment not found")
    return {"status": "archived"}
