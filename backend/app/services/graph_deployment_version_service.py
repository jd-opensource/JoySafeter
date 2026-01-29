"""
Graph 部署版本 Service
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import ForbiddenException, NotFoundException
from app.models.auth import AuthUser
from app.models.graph import AgentGraph
from app.models.graph_deployment_version import GraphDeploymentVersion
from app.models.workspace import WorkspaceMemberRole
from app.repositories.auth_user import AuthUserRepository
from app.repositories.graph import GraphEdgeRepository, GraphNodeRepository, GraphRepository
from app.repositories.graph_deployment_version import GraphDeploymentVersionRepository
from app.schemas.graph_deployment_version import (
    GraphDeploymentVersionListResponse,
    GraphDeploymentVersionResponseCamel,
    GraphDeploymentVersionStateResponse,
    GraphDeployResponse,
    GraphRevertResponse,
)

from .base import BaseService
from .workspace_permission import check_workspace_access


class GraphDeploymentVersionService(BaseService):
    """Graph 部署版本 Service"""

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.version_repo = GraphDeploymentVersionRepository(db)
        self.graph_repo = GraphRepository(db)
        self.node_repo = GraphNodeRepository(db)
        self.edge_repo = GraphEdgeRepository(db)
        self.user_repo = AuthUserRepository(db)

    async def _ensure_access(
        self,
        graph: AgentGraph,
        current_user: AuthUser,
        required_role: WorkspaceMemberRole = WorkspaceMemberRole.viewer,
    ) -> None:
        """确保用户有访问图的权限"""
        if current_user.is_superuser:
            return
        if graph.user_id == current_user.id:
            return
        if graph.workspace_id:
            has_access = await check_workspace_access(
                self.db,
                graph.workspace_id,
                current_user,
                required_role,
            )
            if has_access:
                return
        raise ForbiddenException("No access to graph")

    async def _ensure_can_deploy(self, graph: AgentGraph, current_user: AuthUser) -> None:
        """确保用户可以部署"""
        if current_user.is_superuser:
            return
        if graph.user_id == current_user.id:
            return
        if graph.workspace_id:
            has_access = await check_workspace_access(
                self.db,
                graph.workspace_id,
                current_user,
                WorkspaceMemberRole.admin,
            )
            if has_access:
                return
        raise ForbiddenException("Only graph owner or workspace admin can deploy")

    def _normalize_graph_state(self, nodes: List, edges: List, variables: Dict[str, Any]) -> Dict[str, Any]:
        """规范化图状态 - 存储到 deployment_version.state

        重要：需要深拷贝 node.data，否则 SQLAlchemy 代理对象可能导致序列化问题。
        同时确保 config 中包含所有必要的配置（如 model、temp 等），
        这样回滚时能完整恢复。
        """
        import copy

        normalized_nodes = {}
        for node in nodes:
            node_id = str(node.id)

            # 深拷贝 data，避免 SQLAlchemy 代理对象序列化问题
            node_data = copy.deepcopy(dict(node.data)) if node.data else {}

            # 确保 config 存在
            if "config" not in node_data:
                node_data["config"] = {}

            config = node_data.get("config", {})
            if isinstance(config, dict):
                # 同步数据库字段到 config（确保回滚时能恢复）
                # prompt -> systemPrompt
                if node.prompt and (not config.get("systemPrompt")):
                    config["systemPrompt"] = node.prompt

                # tools
                if node.tools and (not config.get("tools")):
                    config["tools"] = copy.deepcopy(dict(node.tools)) if node.tools else {}

                node_data["config"] = config

            normalized_nodes[node_id] = {
                "id": node_id,
                "type": node.type,
                "tools": copy.deepcopy(dict(node.tools)) if node.tools else {},
                "memory": copy.deepcopy(dict(node.memory)) if node.memory else {},
                "prompt": node.prompt or "",
                "position": {
                    "x": float(node.position_x) if node.position_x else 0,
                    "y": float(node.position_y) if node.position_y else 0,
                },
                "position_absolute": {
                    "x": float(node.position_absolute_x) if node.position_absolute_x else None,
                    "y": float(node.position_absolute_y) if node.position_absolute_y else None,
                },
                "width": float(node.width) if node.width else 0,
                "height": float(node.height) if node.height else 0,
                "data": node_data,
            }

        normalized_edges = []
        for edge in edges:
            normalized_edges.append(
                {
                    "id": str(edge.id),
                    "source": str(edge.source_node_id),
                    "target": str(edge.target_node_id),
                }
            )

        return {
            "nodes": normalized_nodes,
            "edges": normalized_edges,
            "variables": variables,
            "lastSaved": int(datetime.now(timezone.utc).timestamp() * 1000),
        }

    def _compute_state_hash(self, state: Dict[str, Any]) -> str:
        """计算状态的 hash 值，用于快速比较"""
        import hashlib

        # 排除 lastSaved 字段，因为它每次都不同
        state_copy = {k: v for k, v in state.items() if k != "lastSaved"}
        state_json = json.dumps(state_copy, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(state_json.encode()).hexdigest()[:16]

    def _has_graph_changed(self, current_state: Dict[str, Any], deployed_state: Dict[str, Any]) -> bool:
        """检查图是否有变化（使用 hash 快速比较）"""
        current_hash = self._compute_state_hash(current_state)
        deployed_hash = self._compute_state_hash(deployed_state)
        return current_hash != deployed_hash

    async def deploy(
        self, graph_id: uuid.UUID, current_user: AuthUser, name: Optional[str] = None
    ) -> GraphDeployResponse:
        """部署图"""
        graph = await self.graph_repo.get(graph_id)
        if not graph:
            raise NotFoundException("Graph not found")

        await self._ensure_can_deploy(graph, current_user)

        nodes = await self.node_repo.list_by_graph(graph_id)
        edges = await self.edge_repo.list_by_graph(graph_id)

        current_state = self._normalize_graph_state(nodes, edges, graph.variables)
        active_version = await self.version_repo.get_active_version(graph_id)

        # 检查是否有变化
        has_changes = True
        if active_version:
            has_changes = self._has_graph_changed(current_state, active_version.state)

        # 如果没有变化且已部署，返回当前激活版本信息
        if not has_changes and graph.is_deployed and active_version:
            return GraphDeployResponse(
                success=True,
                message=f"No changes detected, current version is v{active_version.version}",
                version=active_version.version,
                isActive=active_version.is_active,
                needsRedeployment=False,
            )

        # 有变化或首次部署，创建新版本
        new_version = await self.version_repo.create_version(
            graph_id=graph_id,
            state=current_state,
            created_by=str(current_user.id),
            name=name,
        )

        now = datetime.now(timezone.utc)
        await self.graph_repo.update(
            graph_id,
            {
                "is_deployed": True,
                "deployed_at": now,
            },
        )

        await self.db.commit()

        return GraphDeployResponse(
            success=True,
            message=f"Deployed as version {new_version.version}",
            version=new_version.version,
            isActive=new_version.is_active,
            needsRedeployment=False,
        )

    async def undeploy(self, graph_id: uuid.UUID, current_user: AuthUser) -> Dict[str, Any]:
        """取消部署"""
        graph = await self.graph_repo.get(graph_id)
        if not graph:
            raise NotFoundException("Graph not found")

        await self._ensure_can_deploy(graph, current_user)

        await self.graph_repo.update(
            graph_id,
            {
                "is_deployed": False,
                "deployed_at": None,
            },
        )

        await self.db.commit()

        return {
            "isDeployed": False,
            "deployedAt": None,
        }

    async def get_deployment_status(self, graph_id: uuid.UUID, current_user: AuthUser) -> Dict[str, Any]:
        """获取部署状态"""
        graph = await self.graph_repo.get(graph_id)
        if not graph:
            raise NotFoundException("Graph not found")

        await self._ensure_access(graph, current_user)

        active_version = await self.version_repo.get_active_version(graph_id)

        nodes = await self.node_repo.list_by_graph(graph_id)
        edges = await self.edge_repo.list_by_graph(graph_id)
        current_state = self._normalize_graph_state(nodes, edges, graph.variables)

        needs_redeployment = False
        if active_version:
            needs_redeployment = self._has_graph_changed(current_state, active_version.state)
        else:
            needs_redeployment = True

        return {
            "isDeployed": graph.is_deployed,
            "deployedAt": graph.deployed_at.isoformat() if graph.deployed_at else None,
            "deployment": self._to_response_camel(active_version) if active_version else None,
            "needsRedeployment": needs_redeployment,
        }

    async def list_versions(
        self,
        graph_id: uuid.UUID,
        current_user: AuthUser,
        page: int = 1,
        page_size: int = 10,
    ) -> GraphDeploymentVersionListResponse:
        """获取所有版本（分页）"""
        graph = await self.graph_repo.get(graph_id)
        if not graph:
            raise NotFoundException("Graph not found")

        await self._ensure_access(graph, current_user)

        versions, total = await self.version_repo.list_by_graph_paginated(graph_id, page=page, page_size=page_size)

        # 批量获取用户名
        user_ids = list(set(v.created_by for v in versions if v.created_by))
        user_names: Dict[str, str] = {}
        for user_id in user_ids:
            if user_id:
                import uuid as uuid_lib

                try:
                    user_uuid = uuid_lib.UUID(user_id) if isinstance(user_id, str) else user_id
                    user = await self.user_repo.get(user_uuid)
                    if user:
                        user_names[user_id] = user.name
                except (ValueError, TypeError):
                    pass

        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 1

        return GraphDeploymentVersionListResponse(
            versions=[
                self._to_response_camel(v, user_names.get(v.created_by) if v.created_by else None) for v in versions
            ],
            total=total,
            page=page,
            pageSize=page_size,
            totalPages=total_pages,
        )

    async def get_version(
        self, graph_id: uuid.UUID, version: int, current_user: AuthUser
    ) -> GraphDeploymentVersionResponseCamel:
        """获取特定版本"""
        graph = await self.graph_repo.get(graph_id)
        if not graph:
            raise NotFoundException("Graph not found")

        await self._ensure_access(graph, current_user)

        deployment_version = await self.version_repo.get_by_graph_and_version(graph_id, version)
        if not deployment_version:
            raise NotFoundException("Deployment version not found")

        return self._to_response_camel(deployment_version)

    async def get_version_state(
        self, graph_id: uuid.UUID, version: int, current_user: AuthUser
    ) -> GraphDeploymentVersionStateResponse:
        """获取特定版本的完整状态（包含 nodes, edges 等用于预览）"""
        import copy

        graph = await self.graph_repo.get(graph_id)
        if not graph:
            raise NotFoundException("Graph not found")

        await self._ensure_access(graph, current_user)

        deployment_version = await self.version_repo.get_by_graph_and_version(graph_id, version)
        if not deployment_version:
            raise NotFoundException("Deployment version not found")

        # 深拷贝状态，转换为前端期望的格式
        state = copy.deepcopy(deployment_version.state) if deployment_version.state else {}

        # 将 state 中的 nodes 转换为前端格式（ReactFlow 格式）
        frontend_nodes = []
        nodes_data = state.get("nodes", {})
        for node_id, node_data in nodes_data.items():
            position = node_data.get("position", {"x": 0, "y": 0})
            position_absolute = node_data.get("position_absolute", position)

            frontend_node = {
                "id": node_id,
                "type": "custom",  # ReactFlow 使用 custom 类型
                "position": position,
                "positionAbsolute": {
                    "x": position_absolute.get("x") if position_absolute else position.get("x", 0),
                    "y": position_absolute.get("y") if position_absolute else position.get("y", 0),
                },
                "width": node_data.get("width", 0),
                "height": node_data.get("height", 0),
                "data": node_data.get("data", {}),
                "selected": False,
                "dragging": False,
            }
            frontend_nodes.append(frontend_node)

        # 转换 edges 格式
        frontend_edges = []
        edges_data = state.get("edges", [])
        for edge_data in edges_data:
            frontend_edge = {
                "id": edge_data.get("id", f"edge-{edge_data.get('source')}-{edge_data.get('target')}"),
                "source": edge_data.get("source"),
                "target": edge_data.get("target"),
                "animated": True,
                "style": {"stroke": "#cbd5e1", "strokeWidth": 1.5},
            }
            frontend_edges.append(frontend_edge)

        frontend_state = {
            "nodes": frontend_nodes,
            "edges": frontend_edges,
            "variables": state.get("variables", {}),
        }

        return GraphDeploymentVersionStateResponse(
            id=str(deployment_version.id),
            version=deployment_version.version,
            name=deployment_version.name,
            isActive=deployment_version.is_active,
            createdAt=deployment_version.created_at.isoformat(),
            createdBy=deployment_version.created_by,
            state=frontend_state,
        )

    async def activate_version(
        self, graph_id: uuid.UUID, version: int, current_user: AuthUser
    ) -> GraphDeploymentVersionResponseCamel:
        """激活版本"""
        graph = await self.graph_repo.get(graph_id)
        if not graph:
            raise NotFoundException("Graph not found")

        await self._ensure_can_deploy(graph, current_user)

        activated_version = await self.version_repo.activate_version(graph_id, version)
        if not activated_version:
            raise NotFoundException("Deployment version not found")

        await self.graph_repo.update(
            graph_id,
            {
                "deployed_at": datetime.now(timezone.utc),
            },
        )

        await self.db.commit()

        return self._to_response_camel(activated_version)

    async def revert_to_version(self, graph_id: uuid.UUID, version: int, current_user: AuthUser) -> GraphRevertResponse:
        """回滚到指定版本

        从部署版本中恢复完整的节点状态，包括 data.config 中的所有配置。
        """
        import copy

        graph = await self.graph_repo.get(graph_id)
        if not graph:
            raise NotFoundException("Graph not found")

        await self._ensure_can_deploy(graph, current_user)

        target_version = await self.version_repo.get_by_graph_and_version(graph_id, version)
        if not target_version:
            raise NotFoundException("Deployment version not found")

        # 恢复 nodes/edges 数据
        state = target_version.state
        if not state or "nodes" not in state:
            raise NotFoundException("Version state is invalid")

        # 1. 删除现有的所有 nodes 和 edges
        await self.node_repo.delete_by_graph(graph_id)
        await self.edge_repo.delete_by_graph(graph_id)

        # 2. 恢复 nodes（使用原始 ID）
        from app.models.graph import GraphNode

        nodes_data = state["nodes"]
        for node_id, node_data in nodes_data.items():
            position = node_data.get("position", {})
            position_absolute = node_data.get("position_absolute")

            # 深拷贝 data，确保数据完整性
            restored_data = copy.deepcopy(node_data.get("data", {}))

            # 从 data.config 中提取配置，用于填充数据库字段
            config = restored_data.get("config", {}) if isinstance(restored_data, dict) else {}

            # 优先使用 config 中的值，否则使用顶层的值
            prompt = ""
            if isinstance(config, dict) and config.get("systemPrompt"):
                prompt = config["systemPrompt"]
            elif node_data.get("prompt"):
                prompt = node_data["prompt"]

            # tools: 优先使用 config 中的，否则使用顶层的
            tools = {}
            if isinstance(config, dict) and config.get("tools"):
                tools = copy.deepcopy(config["tools"])
            elif node_data.get("tools"):
                tools = copy.deepcopy(node_data["tools"])

            node = GraphNode(
                id=uuid.UUID(node_id),  # 使用原始 ID
                graph_id=graph_id,
                type=node_data["type"],
                tools=tools,
                memory=copy.deepcopy(node_data.get("memory", {})),
                prompt=prompt,
                position_x=position.get("x", 0) if position else 0,
                position_y=position.get("y", 0) if position else 0,
                position_absolute_x=position_absolute.get("x") if position_absolute else None,
                position_absolute_y=position_absolute.get("y") if position_absolute else None,
                width=node_data.get("width", 0),
                height=node_data.get("height", 0),
                data=restored_data,  # 完整的 data（包含 config）
            )
            self.db.add(node)

        # 先 flush 确保 nodes 被创建
        await self.db.flush()

        # 3. 恢复 edges
        from app.models.graph import GraphEdge

        edges_data = state.get("edges", [])
        for edge_data in edges_data:
            edge = GraphEdge(
                id=uuid.UUID(edge_data["id"]),  # 使用原始 ID
                graph_id=graph_id,
                source_node_id=uuid.UUID(edge_data["source"]),
                target_node_id=uuid.UUID(edge_data["target"]),
            )
            self.db.add(edge)

        # 4. 更新 variables
        await self.graph_repo.update(
            graph_id,
            {
                "variables": state.get("variables", {}),
            },
        )

        # 5. 激活版本
        await self.version_repo.activate_version(graph_id, version)

        await self.graph_repo.update(
            graph_id,
            {
                "deployed_at": datetime.now(timezone.utc),
            },
        )

        await self.db.commit()

        return GraphRevertResponse(
            success=True,
            message=f"Reverted to version {version}",
            version=version,
            is_active=True,
        )

    async def rename_version(
        self, graph_id: uuid.UUID, version: int, name: str, current_user: AuthUser
    ) -> GraphDeploymentVersionResponseCamel:
        """重命名版本"""
        graph = await self.graph_repo.get(graph_id)
        if not graph:
            raise NotFoundException("Graph not found")

        await self._ensure_access(graph, current_user)

        renamed_version = await self.version_repo.rename_version(graph_id, version, name)
        if not renamed_version:
            raise NotFoundException("Deployment version not found")

        await self.db.commit()

        return self._to_response_camel(renamed_version)

    async def delete_version(self, graph_id: uuid.UUID, version: int, current_user: AuthUser) -> Dict[str, Any]:
        """删除版本"""
        graph = await self.graph_repo.get(graph_id)
        if not graph:
            raise NotFoundException("Graph not found")

        await self._ensure_can_deploy(graph, current_user)

        target_version = await self.version_repo.get_by_graph_and_version(graph_id, version)
        if not target_version:
            raise NotFoundException("Deployment version not found")

        # 不允许删除当前激活的版本
        if target_version.is_active:
            raise ForbiddenException("Cannot delete the active deployment version")

        await self.version_repo.delete_version(graph_id, version)
        await self.db.commit()

        return {
            "success": True,
            "message": f"Version {version} deleted successfully",
        }

    def _to_response_camel(
        self, version: GraphDeploymentVersion, created_by_name: Optional[str] = None
    ) -> GraphDeploymentVersionResponseCamel:
        """转换为 camelCase 响应格式"""
        return GraphDeploymentVersionResponseCamel(
            id=str(version.id),
            version=version.version,
            name=version.name,
            isActive=version.is_active,
            createdAt=version.created_at.isoformat(),
            createdBy=version.created_by,
            createdByName=created_by_name,
        )
