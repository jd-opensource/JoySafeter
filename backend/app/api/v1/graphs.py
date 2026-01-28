"""
Graph API（路径 /api/v1/graphs）
"""

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
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
from app.core.redis import RedisClient
from app.core.settings import settings
from app.models.auth import AuthUser as User
from app.models.graph import AgentGraph, GraphNode
from app.models.workspace import WorkspaceMemberRole
from app.repositories.workspace import WorkspaceRepository
from app.services.copilot_service import CopilotService
from app.services.graph_service import GraphService

router = APIRouter(prefix="/v1/graphs", tags=["Graphs"])


def _bind_log(request: Request, **kwargs):
    trace_id = getattr(request.state, "trace_id", "-")
    return logger.bind(trace_id=trace_id, **kwargs)


class GraphStatePayload(BaseModel):
    """图状态负载"""

    nodes: List[Dict[str, Any]] = Field(default_factory=list, description="节点列表")
    edges: List[Dict[str, Any]] = Field(default_factory=list, description="边列表")
    viewport: Optional[Dict[str, Any]] = Field(default=None, description="视口信息")
    variables: Optional[Dict[str, Any]] = Field(default=None, description="图变量（如 context 变量）")
    # 可选的图创建参数（用于 upsert 模式）
    name: Optional[str] = Field(default=None, max_length=200, description="图名称（用于创建新图）")
    workspaceId: Optional[uuid.UUID] = Field(default=None, description="工作空间ID（用于创建新图）")


class CreateGraphRequest(BaseModel):
    """创建图请求"""

    name: str = Field(..., min_length=1, max_length=200, description="图名称")
    description: Optional[str] = Field(default=None, max_length=2000, description="图描述")
    color: Optional[str] = Field(default=None, max_length=2000, description="颜色")
    workspaceId: Optional[uuid.UUID] = Field(default=None, description="工作空间ID")
    folderId: Optional[uuid.UUID] = Field(default=None, description="文件夹ID")
    parentId: Optional[uuid.UUID] = Field(default=None, description="父图ID")
    variables: Optional[Dict[str, Any]] = Field(default_factory=dict, description="变量")


class UpdateGraphRequest(BaseModel):
    """更新图请求"""

    name: Optional[str] = Field(default=None, min_length=1, max_length=200, description="图名称")
    description: Optional[str] = Field(default=None, max_length=2000, description="图描述")
    color: Optional[str] = Field(default=None, max_length=2000, description="颜色")
    folderId: Optional[uuid.UUID] = Field(default=None, description="文件夹ID")
    parentId: Optional[uuid.UUID] = Field(default=None, description="父图ID")
    isDeployed: Optional[bool] = Field(default=None, description="是否已部署")


async def _ensure_workspace_member(
    *,
    db: AsyncSession,
    workspace_id: uuid.UUID,
    current_user: User,
    min_role: WorkspaceMemberRole,
) -> None:
    """
    确保用户是工作空间成员且有足够权限

    Args:
        db: 数据库会话
        workspace_id: 工作空间ID
        current_user: 当前用户
        min_role: 所需的最低角色

    Raises:
        NotFoundException: 如果工作空间不存在
        ForbiddenException: 如果用户不是成员或权限不足
    """
    from app.services.workspace_permission import check_workspace_access

    # 检查工作空间是否存在
    workspace_repo = WorkspaceRepository(db)
    workspace = await workspace_repo.get(workspace_id)
    if not workspace:
        raise NotFoundException("Workspace not found")

    # 检查访问权限
    has_access = await check_workspace_access(db, workspace_id, current_user, min_role)
    if not has_access:
        raise ForbiddenException("No access to workspace or insufficient permission")


def _serialize_graph_row(graph: AgentGraph, node_count: int = 0) -> Dict[str, Any]:
    """
    序列化图对象为字典格式

    Args:
        graph: 图对象
        node_count: 节点数量（可选）

    Returns:
        序列化后的字典
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
    列出图列表

    过滤逻辑：
    - 默认（无 workspace_id）：列出当前用户拥有的所有 graphs（personal graphs）
    - 若传 workspace_id：
      - 检查用户是否有访问该工作空间的权限（至少 viewer）
      - 如果有权限，返回工作空间中的所有 graphs（不仅限于用户创建的）
      - 如果没有权限，返回空列表
    - 若传 parentId：列出指定父图下的子图
    """
    service = GraphService(db)

    log = _bind_log(request, user_id=str(current_user.id))

    log.info(f"graph.list start workspace_id={workspace_id} parent_id={parent_id}")

    # 如果有 workspace_id，需要检查权限并返回工作空间的所有 graphs
    if workspace_id:
        # 检查用户是否有访问该工作空间的权限（至少 viewer 权限）
        await _ensure_workspace_member(
            db=db,
            workspace_id=workspace_id,
            current_user=current_user,
            min_role=WorkspaceMemberRole.viewer,
        )
        # 返回工作空间中的所有 graphs（不限制用户）
        query = select(AgentGraph).where(AgentGraph.workspace_id == workspace_id)
        if parent_id is not None:
            query = query.where(AgentGraph.parent_id == parent_id)
        query = query.order_by(AgentGraph.updated_at.desc(), AgentGraph.id.desc())
        result = await db.execute(query)
        graphs = list(result.scalars().all())
    else:
        # 没有 workspace_id，返回用户拥有的所有 graphs（personal graphs）
        graphs = await service.graph_repo.list_by_user_with_filters(
            user_id=current_user.id,
            parent_id=parent_id,
            workspace_id=None,
        )

    # 批量查询每个图的节点数量
    graph_ids = [graph.id for graph in graphs]
    node_counts: Dict[Any, int] = {}
    if graph_ids:
        # 使用 GROUP BY 一次性查询所有图的节点数量
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
    获取当前用户可访问的已发布的图列表

    包括：
    1. 用户自己创建的已发布图
    2. 用户有权限访问的工作空间中已发布的图（至少 viewer 权限）

    过滤条件：
    - is_deployed = True
    - 用户是图的所有者，或者用户有工作空间的访问权限
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

    conditions = [AgentGraph.is_deployed]

    user_owned_condition = AgentGraph.user_id == str(current_user.id)

    if accessible_workspace_ids:
        workspace_condition = AgentGraph.workspace_id.in_(accessible_workspace_ids)
        graph_condition = or_(user_owned_condition, workspace_condition)
    else:
        graph_condition = user_owned_condition

    conditions.append(graph_condition)  # type: ignore[arg-type]

    query = select(AgentGraph).where(*conditions).order_by(AgentGraph.updated_at.desc())
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
    创建新图

    - personal graph：当前用户创建
    - workspace graph：要求 workspace write（member+）
    """
    log = _bind_log(request, user_id=str(current_user.id))
    parent_id = payload.parentId
    workspace_id = payload.workspaceId

    # 注意：workspace_id 可能为 None（personal graph）

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
    获取图的详细信息（包括节点和边）

    返回格式：
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
    """更新图元数据（name/description/color/folderId/parentId/isDeployed）"""
    service = GraphService(db)
    graph = await service.graph_repo.get(graph_id)
    if not graph:
        raise NotFoundException("Graph not found")

    # 权限检查
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
        # 如果提供了 folderId，验证它是否存在且属于当前 workspace
        if payload.folderId is not None:
            from app.repositories.workspace_folder import WorkflowFolderRepository

            folder_repo = WorkflowFolderRepository(db)
            folder = await folder_repo.get(payload.folderId)
            if not folder:
                raise NotFoundException(f"Folder with id {payload.folderId} not found")
            # 确保 folder 属于 graph 的 workspace
            if graph.workspace_id and folder.workspace_id != graph.workspace_id:
                from app.common.exceptions import BadRequestException

                raise BadRequestException(
                    f"Folder {payload.folderId} does not belong to workspace {graph.workspace_id}"
                )
        # 允许设置为 None 来清除文件夹关系
        update_data["folder_id"] = payload.folderId
    if "parentId" in fields_set:
        # 如果提供了 parentId，验证它是否存在（允许设置为 None 来清除父图关系）
        if payload.parentId is not None:
            parent_graph = await service.graph_repo.get(payload.parentId)
            if not parent_graph:
                raise NotFoundException(f"Parent graph with id {payload.parentId} not found")
        # 允许设置为 None 来清除父图关系
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
    """删除图（需要 member 权限，即 write 权限）"""
    service = GraphService(db)
    graph = await service.graph_repo.get(graph_id)
    if not graph:
        raise NotFoundException("Graph not found")

    # 检查权限：
    # - personal graph：只有 owner 可以删除
    # - workspace graph：需要至少 member 权限（write 权限）
    if graph.workspace_id:
        # 工作空间图：需要 member 权限才能删除
        await service._ensure_access(
            graph,
            current_user,
            required_role=WorkspaceMemberRole.member,
        )
    else:
        # 个人图：只有 owner 可以删除
        if graph.user_id != current_user.id:
            raise ForbiddenException("Only graph owner can delete personal graph")

    await service.graph_repo.delete(graph_id)
    await db.commit()
    return {"success": True}


@router.get("/{graph_id}/state")
async def load_graph_state(
    graph_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    加载图的状态（节点和边）

    返回格式：
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
    保存图的状态（节点和边）- 支持 upsert 模式

    如果图不存在，会自动创建新图（需要提供 name 参数）。

    接收前端格式：
    {
        "nodes": [...],
        "edges": [...],
        "viewport": {...},
        "name": "可选，用于创建新图",
        "workspaceId": "可选，用于创建新图"
    }
    """
    log = _bind_log(request, user_id=str(current_user.id), graph_id=str(graph_id))
    service = GraphService(db)

    # workspace_id 可能为 None（personal graph）
    workspace_id = payload.workspaceId

    result = await service.save_graph_state(
        graph_id=graph_id,
        nodes=payload.nodes,
        edges=payload.edges,
        viewport=payload.viewport,
        variables=payload.variables,
        current_user=current_user,
        # upsert 参数
        name=payload.name,
        workspace_id=workspace_id,
    )

    # 显式提交事务，确保数据保存到数据库
    # 注意：get_db() 不会自动提交，需要显式调用 commit()
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
    """PUT 方式保存图状态（别名）"""
    return await save_graph_state(request, graph_id, payload, db, current_user)


# ==================== Copilot Endpoints ====================


@router.get("/{graph_id}/copilot/history")
async def get_copilot_history(
    request: Request,
    graph_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get Copilot conversation history for a specific graph.

    Returns all previous messages with their actions, thought steps, and tool calls.
    This enables the frontend to restore the conversation when re-entering the graph.

    Args:
        graph_id: The graph ID to get history for
        current_user: Authenticated user

    Returns:
        CopilotHistoryResponse with messages array
    """
    log = _bind_log(request, user_id=str(current_user.id), graph_id=str(graph_id))
    log.info("copilot.history.get start")

    service = CopilotService(user_id=str(current_user.id), db=db)
    history = await service.get_history(str(graph_id))

    if history:
        log.info(f"copilot.history.get success messages_count={len(history.messages)}")
        return {
            "success": True,
            "data": {
                "graph_id": history.graph_id,
                "messages": [
                    {
                        "id": msg.id,
                        "role": msg.role,
                        "content": msg.content,
                        "created_at": msg.created_at.isoformat() if msg.created_at else None,
                        "actions": msg.actions,
                        "thought_steps": [{"index": s.index, "content": s.content} for s in msg.thought_steps]
                        if msg.thought_steps
                        else None,
                        "tool_calls": [{"tool": tc.tool, "input": tc.input} for tc in msg.tool_calls]
                        if msg.tool_calls
                        else None,
                    }
                    for msg in history.messages
                ],
                "created_at": history.created_at.isoformat() if history.created_at else None,
                "updated_at": history.updated_at.isoformat() if history.updated_at else None,
            },
        }
    else:
        log.info("copilot.history.get success no_history")
        return {
            "success": True,
            "data": {
                "graph_id": str(graph_id),
                "messages": [],
                "created_at": None,
                "updated_at": None,
            },
        }


@router.delete("/{graph_id}/copilot/history")
async def clear_copilot_history(
    request: Request,
    graph_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Clear Copilot conversation history for a specific graph.

    This resets the conversation, useful when starting fresh.

    Args:
        graph_id: The graph ID to clear history for
        current_user: Authenticated user

    Returns:
        Success status
    """
    log = _bind_log(request, user_id=str(current_user.id), graph_id=str(graph_id))
    log.info("copilot.history.clear start")

    service = CopilotService(user_id=str(current_user.id), db=db)
    success = await service.clear_history(str(graph_id))

    log.info(f"copilot.history.clear success={success}")
    return {"success": success}


@router.post("/{graph_id}/copilot/messages")
async def save_copilot_messages(
    request: Request,
    graph_id: uuid.UUID,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Save Copilot conversation messages for a specific graph.

    This saves user and assistant messages to the conversation history.

    Args:
        graph_id: The graph ID to save messages for
        payload: Message data containing user_message and assistant_message
        current_user: Authenticated user

    Returns:
        Success status
    """
    log = _bind_log(request, user_id=str(current_user.id), graph_id=str(graph_id))
    log.info("copilot.messages.save start")

    try:
        user_msg_data = payload.get("user_message", {})
        assistant_msg_data = payload.get("assistant_message", {})

        # Convert to CopilotMessage objects
        from app.core.copilot.action_types import CopilotMessage, CopilotThoughtStep

        user_message = CopilotMessage(
            id=str(uuid.uuid4()),
            role=user_msg_data.get("role", "user"),
            content=user_msg_data.get("content", ""),
        )

        assistant_message = CopilotMessage(
            id=str(uuid.uuid4()),
            role=assistant_msg_data.get("role", "assistant"),
            content=assistant_msg_data.get("content", ""),
            actions=assistant_msg_data.get("actions"),
            thought_steps=[
                CopilotThoughtStep(index=step["index"], content=step["content"])
                for step in assistant_msg_data.get("thought_steps", [])
            ]
            if assistant_msg_data.get("thought_steps")
            else None,
        )

        service = CopilotService(user_id=str(current_user.id), db=db)
        success = await service.save_messages(str(graph_id), user_message, assistant_message)

        log.info(f"copilot.messages.save success={success}")
        return {"success": success}

    except Exception as e:
        log.error(f"copilot.messages.save failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save messages: {str(e)}")


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
    service = CopilotService(user_id=str(current_user.id), db=db)
    response = await service.generate_actions(
        prompt=payload.prompt,
        graph_context=payload.graph_context,
        conversation_history=payload.conversation_history,
    )

    log.info(f"copilot.actions success actions_count={len(response.actions)}")
    return response


@router.post("/copilot/actions/create")
async def create_copilot_task(
    request: Request,
    payload: CopilotRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new Copilot task and return immediately with session_id.

    The actual generation runs asynchronously in the background.
    Frontend should subscribe to WebSocket to receive real-time updates.

    Args:
        payload: CopilotRequest with user prompt, graph context, and optional graph_id
        current_user: Authenticated user
        background_tasks: FastAPI background tasks

    Returns:
        {session_id, status, created_at}
    """
    import uuid as uuid_lib
    from datetime import datetime

    log = _bind_log(request, user_id=str(current_user.id))

    # Check Redis availability
    if not RedisClient.is_available():
        from app.core.copilot.exceptions import CopilotSessionError

        redis_status = "not configured" if not settings.redis_url else "connection failed"
        log.error(f"Redis {redis_status} - Copilot requires Redis for session management")
        raise CopilotSessionError(
            f"Redis {redis_status}. Copilot feature requires Redis to be running.",
            data={"redis_status": redis_status, "has_redis_url": bool(settings.redis_url)},
        )

    # Generate session ID
    session_id = f"copilot_{uuid_lib.uuid4().hex[:16]}"
    created_at = datetime.utcnow()

    # Initialize session in Redis
    await RedisClient.set_copilot_status(session_id, "generating")

    # Start background task
    service = CopilotService(user_id=str(current_user.id), db=db)
    background_tasks.add_task(
        service.generate_actions_async,
        session_id=session_id,
        graph_id=payload.graph_id,
        prompt=payload.prompt,
        graph_context=payload.graph_context,
        conversation_history=payload.conversation_history,
    )

    log.info(f"copilot.actions.create session_id={session_id} graph_id={payload.graph_id}")

    return {
        "session_id": session_id,
        "status": "generating",
        "created_at": created_at.isoformat(),
    }


@router.get("/copilot/sessions/{session_id}")
async def get_copilot_session(
    request: Request,
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get Copilot session status and current content.

    Returns:
        {session_id, status, content?, created_at, updated_at}
        - If status="generating": returns Redis content (real-time)
        - If status="completed" or not found: returns None (check database history)
    """
    from datetime import datetime

    log = _bind_log(request, user_id=str(current_user.id))

    # Check Redis availability
    if not RedisClient.is_available():
        from app.core.copilot.exceptions import CopilotSessionError

        redis_status = "not configured" if not settings.redis_url else "connection failed"
        log.error(f"Redis {redis_status} - Cannot retrieve Copilot session")
        raise CopilotSessionError(
            f"Redis {redis_status}. Copilot feature requires Redis to be running.", data={"redis_status": redis_status}
        )

    # Get session data from Redis
    session_data = await RedisClient.get_copilot_session(session_id)

    if not session_data:
        # Session not found in Redis (either completed or never existed)
        return {
            "session_id": session_id,
            "status": None,
            "content": None,
            "created_at": None,
            "updated_at": None,
        }

    # For generating sessions, return Redis content
    if session_data["status"] == "generating":
        return {
            "session_id": session_id,
            "status": session_data["status"],
            "content": session_data.get("content", ""),
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }

    # For completed/failed sessions, Redis data is temporary
    # History should be loaded from database via graph_id
    return {
        "session_id": session_id,
        "status": session_data["status"],
        "content": None,  # Completed sessions are in database
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
