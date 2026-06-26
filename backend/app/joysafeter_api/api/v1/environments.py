import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_api.api.v1.id_helpers import parse_env_id
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    get_joysafeter_auth_context,
    require_joysafeter_write,
)
from app.joysafeter_shared.database import get_db
from app.joysafeter_domain.schemas.joysafeter_environment import (
    CreateEnvironmentRequest,
    EnvironmentResponse,
    UpdateEnvironmentRequest,
)
from app.joysafeter_domain.schemas.base import CursorPaginatedResponse as PaginatedResponse
from app.joysafeter_api.services import JoySafeterEnvironmentService as EnvironmentService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["joysafeter-environments"])


async def _validate_and_build_image(env) -> None:
    """Validate packages by building the Docker image synchronously.

    Raises HTTPException(400) if the build fails so the caller can propagate
    the error to the client.
    """
    from app.joysafeter_orchestrator.lifespan import get_image_builder

    builder = get_image_builder()
    config = env.config or {}
    packages = config.get("packages", {}) if isinstance(config, dict) else {}
    if not packages:
        return

    if not builder:
        logger.info("Image builder unavailable; skipping environment image build for %s", env.id)
        return

    version = getattr(env, "image_version", 0) or 0
    tag = await builder.build_environment_image(env.id, version + 1, packages)
    if tag:
        from app.joysafeter_shared.database import AsyncSessionLocal
        from app.joysafeter_api.services import JoySafeterEnvironmentService as ES

        async with AsyncSessionLocal() as db:
            svc = ES(db)
            e = await svc.get_environment(env.id, project_id=getattr(env, "project_id", None))
            if e:
                e.image_tag = tag
                e.image_version = version + 1
                await db.commit()
        logger.info("Built environment image %s for env %s", tag, env.id)


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
        image_tag=getattr(env, "image_tag", None),
        image_version=getattr(env, "image_version", 0) or 0,
    )


async def _validate_secret_refs(
    db: AsyncSession,
    secret_refs: list[str],
    project_id: Optional[str],
) -> None:
    if not secret_refs:
        return

    from app.joysafeter_api.services import SecretService

    secret_svc = SecretService(db)
    for secret_ref in secret_refs:
        ref = str(secret_ref).strip()
        if not ref:
            continue
        secret = await secret_svc.get_secret_by_name(ref, project_id=project_id)
        if not secret:
            raise HTTPException(400, f"Secret not found: {ref}")


@router.post("", status_code=201)
async def create_environment(
    req: CreateEnvironmentRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> EnvironmentResponse:
    await _validate_secret_refs(db, req.config.secret_refs, auth_ctx.project_id)

    svc = EnvironmentService(db)
    env = await svc.create_environment(req, project_id=auth_ctx.project_id)

    # Validate packages synchronously -- fail the request on build error
    try:
        await _validate_and_build_image(env)
    except Exception as exc:
        # Roll back the created environment on build failure
        await svc.delete_environment(env.id, project_id=auth_ctx.project_id)
        raise HTTPException(
            500,
            f"Image build failed: {exc}",
        )

    return _env_to_response(env)


@router.get("")
async def list_environments(
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[uuid.UUID] = Query(None),
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> PaginatedResponse[EnvironmentResponse]:
    svc = EnvironmentService(db)
    envs, has_more = await svc.list_environments(limit, after_id, include_archived, project_id=auth_ctx.project_id)
    data = [_env_to_response(e) for e in envs]
    return PaginatedResponse(
        data=data,
        has_more=has_more,
        first_id=str(data[0].id) if data else None,
        last_id=str(data[-1].id) if data else None,
    )


@router.get("/{env_id}")
async def get_environment(
    env_id: uuid.UUID = Depends(parse_env_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> EnvironmentResponse:
    svc = EnvironmentService(db)
    env = await svc.get_environment(env_id, project_id=auth_ctx.project_id)
    if not env:
        raise HTTPException(404, "Environment not found")
    return _env_to_response(env)


@router.post("/{env_id}")
async def update_environment(
    req: UpdateEnvironmentRequest,
    env_id: uuid.UUID = Depends(parse_env_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> EnvironmentResponse:
    svc = EnvironmentService(db)
    env = await svc.get_environment(env_id, project_id=auth_ctx.project_id)
    if not env:
        raise HTTPException(404, "Environment not found")

    if env.archived_at is not None:
        raise HTTPException(409, "Cannot update an archived environment")

    if req.config is not None:
        await _validate_secret_refs(db, req.config.secret_refs, auth_ctx.project_id)

    env = await svc.update_environment(env_id, req, project_id=auth_ctx.project_id)
    if not env:
        raise HTTPException(404, "Environment not found")

    # Validate packages synchronously if config changed
    if req.config is not None:
        try:
            await _validate_and_build_image(env)
        except Exception as exc:
            raise HTTPException(
                500,
                f"Image build failed: {exc}",
            )

    return _env_to_response(env)


@router.delete("/{env_id}", status_code=204)
async def delete_environment(
    env_id: uuid.UUID = Depends(parse_env_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> None:
    svc = EnvironmentService(db)
    env = await svc.get_environment(env_id, project_id=auth_ctx.project_id)
    if not env:
        raise HTTPException(404, "Environment not found")

    if await svc.environment_is_referenced_by_sessions(
        env.name, env.id, project_id=auth_ctx.project_id
    ):
        raise HTTPException(
            409,
            "Environment is referenced by one or more active sessions. "
            "Archive or remove those sessions first.",
        )

    ok = await svc.delete_environment(env_id, project_id=auth_ctx.project_id)
    if not ok:
        raise HTTPException(404, "Environment not found")


@router.post("/{env_id}/archive")
async def archive_environment(
    env_id: uuid.UUID = Depends(parse_env_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> dict:
    svc = EnvironmentService(db)
    env = await svc.get_environment(env_id, project_id=auth_ctx.project_id)
    if not env:
        raise HTTPException(404, "Environment not found")

    if env.archived_at is not None:
        raise HTTPException(409, "Environment is already archived")

    await svc.archive_environment(env_id, project_id=auth_ctx.project_id)
    return {"status": "archived"}
