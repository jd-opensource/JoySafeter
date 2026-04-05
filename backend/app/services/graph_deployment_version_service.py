"""
Graph deployment version service.
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
    """Graph deployment version service."""

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
        """Ensure the user has permission to access the graph."""
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
        """Ensure the user can deploy."""
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
        """Normalize graph state — store into deployment_version.state.

        Important: deep-copy node.data to avoid serialization issues with SQLAlchemy proxy objects.
        Also ensure config contains all necessary settings (e.g. model, temp, etc.)
        so that a revert can fully restore the state.
        """
        import copy

        normalized_nodes = {}
        for node in nodes:
            node_id = str(node.id)

            # deep-copy data to avoid SQLAlchemy proxy object serialization issues
            node_data = copy.deepcopy(dict(node.data)) if node.data else {}

            # ensure config exists
            if "config" not in node_data:
                node_data["config"] = {}

            config = node_data.get("config", {})
            if not isinstance(config, dict):
                config = {}
            node_data["config"] = config

            normalized_nodes[node_id] = {
                "id": node_id,
                "type": node.type,
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
        """Compute a hash of the state for quick comparison."""
        import hashlib

        # exclude lastSaved field since it differs every time
        state_copy = {k: v for k, v in state.items() if k != "lastSaved"}
        state_json = json.dumps(state_copy, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(state_json.encode()).hexdigest()[:16]

    def _has_graph_changed(self, current_state: Dict[str, Any], deployed_state: Dict[str, Any]) -> bool:
        """Check whether the graph has changed (using hash for quick comparison)."""
        current_hash = self._compute_state_hash(current_state)
        deployed_hash = self._compute_state_hash(deployed_state)
        return current_hash != deployed_hash

    async def deploy(
        self, graph_id: uuid.UUID, current_user: AuthUser, name: Optional[str] = None
    ) -> GraphDeployResponse:
        """Deploy a graph."""
        graph = await self.graph_repo.get(graph_id)
        if not graph:
            raise NotFoundException("Graph not found")

        await self._ensure_can_deploy(graph, current_user)

        nodes = await self.node_repo.list_by_graph(graph_id)
        edges = await self.edge_repo.list_by_graph(graph_id)

        current_state = self._normalize_graph_state(nodes, edges, graph.variables)
        active_version = await self.version_repo.get_active_version(graph_id)

        # check if there are changes
        has_changes = True
        if active_version:
            has_changes = self._has_graph_changed(current_state, active_version.state)

        # if no changes and already deployed, return current active version info
        if not has_changes and graph.is_deployed and active_version:
            return GraphDeployResponse(
                success=True,
                message=f"No changes detected, current version is v{active_version.version}",
                version=active_version.version,
                isActive=active_version.is_active,
                needsRedeployment=False,
            )

        # changes detected or first deploy, create a new version
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
        """Undeploy."""
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
        """Get deployment status."""
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
        """Get all versions (paginated)."""
        graph = await self.graph_repo.get(graph_id)
        if not graph:
            raise NotFoundException("Graph not found")

        await self._ensure_access(graph, current_user)

        versions, total = await self.version_repo.list_by_graph_paginated(graph_id, page=page, page_size=page_size)

        # batch-fetch usernames
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
        """Get a specific version."""
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
        """Get the full state of a specific version (including nodes, edges, etc. for preview)."""
        import copy

        graph = await self.graph_repo.get(graph_id)
        if not graph:
            raise NotFoundException("Graph not found")

        await self._ensure_access(graph, current_user)

        deployment_version = await self.version_repo.get_by_graph_and_version(graph_id, version)
        if not deployment_version:
            raise NotFoundException("Deployment version not found")

        # deep-copy state, convert to frontend-expected format
        state = copy.deepcopy(deployment_version.state) if deployment_version.state else {}

        # convert state nodes to frontend format (ReactFlow format)
        frontend_nodes = []
        nodes_data = state.get("nodes", {})
        for node_id, node_data in nodes_data.items():
            position = node_data.get("position", {"x": 0, "y": 0})
            position_absolute = node_data.get("position_absolute", position)

            frontend_node = {
                "id": node_id,
                "type": "custom",  # ReactFlow uses custom type
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

        # convert edges format
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
        """Activate a version."""
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
        """Revert to a specific version.

        Restore the full node state from the deployment version, including all settings in data.config.
        """
        import copy

        graph = await self.graph_repo.get(graph_id)
        if not graph:
            raise NotFoundException("Graph not found")

        await self._ensure_can_deploy(graph, current_user)

        target_version = await self.version_repo.get_by_graph_and_version(graph_id, version)
        if not target_version:
            raise NotFoundException("Deployment version not found")

        # restore nodes/edges data
        state = target_version.state
        if not state or "nodes" not in state:
            raise NotFoundException("Version state is invalid")

        # 1. delete all existing nodes and edges
        await self.node_repo.delete_by_graph(graph_id)
        await self.edge_repo.delete_by_graph(graph_id)

        # 2. restore nodes (using original IDs)
        from app.models.graph import GraphNode

        nodes_data = state["nodes"]
        for node_id, node_data in nodes_data.items():
            position = node_data.get("position", {})
            position_absolute = node_data.get("position_absolute")

            # deep-copy data to ensure data integrity
            restored_data = copy.deepcopy(node_data.get("data", {}))

            node = GraphNode(
                id=uuid.UUID(node_id),  # use original ID
                graph_id=graph_id,
                type=node_data["type"],
                position_x=position.get("x", 0) if position else 0,
                position_y=position.get("y", 0) if position else 0,
                position_absolute_x=position_absolute.get("x") if position_absolute else None,
                position_absolute_y=position_absolute.get("y") if position_absolute else None,
                width=node_data.get("width", 0),
                height=node_data.get("height", 0),
                data=restored_data,  # full data (including config)
            )
            self.db.add(node)

        # flush first to ensure nodes are created
        await self.db.flush()

        # 3. restore edges
        from app.models.graph import GraphEdge

        edges_data = state.get("edges", [])
        for edge_data in edges_data:
            edge = GraphEdge(
                id=uuid.UUID(edge_data["id"]),  # use original ID
                graph_id=graph_id,
                source_node_id=uuid.UUID(edge_data["source"]),
                target_node_id=uuid.UUID(edge_data["target"]),
            )
            self.db.add(edge)

        # 4. update variables
        await self.graph_repo.update(
            graph_id,
            {
                "variables": state.get("variables", {}),
            },
        )

        # 5. activate version
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
        """Rename a version."""
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
        """Delete a version."""
        graph = await self.graph_repo.get(graph_id)
        if not graph:
            raise NotFoundException("Graph not found")

        await self._ensure_can_deploy(graph, current_user)

        target_version = await self.version_repo.get_by_graph_and_version(graph_id, version)
        if not target_version:
            raise NotFoundException("Deployment version not found")

        # cannot delete the currently active version
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
        """Convert to camelCase response format."""
        return GraphDeploymentVersionResponseCamel(
            id=str(version.id),
            version=version.version,
            name=version.name,
            isActive=version.is_active,
            createdAt=version.created_at.isoformat(),
            createdBy=version.created_by,
            createdByName=created_by_name,
        )
