"""
Graph API (path: /api/v1/graphs)
"""

import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.common.exceptions import ForbiddenException, NotFoundException

# Import Copilot types from the new module
from app.core.copilot import (
    CopilotRequest,
    CopilotResponse,
)
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.models.graph import AgentGraph, GraphNode
from app.models.workspace import WorkspaceMemberRole
from app.repositories.agent_run import AgentRunRepository
from app.repositories.workspace import WorkspaceRepository
from app.services.copilot_service import CopilotService
from app.services.graph_service import GraphService

router = APIRouter(prefix="/v1/graphs", tags=["Graphs"])


def _bind_log(request: Request, **kwargs):
    trace_id = getattr(request.state, "trace_id", "-")
    return logger.bind(trace_id=trace_id, **kwargs)


class GraphStatePayload(BaseModel):
    """Graph state payload."""

    nodes: List[Dict[str, Any]] = Field(default_factory=list, description="Node list")
    edges: List[Dict[str, Any]] = Field(default_factory=list, description="Edge list")
    viewport: Optional[Dict[str, Any]] = Field(default=None, description="Viewport info")
    variables: Optional[Dict[str, Any]] = Field(default=None, description="Graph variables (e.g. context variables)")
    # optional graph creation params (for upsert mode)
    name: Optional[str] = Field(default=None, max_length=200, description="Graph name (for creating a new graph)")
    workspaceId: Optional[uuid.UUID] = Field(default=None, description="Workspace ID (for creating a new graph)")


class CreateGraphRequest(BaseModel):
    """Create graph request."""

    name: str = Field(..., min_length=1, max_length=200, description="Graph name")
    description: Optional[str] = Field(default=None, max_length=2000, description="Graph description")
    color: Optional[str] = Field(default=None, max_length=2000, description="Color")
    workspaceId: Optional[uuid.UUID] = Field(default=None, description="Workspace ID")
    folderId: Optional[uuid.UUID] = Field(default=None, description="Folder ID")
    parentId: Optional[uuid.UUID] = Field(default=None, description="Parent graph ID")
    variables: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Variables")


class UpdateGraphRequest(BaseModel):
    """Update graph request."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=200, description="Graph name")
    description: Optional[str] = Field(default=None, max_length=2000, description="Graph description")
    color: Optional[str] = Field(default=None, max_length=2000, description="Color")
    folderId: Optional[uuid.UUID] = Field(default=None, description="Folder ID")
    parentId: Optional[uuid.UUID] = Field(default=None, description="Parent graph ID")
    isDeployed: Optional[bool] = Field(default=None, description="Whether deployed")


async def _ensure_workspace_member(
    *,
    db: AsyncSession,
    workspace_id: uuid.UUID,
    current_user: User,
    min_role: WorkspaceMemberRole,
) -> None:
    """
    Ensure the user is a workspace member with sufficient permissions.

    Args:
        db: database session
        workspace_id: workspace ID
        current_user: current user
        min_role: minimum required role

    Raises:
        NotFoundException: if the workspace does not exist
        ForbiddenException: if the user is not a member or lacks permission
    """
    from app.services.workspace_permission import check_workspace_access

    # check workspace existence
    workspace_repo = WorkspaceRepository(db)
    workspace = await workspace_repo.get(workspace_id)
    if not workspace:
        raise NotFoundException("Workspace not found")

    # check access permission
    has_access = await check_workspace_access(db, workspace_id, current_user, min_role)
    if not has_access:
        raise ForbiddenException("No access to workspace or insufficient permission")


def _serialize_graph_row(graph: AgentGraph, node_count: int = 0) -> Dict[str, Any]:
    """
    Serialize a graph object to a dict.

    Args:
        graph: graph object
        node_count: node count (optional)

    Returns:
        Serialized dict
    """
    return {
        "id": str(graph.id),
        "userId": str(graph.user_id),
        "workspaceId": str(graph.workspace_id) if graph.workspace_id else None,
        "folderId": str(graph.folder_id) if graph.folder_id else None,
        "parentId": str(graph.parent_id) if graph.parent_id else None,
        "name": graph.name,
        "description": graph.description,
        "color": graph.color,
        "isDeployed": graph.is_deployed,
        "variables": graph.variables or {},
        "createdAt": graph.created_at.isoformat() if graph.created_at else None,
        "updatedAt": graph.updated_at.isoformat() if graph.updated_at else None,
        "nodeCount": node_count,
    }


@router.get("")
async def list_graphs(
    request: Request,
    workspace_id: Optional[uuid.UUID] = Query(default=None, alias="workspaceId"),
    parent_id: Optional[uuid.UUID] = Query(default=None, alias="parentId"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List graphs.

    Filtering logic:
    - Default (no workspace_id): list all graphs owned by the current user (personal graphs)
    - If workspace_id is provided:
      - Check that the user has access to the workspace (at least viewer)
      - If authorized, return all graphs in the workspace (not limited to user-created ones)
      - If unauthorized, return an empty list
    - If parentId is provided: list sub-graphs under the specified parent graph
    """
    service = GraphService(db)

    log = _bind_log(request, user_id=str(current_user.id))

    log.info(f"graph.list start workspace_id={workspace_id} parent_id={parent_id}")

    # if workspace_id is provided, check permission and return all workspace graphs
    if workspace_id:
        # check that the user has access (at least viewer)
        await _ensure_workspace_member(
            db=db,
            workspace_id=workspace_id,
            current_user=current_user,
            min_role=WorkspaceMemberRole.viewer,
        )
        # return all graphs in the workspace (not limited to user)
        query = select(AgentGraph).where(
            AgentGraph.workspace_id == workspace_id,
            AgentGraph.deleted_at.is_(None),
        )
        if parent_id is not None:
            query = query.where(AgentGraph.parent_id == parent_id)
        query = query.order_by(AgentGraph.created_at.desc(), AgentGraph.id.desc())
        result = await db.execute(query)
        graphs = list(result.scalars().all())
    else:
        # no workspace_id — return user-owned graphs (personal graphs)
        graphs = await service.graph_repo.list_by_user_with_filters(
            user_id=current_user.id,
            parent_id=parent_id,
            workspace_id=None,
        )

    # batch-query node counts for each graph
    graph_ids = [graph.id for graph in graphs]
    node_counts: Dict[Any, int] = {}
    if graph_ids:
        # use GROUP BY to query all node counts in one shot
        count_query = (
            select(GraphNode.graph_id, func.count(GraphNode.id).label("count"))
            .where(GraphNode.graph_id.in_(graph_ids))
            .group_by(GraphNode.graph_id)
        )
        result = await db.execute(count_query)
        for row in result:
            count_val = getattr(row, "count", 0)
            node_counts[row.graph_id] = int(count_val) if not callable(count_val) else count_val()  # type: ignore[call-overload]

    log.info(f"graph.list success count={len(graphs)}")
    return {"data": [_serialize_graph_row(graph, node_counts.get(graph.id, 0)) for graph in graphs]}


@router.get("/deployed")
async def list_deployed_graphs(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List deployed graphs accessible to the current user.

    Includes:
    1. Deployed graphs created by the user
    2. Deployed graphs in workspaces the user has access to (at least viewer)

    Filters:
    - is_deployed = True
    - User is the graph owner, or user has workspace access
    """
    from sqlalchemy import or_

    from app.models.workspace import WorkspaceMemberRole
    from app.repositories.workspace import WorkspaceRepository
    from app.services.workspace_permission import check_workspace_access

    log = _bind_log(request, user_id=str(current_user.id))
    log.info("graph.list_deployed start")

    workspace_repo = WorkspaceRepository(db)
    user_workspaces = await workspace_repo.list_for_user(current_user.id)
    accessible_workspace_ids = [ws.id for ws in user_workspaces]

    conditions = [AgentGraph.is_deployed, AgentGraph.deleted_at.is_(None)]

    user_owned_condition = AgentGraph.user_id == str(current_user.id)

    if accessible_workspace_ids:
        workspace_condition = AgentGraph.workspace_id.in_(accessible_workspace_ids)
        graph_condition = or_(user_owned_condition, workspace_condition)
    else:
        graph_condition = user_owned_condition

    conditions.append(graph_condition)  # type: ignore[arg-type]

    query = select(AgentGraph).where(*conditions).order_by(AgentGraph.created_at.desc())
    result = await db.execute(query)
    all_graphs = list(result.scalars().all())

    filtered_graphs = []
    for graph in all_graphs:
        if graph.user_id == str(current_user.id):
            filtered_graphs.append(graph)
        elif graph.workspace_id:
            has_access = await check_workspace_access(
                db,
                graph.workspace_id,
                current_user,
                WorkspaceMemberRole.viewer,
            )
            if has_access:
                filtered_graphs.append(graph)

    graphs = filtered_graphs

    graph_ids = [graph.id for graph in graphs]
    node_counts: Dict[Any, int] = {}
    if graph_ids:
        count_query = (
            select(GraphNode.graph_id, func.count(GraphNode.id).label("count"))
            .where(GraphNode.graph_id.in_(graph_ids))
            .group_by(GraphNode.graph_id)
        )
        result = await db.execute(count_query)
        for row in result:
            count_val = getattr(row, "count", 0)
            node_counts[row.graph_id] = int(count_val) if not callable(count_val) else count_val()  # type: ignore[call-overload]

    log.info(f"graph.list_deployed success count={len(graphs)}")
    return {"data": [_serialize_graph_row(graph, node_counts.get(graph.id, 0)) for graph in graphs]}


@router.post("")
async def create_graph(
    request: Request,
    payload: CreateGraphRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a new graph.

    - personal graph: created by the current user
    - workspace graph: requires workspace write permission (member+)
    """
    log = _bind_log(request, user_id=str(current_user.id))
    parent_id = payload.parentId
    workspace_id = payload.workspaceId

    # workspace_id may be None (personal graph)

    if workspace_id:
        await _ensure_workspace_member(
            db=db,
            workspace_id=workspace_id,
            current_user=current_user,
            min_role=WorkspaceMemberRole.member,
        )

    service = GraphService(db)
    graph = await service.create_graph(
        name=payload.name.strip(),
        user_id=current_user.id,
        workspace_id=workspace_id,
        folder_id=payload.folderId,
        parent_id=parent_id,
        description=payload.description.strip() if payload.description else None,
        color=payload.color,
        variables=payload.variables,
    )
    await db.commit()
    log.info(f"graph.create success graph_id={graph.id} workspace_id={workspace_id} parent_id={parent_id}")
    return {"data": _serialize_graph_row(graph)}


@router.get("/{graph_id}")
async def get_graph(
    graph_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get graph details including nodes and edges.

    Returns:
        {
            "data": {
                "id": "...",
                "name": "...",
                "nodes": [...],
                "edges": [...],
                "viewport": {...},
                ...
            }
        }
    """
    service = GraphService(db)
    data = await service.get_graph_detail(graph_id, current_user)
    return {"data": data}


@router.put("/{graph_id}")
async def update_graph(
    graph_id: uuid.UUID,
    payload: UpdateGraphRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update graph metadata (name/description/color/folderId/parentId/isDeployed)."""
    service = GraphService(db)
    graph = await service.graph_repo.get(graph_id)
    if not graph:
        raise NotFoundException("Graph not found")

    # permission check
    await service._ensure_access(graph, current_user, WorkspaceMemberRole.member)

    update_data: Dict[str, Any] = {}
    fields_set: set[str] = getattr(payload, "model_fields_set", set())

    if payload.name is not None:
        update_data["name"] = payload.name.strip()
    if "description" in fields_set:
        update_data["description"] = payload.description
    if payload.color is not None:
        update_data["color"] = payload.color
    if "folderId" in fields_set:
        # if folderId is provided, verify it exists and belongs to the current workspace
        if payload.folderId is not None:
            from app.repositories.workspace_folder import WorkflowFolderRepository

            folder_repo = WorkflowFolderRepository(db)
            folder = await folder_repo.get(payload.folderId)
            if not folder:
                raise NotFoundException(f"Folder with id {payload.folderId} not found")
            # ensure folder belongs to the graph's workspace
            if graph.workspace_id and folder.workspace_id != graph.workspace_id:
                from app.common.exceptions import BadRequestException

                raise BadRequestException(
                    f"Folder {payload.folderId} does not belong to workspace {graph.workspace_id}"
                )
        # allow setting to None to clear the folder association
        update_data["folder_id"] = payload.folderId
    if "parentId" in fields_set:
        # if parentId is provided, verify it exists (allow None to clear the parent relationship)
        if payload.parentId is not None:
            parent_graph = await service.graph_repo.get(payload.parentId)
            if not parent_graph:
                raise NotFoundException(f"Parent graph with id {payload.parentId} not found")
        # allow setting to None to clear the parent graph relationship
        update_data["parent_id"] = payload.parentId
    if payload.isDeployed is not None:
        update_data["is_deployed"] = payload.isDeployed

    if update_data:
        await service.graph_repo.update(graph_id, update_data)
        await db.commit()

    graph2 = await service.graph_repo.get(graph_id)
    if not graph2:
        raise NotFoundException("Graph not found")
    return {"data": _serialize_graph_row(graph2)}


@router.delete("/{graph_id}")
async def delete_graph(
    graph_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a graph (requires member permission, i.e. write access)."""
    service = GraphService(db)
    graph = await service.graph_repo.get(graph_id)
    if not graph:
        raise NotFoundException("Graph not found")

    # permission check:
    # - personal graph: only the owner can delete
    # - workspace graph: requires at least member permission (write access)
    if graph.workspace_id:
        # workspace graph: requires member permission to delete
        await service._ensure_access(
            graph,
            current_user,
            required_role=WorkspaceMemberRole.member,
        )
    else:
        # personal graph: only the owner can delete
        if graph.user_id != current_user.id:
            raise ForbiddenException("Only graph owner can delete personal graph")

    await service.graph_repo.soft_delete(graph_id)
    await db.commit()
    return {"success": True}


@router.get("/{graph_id}/state")
async def load_graph_state(
    graph_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Load graph state (nodes and edges).

    Returns:
        {
            "success": true,
            "data": {
                "nodes": [...],
                "edges": [...],
                "viewport": {...}
            }
        }
    """
    service = GraphService(db)
    state = await service.load_graph_state(graph_id, current_user)
    return {"success": True, "data": state}


@router.post("/{graph_id}/state")
async def save_graph_state(
    request: Request,
    graph_id: uuid.UUID,
    payload: GraphStatePayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Save graph state (nodes and edges) — supports upsert mode.

    If the graph does not exist, automatically create a new one (requires name parameter).

    Accepts frontend format:
    {
        "nodes": [...],
        "edges": [...],
        "viewport": {...},
        "name": "optional, for creating a new graph",
        "workspaceId": "optional, for creating a new graph"
    }
    """
    log = _bind_log(request, user_id=str(current_user.id), graph_id=str(graph_id))
    service = GraphService(db)

    # workspace_id may be None (personal graph)
    workspace_id = payload.workspaceId

    result = await service.save_graph_state(
        graph_id=graph_id,
        nodes=payload.nodes,
        edges=payload.edges,
        viewport=payload.viewport,
        variables=payload.variables,
        current_user=current_user,
        # upsert parameters
        name=payload.name,
        workspace_id=workspace_id,
    )

    # explicitly commit the transaction to persist data
    # note: get_db() does not auto-commit; an explicit commit() is required
    await db.commit()

    log.info(f"graph.state.save success nodes={len(payload.nodes)} edges={len(payload.edges)}")
    return {"success": True, **result}


@router.put("/{graph_id}/state")
async def save_graph_state_put(
    request: Request,
    graph_id: uuid.UUID,
    payload: GraphStatePayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """PUT alias for saving graph state."""
    return await save_graph_state(request, graph_id, payload, db, current_user)


# ==================== Compile (pre-build + cache warm) ====================


@router.post("/{graph_id}/compile")
async def compile_graph(
    request: Request,
    graph_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Compile a graph and warm the cache; return build time. Execution uses the cache if not expired."""
    service = GraphService(db)
    graph = await service.graph_repo.get(graph_id)
    if not graph:
        raise NotFoundException("Graph not found")
    await service._ensure_access(graph, current_user, WorkspaceMemberRole.viewer)
    start = time.time()
    try:
        await service.create_graph_by_graph_id(
            graph_id=graph_id,
            user_id=current_user.id,
            current_user=current_user,
        )
        build_time_ms = (time.time() - start) * 1000
        return {"ok": True, "build_time_ms": round(build_time_ms, 2)}
    except Exception as e:
        log = _bind_log(request, user_id=str(current_user.id), graph_id=str(graph_id))
        log.error(f"graph.compile failed: {e}")
        raise


# ==================== Copilot Endpoints ====================


@router.get("/{graph_id}/copilot/history")
async def get_copilot_history(
    request: Request,
    graph_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    log = _bind_log(request, user_id=str(current_user.id), graph_id=str(graph_id))
    log.info("copilot.history.get start")

    graph_service = GraphService(db)
    graph = await graph_service.graph_repo.get(graph_id)
    if not graph:
        raise NotFoundException("Graph not found")
    await graph_service._ensure_access(graph, current_user, WorkspaceMemberRole.viewer)

    repo = AgentRunRepository(db)
    runs = await repo.list_recent_runs_for_user(
        user_id=str(current_user.id),
        agent_name="copilot",
        graph_id=graph_id,
        limit=100,
    )

    messages = []
    for run in reversed(list(runs)):  # oldest first
        snapshot = await repo.get_snapshot(run.id)
        if not snapshot or not snapshot.projection:
            continue
        p = snapshot.projection
        messages.append(
            {
                "role": "user",
                "content": run.title or "",
                "created_at": run.created_at.isoformat() if run.created_at else None,
            }
        )
        messages.append(
            {
                "role": "assistant",
                "content": p.get("result_message") or p.get("content", ""),
                "created_at": run.updated_at.isoformat() if run.updated_at else None,
                "actions": p.get("result_actions", []),
                "thought_steps": p.get("thought_steps", []),
                "tool_calls": p.get("tool_calls", []),
            }
        )

    log.info(f"copilot.history.get success messages_count={len(messages)}")
    return {"data": {"graph_id": str(graph_id), "messages": messages}}


@router.delete("/{graph_id}/copilot/history")
async def clear_copilot_history(
    request: Request,
    graph_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    log = _bind_log(request, user_id=str(current_user.id), graph_id=str(graph_id))
    log.info("copilot.history.clear start")

    graph_service = GraphService(db)
    graph = await graph_service.graph_repo.get(graph_id)
    if not graph:
        raise NotFoundException("Graph not found")
    await graph_service._ensure_access(graph, current_user, WorkspaceMemberRole.member)

    repo = AgentRunRepository(db)
    deleted = await repo.delete_runs_for_graph(
        user_id=str(current_user.id),
        agent_name="copilot",
        graph_id=graph_id,
    )

    log.info(f"copilot.history.clear success deleted={deleted}")
    return {"success": True}


@router.post("/copilot/actions", response_model=CopilotResponse)
async def generate_graph_actions(
    request: Request,
    payload: CopilotRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CopilotResponse:
    """
    Generate graph actions using AI Copilot ("God Mode" Engine)

    This endpoint uses an Agent-based approach with tools to generate
    graph modification actions (CREATE_NODE, CONNECT_NODES, etc.)

    Args:
        payload: CopilotRequest with user prompt and graph context
        current_user: Authenticated user

    Returns:
        CopilotResponse: Message to the user and array of actions to execute
    """
    log = _bind_log(request, user_id=str(current_user.id))

    nodes = payload.graph_context.get("nodes", [])
    log.info(f"copilot.actions start nodes={len(nodes)}")

    # Use CopilotService for action generation
    service = CopilotService(user_id=str(current_user.id), llm_model=payload.model, db=db)
    response = await service.generate_actions(
        prompt=payload.prompt,
        graph_context=payload.graph_context,
        conversation_history=payload.conversation_history,
    )

    log.info(f"copilot.actions success actions_count={len(response.actions)}")
    return response
