"""
Graph Variables API - Provides variable analysis and validation endpoints.

Endpoints:
- GET /api/graph/{graph_id}/variables - Get all variables in graph
- GET /api/graph/{graph_id}/nodes/{node_id}/available-variables - Get available variables for node
- POST /api/graph/{graph_id}/validate-variables - Validate variable usage
"""

from typing import Any, Dict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.common.exceptions import ForbiddenException, NotFoundException
from app.core.database import get_db
from app.core.graph.state_variable_tracker import StateVariableTracker
from app.models.auth import AuthUser as User
from app.models.graph import AgentGraph, GraphEdge, GraphNode
from app.models.workspace import WorkspaceMemberRole
from app.services.workspace_permission import check_workspace_access

router = APIRouter(prefix="/graph", tags=["graph-variables"])


@router.get("/{graph_id}/variables")
async def get_graph_variables(
    graph_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """获取图中所有变量的信息。

    Returns:
        {
            "variables": [
                {
                    "name": "user_id",
                    "path": "context.user_id",
                    "source": "Input Node",
                    "source_node_id": "node_123",
                    "scope": "global",
                    "description": "User ID",
                    "value_type": "string",
                    "is_defined": true,
                    "is_used": true,
                    "usages": [...]
                }
            ]
        }
    """
    # 获取图
    result = await db.execute(select(AgentGraph).where(AgentGraph.id == graph_id))
    graph = result.scalar_one_or_none()
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not found")

    # 检查权限
    if not current_user.is_superuser:
        if graph.user_id != current_user.id:
            if graph.workspace_id:
                has_access = await check_workspace_access(
                    db, graph.workspace_id, current_user, WorkspaceMemberRole.viewer
                )
                if not has_access:
                    raise ForbiddenException("No access to graph")
            else:
                raise ForbiddenException("No access to graph")

    # 获取节点和边
    nodes_result = await db.execute(
        select(GraphNode).where(GraphNode.graph_id == graph_id).order_by(GraphNode.position_x)
    )
    nodes = nodes_result.scalars().all()

    edges_result = await db.execute(select(GraphEdge).where(GraphEdge.graph_id == graph_id))
    edges = edges_result.scalars().all()

    # 分析变量
    tracker = StateVariableTracker(list(nodes), list(edges))
    variables_info = tracker.analyze_graph()

    # 转换为 API 响应格式
    variables_list = []
    for var_name, var_info in variables_info.items():
        variables_list.append(
            {
                "name": var_name,
                "path": var_info.definitions[0].path
                if var_info.definitions
                else var_info.usages[0].path
                if var_info.usages
                else f"context.{var_name}",
                "source": var_info.definitions[0].source_node_label if var_info.definitions else "Unknown",
                "source_node_id": var_info.definitions[0].source_node_id if var_info.definitions else None,
                "scope": var_info.scope,
                "description": var_info.definitions[0].description if var_info.definitions else None,
                "value_type": var_info.definitions[0].value_type if var_info.definitions else None,
                "is_defined": var_info.is_defined,
                "is_used": var_info.is_used,
                "usages": [
                    {
                        "node_id": usage.used_in_node_id,
                        "node_label": usage.used_in_node_label,
                        "usage_type": usage.usage_type,
                    }
                    for usage in var_info.usages
                ],
            }
        )

    return {"variables": variables_list}


@router.get("/{graph_id}/nodes/{node_id}/available-variables")
async def get_node_available_variables(
    graph_id: UUID,
    node_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """获取节点可用的变量列表。

    Returns:
        {
            "variables": [
                {
                    "name": "user_id",
                    "path": "context.user_id",
                    "source": "Input Node",
                    "scope": "global",
                    "description": "User ID",
                    "value_type": "string"
                }
            ]
        }
    """
    # 获取图
    result = await db.execute(select(AgentGraph).where(AgentGraph.id == graph_id))
    graph = result.scalar_one_or_none()
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not found")

    # 检查权限
    if not current_user.is_superuser:
        if graph.user_id != current_user.id:
            if graph.workspace_id:
                has_access = await check_workspace_access(
                    db, graph.workspace_id, current_user, WorkspaceMemberRole.viewer
                )
                if not has_access:
                    raise ForbiddenException("No access to graph")
            else:
                raise ForbiddenException("No access to graph")

    # 获取节点和边
    nodes_result = await db.execute(
        select(GraphNode).where(GraphNode.graph_id == graph_id).order_by(GraphNode.position_x)
    )
    nodes = nodes_result.scalars().all()

    edges_result = await db.execute(select(GraphEdge).where(GraphEdge.graph_id == graph_id))
    edges = edges_result.scalars().all()

    # 检查节点是否存在
    target_node = next((n for n in nodes if n.id == node_id), None)
    if not target_node:
        raise NotFoundException("Node not found")

    # 获取可用变量
    tracker = StateVariableTracker(list(nodes), list(edges))
    available_vars = tracker.get_available_variables_for_node(str(node_id))

    return {"variables": available_vars}


@router.post("/{graph_id}/validate-variables")
async def validate_variables(
    graph_id: UUID,
    request: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """验证表达式中使用的变量。

    Request:
        {
            "node_id": "node_123",
            "expression": "state.get('user_id', 0) > 10"
        }

    Returns:
        {
            "valid": true,
            "errors": [],
            "variables": [
                {
                    "name": "user_id",
                    "path": "context.user_id",
                    "available": true
                }
            ]
        }
    """
    node_id = request.get("node_id")
    expression = request.get("expression", "")

    if not node_id:
        raise HTTPException(status_code=400, detail="node_id is required")

    # 获取图
    result = await db.execute(select(AgentGraph).where(AgentGraph.id == graph_id))
    graph = result.scalar_one_or_none()
    if not graph:
        raise NotFoundException("Graph not found")

    # 检查权限
    if not current_user.is_superuser:
        if graph.user_id != current_user.id:
            if graph.workspace_id:
                has_access = await check_workspace_access(
                    db, graph.workspace_id, current_user, WorkspaceMemberRole.viewer
                )
                if not has_access:
                    raise ForbiddenException("No access to graph")
            else:
                raise ForbiddenException("No access to graph")

    # 获取节点和边
    nodes_result = await db.execute(
        select(GraphNode).where(GraphNode.graph_id == graph_id).order_by(GraphNode.position_x)
    )
    nodes = nodes_result.scalars().all()

    edges_result = await db.execute(select(GraphEdge).where(GraphEdge.graph_id == graph_id))
    edges = edges_result.scalars().all()

    # 验证变量
    tracker = StateVariableTracker(list(nodes), list(edges))
    errors = tracker.validate_variable_usage(str(node_id), expression)

    # 获取使用的变量
    used_vars = tracker._extract_variables_from_expression(expression)
    available_vars = tracker.get_available_variables_for_node(str(node_id))
    available_var_names = {v["name"] for v in available_vars}

    variables_info = []
    for var_name, var_path in used_vars.items():
        variables_info.append(
            {
                "name": var_name,
                "path": var_path,
                "available": var_name in available_var_names or any(v["path"] == var_path for v in available_vars),
            }
        )

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "variables": variables_info,
    }
