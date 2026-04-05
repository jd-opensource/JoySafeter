"""
Graph deployment version API
"""

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.schemas.graph_deployment_version import (
    GraphDeploymentVersionListResponse,
    GraphDeploymentVersionResponseCamel,
    GraphDeploymentVersionStateResponse,
    GraphDeployRequest,
    GraphRenameVersionRequest,
    GraphRevertResponse,
)
from app.services.graph_deployment_version_service import GraphDeploymentVersionService

router = APIRouter(prefix="/v1/graphs", tags=["Graph Deployments"])


def _bind_log(request: Request, **kwargs):
    trace_id = getattr(request.state, "trace_id", "-")
    return logger.bind(trace_id=trace_id, **kwargs)


@router.get("/{graph_id}/deploy", response_model=Dict[str, Any])
async def get_deployment_status(
    graph_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get deployment status."""
    log = _bind_log(request, graph_id=str(graph_id))
    log.info("Getting deployment status for graph: {}", graph_id)

    service = GraphDeploymentVersionService(db)
    return await service.get_deployment_status(graph_id, current_user)


@router.post("/{graph_id}/deploy", response_model=Dict[str, Any])
async def deploy_graph(
    graph_id: uuid.UUID,
    request: Request,
    body: Optional[GraphDeployRequest] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deploy a graph."""
    log = _bind_log(request, graph_id=str(graph_id))
    log.info("Deploying graph: {}", graph_id)

    service = GraphDeploymentVersionService(db)
    name = body.name if body else None

    result = await service.deploy(graph_id, current_user, name)

    return {
        "success": result.success,
        "message": result.message,
        "version": result.version,
        "isActive": result.isActive,
        "needsRedeployment": result.needsRedeployment,
    }


@router.delete("/{graph_id}/deploy", response_model=Dict[str, Any])
async def undeploy_graph(
    graph_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Undeploy a graph."""
    log = _bind_log(request, graph_id=str(graph_id))
    log.info("Undeploying graph: {}", graph_id)

    service = GraphDeploymentVersionService(db)
    return await service.undeploy(graph_id, current_user)


@router.get("/{graph_id}/deployments", response_model=GraphDeploymentVersionListResponse)
async def list_deployment_versions(
    graph_id: uuid.UUID,
    request: Request,
    page: int = 1,
    page_size: int = 10,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all deployment versions (paginated)."""
    log = _bind_log(request, graph_id=str(graph_id))
    log.info("Listing deployment versions for graph: {} (page={}, page_size={})", graph_id, page, page_size)

    service = GraphDeploymentVersionService(db)
    return await service.list_versions(graph_id, current_user, page=page, page_size=page_size)


@router.get("/{graph_id}/deployments/{version}", response_model=GraphDeploymentVersionResponseCamel)
async def get_deployment_version(
    graph_id: uuid.UUID,
    version: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific deployment version."""
    log = _bind_log(request, graph_id=str(graph_id), version=version)
    log.info("Getting deployment version: {} v{}", graph_id, version)

    service = GraphDeploymentVersionService(db)
    return await service.get_version(graph_id, version, current_user)


@router.get("/{graph_id}/deployments/{version}/state", response_model=GraphDeploymentVersionStateResponse)
async def get_deployment_version_state(
    graph_id: uuid.UUID,
    version: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific deployment version's full state (for preview)."""
    log = _bind_log(request, graph_id=str(graph_id), version=version)
    log.info("Getting deployment version state: {} v{}", graph_id, version)

    service = GraphDeploymentVersionService(db)
    return await service.get_version_state(graph_id, version, current_user)


@router.patch("/{graph_id}/deployments/{version}", response_model=GraphDeploymentVersionResponseCamel)
async def rename_deployment_version(
    graph_id: uuid.UUID,
    version: int,
    body: GraphRenameVersionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rename a deployment version."""
    log = _bind_log(request, graph_id=str(graph_id), version=version)
    log.info("Renaming deployment version: {} v{} to '{}'", graph_id, version, body.name)

    service = GraphDeploymentVersionService(db)
    return await service.rename_version(graph_id, version, body.name, current_user)


@router.post("/{graph_id}/deployments/{version}/activate", response_model=Dict[str, Any])
async def activate_deployment_version(
    graph_id: uuid.UUID,
    version: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Activate a deployment version."""
    log = _bind_log(request, graph_id=str(graph_id), version=version)
    log.info("Activating deployment version: {} v{}", graph_id, version)

    service = GraphDeploymentVersionService(db)
    activated = await service.activate_version(graph_id, version, current_user)

    return {
        "success": True,
        "deployedAt": activated.createdAt,
    }


@router.post("/{graph_id}/deployments/{version}/revert", response_model=GraphRevertResponse)
async def revert_to_deployment_version(
    graph_id: uuid.UUID,
    version: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revert to a specific deployment version."""
    log = _bind_log(request, graph_id=str(graph_id), version=version)
    log.info("Reverting to deployment version: {} v{}", graph_id, version)

    service = GraphDeploymentVersionService(db)
    return await service.revert_to_version(graph_id, version, current_user)


@router.delete("/{graph_id}/deployments/{version}", response_model=Dict[str, Any])
async def delete_deployment_version(
    graph_id: uuid.UUID,
    version: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a deployment version."""
    log = _bind_log(request, graph_id=str(graph_id), version=version)
    log.info("Deleting deployment version: {} v{}", graph_id, version)

    service = GraphDeploymentVersionService(db)
    return await service.delete_version(graph_id, version, current_user)
