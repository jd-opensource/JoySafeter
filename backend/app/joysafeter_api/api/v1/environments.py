import logging
import re
from typing import NamedTuple, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_api.api.v1.network_policy_refresh import (
    refresh_live_limited_sandbox_network_policies,
)
from app.joysafeter_domain.schemas.base import CursorPaginatedResponse as PaginatedResponse
from app.joysafeter_domain.schemas.joysafeter_environment import (
    CreateEnvironmentRequest,
    EnvironmentResponse,
    UpdateEnvironmentRequest,
)
from app.joysafeter_domain.services.joysafeter_environment_service import EnvironmentService
from app.joysafeter_domain.services.joysafeter_storage_mount_service import StorageMountService
from app.joysafeter_shared.common.app_errors import (
    AppError,
    InternalServiceError,
    InvalidRequestError,
    NotFoundError,
    ResourceConflictError,
    ServiceUnavailableError,
)
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    get_joysafeter_auth_context,
    require_joysafeter_write,
)
from app.joysafeter_shared.database import get_db
from app.joysafeter_shared.ids import EnvironmentId, TaskId

logger = logging.getLogger(__name__)

router = APIRouter(tags=["joysafeter-environments"])

_ACTIVE_TASK_ENV_RE = re.compile(r"^Environment is required by active task '([^']+)' via ([^.]+)\. (.+)$")
_AGENT_ENV_RE = re.compile(r"^Environment is referenced by agent '([^']+)'\.$")
_TRIGGER_ENV_RE = re.compile(r"^Environment is referenced by cron trigger '([^']+)'\.$")


class _EnvironmentImageUpdate(NamedTuple):
    image_tag: Optional[str]
    image_version: int


def _environment_conflict_error(env_id: EnvironmentId, exc: ValueError) -> AppError:
    message = str(exc)
    active_task_match = _ACTIVE_TASK_ENV_RE.match(message)
    if active_task_match:
        task_id, source, _rest = active_task_match.groups()
        return ResourceConflictError(
            code="ENVIRONMENT_ACTIVE_TASK",
            message=message,
            data={"environment_id": str(env_id), "task_id": str(TaskId(task_id)), "source": source},
            retryable=True,
            user_action="retry",
        )

    agent_match = _AGENT_ENV_RE.match(message)
    if agent_match:
        return ResourceConflictError(
            code="ENVIRONMENT_AGENT_REFERENCE",
            message=message,
            data={"environment_id": str(env_id), "agent_name": agent_match.group(1)},
        )

    trigger_match = _TRIGGER_ENV_RE.match(message)
    if trigger_match:
        return ResourceConflictError(
            code="ENVIRONMENT_TRIGGER_REFERENCE",
            message=message,
            data={"environment_id": str(env_id), "trigger_name": trigger_match.group(1)},
        )

    if message.startswith("Environment is referenced by one or more active sessions"):
        return ResourceConflictError(
            code="ENVIRONMENT_ACTIVE_SESSION_REFERENCE",
            message=message,
            data={"environment_id": str(env_id)},
            retryable=True,
            user_action="retry",
        )

    return ResourceConflictError(
        code="ENVIRONMENT_CONFLICT",
        message=message,
        data={"environment_id": str(env_id)},
    )


def _environment_not_found_error(env_id: EnvironmentId) -> AppError:
    return NotFoundError(
        code="ENVIRONMENT_NOT_FOUND",
        message="Environment not found",
        data={"environment_id": str(env_id)},
        user_action="refresh",
    )


def _environment_image_build_error(env_id: EnvironmentId, *, operation: str, exc: Exception) -> AppError:
    return InternalServiceError(
        code="ENVIRONMENT_IMAGE_BUILD_FAILED",
        message=f"Image build failed: {exc}",
        data={"environment_id": str(env_id), "operation": operation},
        source="runtime",
        retryable=True,
        user_action="retry",
    )


def _environment_image_builder_unavailable_error(env_id: EnvironmentId) -> AppError:
    return ServiceUnavailableError(
        code="ENVIRONMENT_IMAGE_BUILDER_UNAVAILABLE",
        message="Image builder is unavailable; cannot provision environment packages right now",
        data={"environment_id": str(env_id)},
    )


def _apply_image_update(env, update: _EnvironmentImageUpdate) -> None:
    env.image_tag = update.image_tag
    env.image_version = update.image_version


def _is_packages_empty(packages: dict) -> bool:
    return not any(packages.get(key) for key in ("apt", "pip", "npm", "cargo", "gem", "go"))


async def _build_image_update(env) -> _EnvironmentImageUpdate:
    """Validate packages by asking the Rust runtime to build the Docker image.

    Raises an AppError if the build fails so the caller can propagate the
    error to the client.
    """
    from app.joysafeter_shared.orchestrator_bridge.runtime_commands import relay_environment_image_build_via_redis

    config = env.config or {}
    packages = config.get("packages", {}) if isinstance(config, dict) else {}
    if not isinstance(packages, dict) or not packages or _is_packages_empty(packages):
        return _EnvironmentImageUpdate(image_tag=None, image_version=0)

    version = getattr(env, "image_version", 0) or 0
    tag = await relay_environment_image_build_via_redis(
        env.id,
        version=version + 1,
        packages=packages,
        boundary="environment_api",
        operation="build_environment_image",
        failure_code="ENVIRONMENT_IMAGE_BUILD_RELAY_FAILED",
        failure_message="Redis environment image build relay failed",
    )
    if tag:
        logger.info("Built environment image %s for env %s", tag, env.id)
        return _EnvironmentImageUpdate(image_tag=tag, image_version=version + 1)

    logger.warning("Image builder unavailable; refusing to persist environment %s with packages", env.id)
    raise _environment_image_builder_unavailable_error(env.id)


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

    from app.joysafeter_domain.services.joysafeter_secret_service import SecretService

    secret_svc = SecretService(db)
    for secret_ref in secret_refs:
        ref = str(secret_ref).strip()
        if not ref:
            continue
        secret = await secret_svc.get_secret_by_name(ref, project_id=project_id)
        if not secret:
            raise InvalidRequestError(
                code="ENVIRONMENT_SECRET_NOT_FOUND",
                message=f"Secret not found: {ref}",
                data={"secret_ref": ref},
                user_action="fix_input",
            )


@router.get("/mount-catalog/storage")
async def get_storage_mount_catalog(
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> dict:
    return {"data": await StorageMountService(db).catalog_for_project(auth_ctx.project_id)}


@router.post("", status_code=201)
async def create_environment(
    req: CreateEnvironmentRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> EnvironmentResponse:
    await _validate_secret_refs(db, req.config.secret_refs, auth_ctx.project_id)
    await StorageMountService(db).validate_mount_resources(req.config.mount_resources, auth_ctx.project_id)

    svc = EnvironmentService(db)
    env = await svc.create_environment(req, project_id=auth_ctx.project_id)

    # Validate packages synchronously -- fail the request on build error
    try:
        _apply_image_update(env, await _build_image_update(env))
        await db.commit()
        await db.refresh(env)
    except AppError:
        # Builder-unavailable (or any structured error) rolls back the created
        # environment while preserving its distinct error code for the client.
        await svc.delete_environment(env.id, project_id=auth_ctx.project_id)
        raise
    except Exception as exc:
        # Roll back the created environment on build failure
        await svc.delete_environment(env.id, project_id=auth_ctx.project_id)
        raise _environment_image_build_error(env.id, operation="create", exc=exc) from exc

    return _env_to_response(env)


@router.get("")
async def list_environments(
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[EnvironmentId] = Query(None),
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
    env_id: EnvironmentId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> EnvironmentResponse:
    svc = EnvironmentService(db)
    env = await svc.get_environment(env_id, project_id=auth_ctx.project_id)
    if not env:
        raise _environment_not_found_error(env_id)
    return _env_to_response(env)


@router.post("/{env_id}")
async def update_environment(
    req: UpdateEnvironmentRequest,
    env_id: EnvironmentId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> EnvironmentResponse:
    svc = EnvironmentService(db)
    env = await svc.get_environment(env_id, project_id=auth_ctx.project_id)
    if not env:
        raise _environment_not_found_error(env_id)

    if env.archived_at is not None:
        raise ResourceConflictError(
            code="ENVIRONMENT_ARCHIVED",
            message="Cannot update an archived environment",
            data={"environment_id": str(env_id)},
            user_action="refresh",
        )

    if req.config is not None:
        await _validate_secret_refs(db, req.config.secret_refs, auth_ctx.project_id)
        await StorageMountService(db).validate_mount_resources(req.config.mount_resources, auth_ctx.project_id)

    try:
        try:
            env = await svc.update_environment(env_id, req, project_id=auth_ctx.project_id, commit=False)
        except ValueError as exc:
            raise _environment_conflict_error(env_id, exc) from exc
        if not env:
            raise _environment_not_found_error(env_id)

        # Validate packages synchronously if config changed. Config and image
        # fields commit together so failed builds do not leave a half-updated
        # environment pointing at the previous image.
        if req.config is not None:
            _apply_image_update(env, await _build_image_update(env))
        await db.commit()
        await db.refresh(env)
    except AppError:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        if req.config is not None:
            raise _environment_image_build_error(env_id, operation="update", exc=exc) from exc
        raise

    if req.config is not None:
        await refresh_live_limited_sandbox_network_policies(
            db,
            project_id=auth_ctx.project_id,
            reason="environment.updated",
            source_type="environment",
            source_id=str(env_id),
        )

    return _env_to_response(env)


@router.delete("/{env_id}", status_code=204)
async def delete_environment(
    env_id: EnvironmentId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> None:
    svc = EnvironmentService(db)
    env = await svc.get_environment(env_id, project_id=auth_ctx.project_id)
    if not env:
        raise _environment_not_found_error(env_id)

    if await svc.environment_is_referenced_by_sessions(env.name, env.id, project_id=auth_ctx.project_id):
        raise ResourceConflictError(
            code="ENVIRONMENT_ACTIVE_SESSION_REFERENCE",
            message="Environment is referenced by one or more active sessions. Archive or remove those sessions first.",
            data={"environment_id": str(env_id)},
            retryable=True,
            user_action="retry",
        )

    try:
        ok = await svc.delete_environment(env_id, project_id=auth_ctx.project_id)
    except ValueError as exc:
        raise _environment_conflict_error(env_id, exc) from exc
    if not ok:
        raise _environment_not_found_error(env_id)


@router.post("/{env_id}/archive")
async def archive_environment(
    env_id: EnvironmentId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> dict:
    svc = EnvironmentService(db)
    env = await svc.get_environment(env_id, project_id=auth_ctx.project_id)
    if not env:
        raise _environment_not_found_error(env_id)

    if env.archived_at is not None:
        raise ResourceConflictError(
            code="ENVIRONMENT_ARCHIVED",
            message="Environment is already archived",
            data={"environment_id": str(env_id)},
            user_action="refresh",
        )

    try:
        await svc.archive_environment(env_id, project_id=auth_ctx.project_id)
    except ValueError as exc:
        raise _environment_conflict_error(env_id, exc) from exc
    return {"status": "archived"}
