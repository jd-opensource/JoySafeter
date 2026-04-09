"""
Graph service.
"""

import hashlib
import json
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from langgraph.graph.state import CompiledStateGraph
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.core.graph.deep_agents.builder import build_deep_agents_graph
from app.core.graph.node_secrets import (
    hydrate_nodes_a2a_secrets,
    prepare_node_data_for_save,
    store_a2a_auth_headers,
)
from app.core.graph.runtime_prompt_template import build_runtime_prompt_context
from app.models.auth import AuthUser
from app.models.graph import AgentGraph, GraphEdge, GraphNode, GraphNodeSecret
from app.models.workspace import WorkspaceMemberRole
from app.repositories.graph import GraphEdgeRepository, GraphNodeRepository, GraphRepository

from .base import BaseService
from .model_service import ModelService
from .workspace_permission import check_workspace_access

# In-memory compile cache: (graph_id, updated_at_iso, runtime_context_fingerprint) -> (compiled_graph, cached_at_ts).
_compile_cache: Dict[Tuple[str, str, str], Tuple[CompiledStateGraph, float]] = {}
_COMPILE_CACHE_TTL = 300.0


def _invalidate_compile_cache(graph_id: uuid.UUID) -> None:
    """Remove any cache entry for this graph (call after save)."""
    to_drop = [k for k in _compile_cache if k[0] == str(graph_id)]
    for k in to_drop:
        _compile_cache.pop(k, None)


def _build_runtime_prompt_context_for_cache(
    graph: AgentGraph,
    *,
    user_id: Optional[Any],
    thread_id: Optional[str],
) -> Dict[str, Any]:
    """Build effective runtime prompt context used by GraphBuilder for cache-keying."""
    return build_runtime_prompt_context(graph, user_id=user_id, thread_id=thread_id)


def _normalize_runtime_prompt_context_for_cache(value: Any) -> Any:
    """Normalize runtime context into a JSON-serializable deterministic structure."""
    if isinstance(value, dict):
        return {
            str(key): _normalize_runtime_prompt_context_for_cache(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, list):
        return [_normalize_runtime_prompt_context_for_cache(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_runtime_prompt_context_for_cache(item) for item in value]
    if isinstance(value, set):
        normalized_items = [_normalize_runtime_prompt_context_for_cache(item) for item in value]
        return sorted(
            normalized_items,
            key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
        )
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _build_runtime_aware_compile_cache_key(
    graph: AgentGraph,
    *,
    user_id: Optional[Any],
    thread_id: Optional[str],
) -> Tuple[str, str, str]:
    """Build compile cache key that includes effective runtime prompt context fingerprint."""
    runtime_context = _build_runtime_prompt_context_for_cache(graph, user_id=user_id, thread_id=thread_id)
    normalized_context = _normalize_runtime_prompt_context_for_cache(runtime_context)
    serialized_context = json.dumps(normalized_context, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    context_fingerprint = hashlib.sha256(serialized_context.encode("utf-8")).hexdigest()
    updated_at_iso = graph.updated_at.isoformat() if graph.updated_at else ""
    return (str(graph.id), updated_at_iso, context_fingerprint)


class GraphService(BaseService):
    """Graph Service"""

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.graph_repo = GraphRepository(db)
        self.node_repo = GraphNodeRepository(db)
        self.edge_repo = GraphEdgeRepository(db)

    async def _ensure_access(
        self,
        graph: AgentGraph,
        current_user: AuthUser,
        required_role: WorkspaceMemberRole = WorkspaceMemberRole.viewer,
    ) -> None:
        """
        Ensure the user has permission to access the graph.

        Args:
            graph: the graph to access
            current_user: current user
            required_role: minimum required workspace role (only applies to workspace graphs)

        Raises:
            ForbiddenException: if the user has no access
        """
        # superuser has all permissions
        if current_user.is_superuser:
            return

        # if the user owns the graph, allow directly
        if graph.user_id == current_user.id:
            return

        # if it's a workspace graph, check workspace permissions
        if graph.workspace_id:
            has_access = await check_workspace_access(
                self.db,
                graph.workspace_id,
                current_user,
                required_role,
            )
            if has_access:
                return

        # no permission
        raise ForbiddenException("No access to graph")

    async def _create_graph_with_id(
        self,
        graph_id: uuid.UUID,
        name: str,
        user_id: uuid.UUID,
        workspace_id: Optional[uuid.UUID] = None,
        description: Optional[str] = None,
    ) -> AgentGraph:
        """
        Create a graph with a specified ID (for upsert scenarios).

        Args:
            graph_id: specified graph ID
            name: graph name
            user_id: user ID
            workspace_id: workspace ID (optional)
            description: description (optional)

        Returns:
            The created graph object
        """
        graph_data = {
            "id": graph_id,
            "name": name,
            "user_id": user_id,
            "workspace_id": workspace_id,
            "description": description,
            "is_deployed": False,
            "variables": {},
        }
        return await self.graph_repo.create(graph_data)

    async def create_graph(
        self,
        name: str,
        user_id: str,
        workspace_id: Optional[uuid.UUID] = None,
        folder_id: Optional[uuid.UUID] = None,
        parent_id: Optional[uuid.UUID] = None,
        description: Optional[str] = None,
        color: Optional[str] = None,
        variables: Optional[Dict[str, Any]] = None,
    ) -> AgentGraph:
        """
        Create a new graph.

        Args:
            name: graph name
            user_id: user ID
            workspace_id: workspace ID (optional)
            folder_id: folder ID (optional)
            parent_id: parent graph ID (optional)
            description: description (optional)
            color: color (optional)
            variables: variables (optional)

        Returns:
            The created graph object

        Raises:
            NotFoundException: if the parent graph does not exist
        """
        # validate parent_id exists
        if parent_id:
            parent_graph = await self.graph_repo.get(parent_id)
            if not parent_graph:
                raise NotFoundException(f"Parent graph with id {parent_id} not found")

        # validate folder_id exists and belongs to the specified workspace
        if folder_id:
            from app.repositories.workspace_folder import WorkflowFolderRepository

            folder_repo = WorkflowFolderRepository(self.db)
            folder = await folder_repo.get(folder_id)
            if not folder:
                raise NotFoundException(f"Folder with id {folder_id} not found")
            # if workspace_id is specified, ensure the folder belongs to that workspace
            if workspace_id and folder.workspace_id != workspace_id:
                raise BadRequestException(f"Folder {folder_id} does not belong to workspace {workspace_id}")
            # if workspace_id is not specified, derive it from the folder
            if not workspace_id:
                workspace_id = folder.workspace_id

        graph_data = {
            "name": name,
            "user_id": user_id,
            "workspace_id": workspace_id,
            "folder_id": folder_id,
            "parent_id": parent_id,
            "description": description,
            "color": color,
            "is_deployed": False,
            "variables": variables or {},
        }
        return await self.graph_repo.create(graph_data)

    async def save_graph_state(
        self,
        graph_id: uuid.UUID,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        viewport: Optional[Dict[str, Any]] = None,
        variables: Optional[Dict[str, Any]] = None,
        current_user: Optional[AuthUser] = None,
        # upsert params
        name: Optional[str] = None,
        workspace_id: Optional[uuid.UUID] = None,
    ) -> Dict[str, Any]:
        """
        Save the complete graph state (nodes and edges) — supports upsert mode.

        If the graph does not exist and a name parameter is provided, automatically create a new graph.

        Frontend format:
        {
            "nodes": [...],
            "edges": [...],
            "viewport": {...},
            ...
        }
        """
        # use a transaction to ensure atomicity: all operations succeed or all fail
        # check if already in a transaction to avoid starting a duplicate
        if self.db.in_transaction():
            # already in a transaction, execute directly
            return await self._save_graph_state_internal(
                graph_id=graph_id,
                nodes=nodes,
                edges=edges,
                viewport=viewport,
                variables=variables,
                current_user=current_user,
                name=name,
                workspace_id=workspace_id,
            )
        else:
            # not in a transaction, start a new one
            async with self.db.begin():
                return await self._save_graph_state_internal(
                    graph_id=graph_id,
                    nodes=nodes,
                    edges=edges,
                    viewport=viewport,
                    variables=variables,
                    current_user=current_user,
                    name=name,
                    workspace_id=workspace_id,
                )

    async def _save_graph_state_internal(
        self,
        graph_id: uuid.UUID,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        viewport: Optional[Dict[str, Any]] = None,
        variables: Optional[Dict[str, Any]] = None,
        current_user: Optional[AuthUser] = None,
        # upsert params
        name: Optional[str] = None,
        workspace_id: Optional[uuid.UUID] = None,
    ) -> Dict[str, Any]:
        """Internal method: execute the actual save graph state logic."""
        # get the graph
        graph = await self.graph_repo.get(graph_id)
        if graph:
            # permission check: ensure user has write access to the existing graph
            if current_user:
                await self._ensure_access(graph, current_user, WorkspaceMemberRole.member)
        if not graph:
            # upsert mode: if the graph does not exist, auto-create a new graph
            if current_user:
                # if no workspace_id provided, find the user's default workspace
                if not workspace_id:
                    from app.repositories.workspace import WorkspaceRepository

                    workspace_repo = WorkspaceRepository(self.db)
                    workspace = await workspace_repo.get_by_name_and_owner(
                        name="Default Workspace",
                        owner_id=current_user.id,
                    )
                    if workspace:
                        workspace_id = workspace.id

                # use default name if none provided
                graph_name = name or "Untitled Graph"

                import uuid as uuid_lib

                user_uuid = uuid_lib.UUID(current_user.id) if isinstance(current_user.id, str) else current_user.id
                graph = await self._create_graph_with_id(
                    graph_id=graph_id,
                    name=graph_name,
                    user_id=user_uuid,
                    workspace_id=workspace_id,
                )
            else:
                raise NotFoundException("Graph not found")

        # load existing nodes, build frontend-ID-to-database-ID mapping
        existing_nodes = await self.node_repo.list_by_graph(graph_id)
        existing_node_map: Dict[str, GraphNode] = {}
        for node in existing_nodes:
            # frontend uses the database UUID string form as node ID
            frontend_id = str(node.id)
            existing_node_map[frontend_id] = node

        # create node mapping (frontend ID -> database UUID)
        node_id_map: Dict[str, uuid.UUID] = {}
        nodes_to_create: List[Dict[str, Any]] = []
        nodes_to_update: List[Tuple[uuid.UUID, Dict[str, Any]]] = []

        # save nodes
        for node_data in nodes:
            # convert frontend node format to database format
            node_id = node_data.get("id")
            if not node_id:
                continue

            # try to parse frontend ID as UUID; if successful and node exists, update; otherwise create new node
            db_node_id: uuid.UUID
            try:
                # try to parse frontend ID as UUID
                node_id_str = str(node_id)
                parsed_uuid = uuid.UUID(node_id_str)
                if str(parsed_uuid) in existing_node_map:
                    # node exists, update
                    db_node_id = parsed_uuid
                    nodes_to_update.append((db_node_id, node_data))
                else:
                    # UUID format but node does not exist, create new node
                    db_node_id = uuid.uuid4()
                    nodes_to_create.append(node_data)
            except (ValueError, AttributeError):
                # frontend ID is not UUID format (e.g. node_xxx), create new node
                db_node_id = uuid.uuid4()
                nodes_to_create.append(node_data)

            node_id_map[node_id] = db_node_id

        # delete nodes that no longer exist and all edges (edges will be recreated later)
        # build database UUID set to determine which nodes to delete
        # node_id_map values are database UUIDs, keys are frontend IDs
        existing_db_node_ids = set(node_id_map.values())
        # also include updated nodes (these are kept, should not be deleted)
        for db_node_id, _ in nodes_to_update:
            existing_db_node_ids.add(db_node_id)

        nodes_to_delete = [
            node.id for node_id_str, node in existing_node_map.items() if node.id not in existing_db_node_ids
        ]
        if nodes_to_delete:
            await self.node_repo.delete_by_ids(graph_id, nodes_to_delete)
            await self.edge_repo.delete_by_graph(graph_id)

        # create new nodes
        for node_data in nodes_to_create:
            node_id = node_data.get("id")
            if not node_id:
                continue
            db_node_id_raw = node_id_map.get(node_id)
            if not db_node_id_raw:
                continue
            new_db_node_id: uuid.UUID = db_node_id_raw

            position = node_data.get("position", {})
            position_absolute = node_data.get("positionAbsolute", position)
            data_payload = node_data.get("data", {}) or {}
            data_for_save, headers_to_store = prepare_node_data_for_save(data_payload)
            if headers_to_store:
                try:
                    secret_id = await store_a2a_auth_headers(self.db, graph_id, new_db_node_id, headers_to_store)
                    if "config" not in data_for_save:
                        data_for_save["config"] = {}
                    data_for_save["config"]["a2a_auth_headers"] = {"__secretRef": str(secret_id)}
                except Exception as e:
                    logger.warning(f"[GraphService] Failed to store a2a_auth_headers for node {new_db_node_id}: {e}")
            node_type = data_for_save.get("type") or node_data.get("type") or "agent"

            node_create_data = {
                "graph_id": graph_id,
                "id": new_db_node_id,
                "type": node_type,
                "position_x": float(position.get("x", 0)),
                "position_y": float(position.get("y", 0)),
                "position_absolute_x": float(position_absolute.get("x", position.get("x", 0))),
                "position_absolute_y": float(position_absolute.get("y", position.get("y", 0))),
                "width": float(node_data.get("width", 0)),
                "height": float(node_data.get("height", 0)),
                "data": data_for_save,
            }

            await self.node_repo.create(node_create_data)

        # update existing nodes
        for db_node_id, node_data in nodes_to_update:
            position = node_data.get("position", {})
            position_absolute = node_data.get("positionAbsolute", position)
            data_payload = node_data.get("data", {}) or {}
            data_for_save, headers_to_store = prepare_node_data_for_save(data_payload)
            if headers_to_store:
                try:
                    from sqlalchemy import delete

                    await self.db.execute(
                        delete(GraphNodeSecret).where(
                            GraphNodeSecret.graph_id == graph_id,
                            GraphNodeSecret.node_id == db_node_id,
                            GraphNodeSecret.key_slug == "a2a_auth_headers",
                        )
                    )
                    secret_id = await store_a2a_auth_headers(self.db, graph_id, db_node_id, headers_to_store)
                    if "config" not in data_for_save:
                        data_for_save["config"] = {}
                    data_for_save["config"]["a2a_auth_headers"] = {"__secretRef": str(secret_id)}
                except Exception as e:
                    logger.warning(f"[GraphService] Failed to store a2a_auth_headers for node {db_node_id}: {e}")
            node_type = data_for_save.get("type") or node_data.get("type") or "agent"

            update_data = {
                "type": node_type,
                "position_x": float(position.get("x", 0)),
                "position_y": float(position.get("y", 0)),
                "position_absolute_x": float(position_absolute.get("x", position.get("x", 0))),
                "position_absolute_y": float(position_absolute.get("y", position.get("y", 0))),
                "width": float(node_data.get("width", 0)),
                "height": float(node_data.get("height", 0)),
                "data": data_for_save,
            }

            await self.node_repo.update(db_node_id, update_data)

        # save edges (with dedup)
        saved_edges_count = 0
        skipped_edges_count = 0
        seen_edges: set[tuple[str, str]] = set()  # for dedup

        for edge_data in edges:
            source_id = edge_data.get("source")
            target_id = edge_data.get("target")

            if not source_id or not target_id:
                skipped_edges_count += 1
                continue

            # edge dedup: only save each source-target pair once
            edge_key = (source_id, target_id)
            if edge_key in seen_edges:
                skipped_edges_count += 1
                continue
            seen_edges.add(edge_key)

            # find the corresponding database node ID
            source_node_id = node_id_map.get(source_id)
            target_node_id = node_id_map.get(target_id)

            if not source_node_id or not target_node_id:
                skipped_edges_count += 1
                continue

            # extract edge data fields (including edge_type, route_key, source_handle_id, etc.)
            edge_data_payload = edge_data.get("data", {}) or {}

            edge_create_data = {
                "graph_id": graph_id,
                "source_node_id": source_node_id,
                "target_node_id": target_node_id,
                "data": edge_data_payload,  # save edge metadata (edge_type, route_key, etc.)
            }

            await self.edge_repo.create(edge_create_data)
            saved_edges_count += 1

        # update graph variables (save viewport and context variables metadata) and updated_at
        update_data = {}
        graph_variables = graph.variables or {}

        if viewport:
            graph_variables["viewport"] = viewport

        # if variables provided, merge into graph_variables
        if variables:
            # merge variables, preserving existing viewport and other fields
            for key, value in variables.items():
                graph_variables[key] = value

        if viewport or variables:
            update_data["variables"] = graph_variables

        # update graph updated_at (ensure list sorting is correct)
        # BaseModel uses the updated_at field; SQLAlchemy's onupdate auto-updates it
        # but to be safe, we explicitly trigger an update
        from app.utils.datetime import utc_now

        update_data["updated_at"] = utc_now()

        if update_data:
            await self.graph_repo.update(graph_id, update_data)

        _invalidate_compile_cache(graph_id)

        return {
            "graph_id": str(graph_id),
            "nodes_count": len(nodes),
            "edges_count": len(edges),
        }

    async def load_graph_state(
        self,
        graph_id: uuid.UUID,
        current_user: Optional[AuthUser] = None,
    ) -> Dict[str, Any]:
        """
        Load the complete graph state (nodes and edges).

        Return the format expected by the frontend:
        {
            "nodes": [...],
            "edges": [...],
            "viewport": {...},
            ...
        }
        """
        # get the graph
        graph = await self.graph_repo.get(graph_id, relations=["nodes", "edges"])
        if not graph:
            raise NotFoundException("Graph not found")

        # permission check
        if current_user:
            await self._ensure_access(graph, current_user, WorkspaceMemberRole.viewer)

        # load nodes and edges
        nodes = await self.node_repo.list_by_graph(graph_id)
        edges = await self.edge_repo.list_by_graph(graph_id)

        # build node mapping (database UUID -> frontend ID)
        node_id_map: Dict[uuid.UUID, str] = {}
        frontend_nodes = []

        for node in nodes:
            # generate frontend ID (use node ID string form)
            frontend_id = str(node.id)
            node_id_map[node.id] = frontend_id

            # build frontend node format
            # note: ReactFlow's type field should be "custom" (all nodes use the BuilderNode component)
            # the actual node type (e.g. "agent", "condition") is stored in data.type
            node_data = node.data or {}

            # ensure data.type exists (used to get colors etc. from nodeRegistry)
            # if node.data has no type, use the database node.type field
            if "type" not in node_data:
                node_data["type"] = node.type

            # restore position info: use saved position and positionAbsolute
            # if position_absolute_x/y don't exist (old data), fall back to position_x/y
            pos_x = float(node.position_x)
            pos_y = float(node.position_y)
            pos_abs_x = float(node.position_absolute_x) if node.position_absolute_x is not None else pos_x
            pos_abs_y = float(node.position_absolute_y) if node.position_absolute_y is not None else pos_y

            frontend_node: Dict[str, Any] = {
                "id": frontend_id,
                "type": "custom",  # ReactFlow node type, all nodes use BuilderNode
                "position": {
                    "x": pos_x,
                    "y": pos_y,
                },
                "positionAbsolute": {
                    "x": pos_abs_x,
                    "y": pos_abs_y,
                },
                "width": float(node.width),
                "height": float(node.height),
                "data": node_data,
                "selected": False,
                "dragging": False,
            }

            # ensure config field exists
            node_data_dict = frontend_node["data"] if isinstance(frontend_node["data"], dict) else {}
            if "config" not in node_data_dict:
                node_data_dict["config"] = {}
            # redact: if plaintext a2a_auth_headers remain, do not return to frontend
            a2a_headers = node_data_dict.get("config", {}).get("a2a_auth_headers")
            if isinstance(a2a_headers, dict) and "__secretRef" not in a2a_headers and a2a_headers:
                node_data_dict.setdefault("config", {})["a2a_auth_headers"] = {"__redacted": True}
            frontend_node["data"] = node_data_dict

            frontend_nodes.append(frontend_node)

        # build frontend edge format
        frontend_edges = []
        for edge in edges:
            source_id = node_id_map.get(edge.source_node_id)
            target_id = node_id_map.get(edge.target_node_id)

            if not source_id or not target_id:
                continue

            # restore edge data field from database
            edge_data = edge.data or {}
            edge_type = edge_data.get("edge_type", "normal")

            # set style and type based on edge_type
            if edge_type == "loop_back":
                edge_style = {
                    "stroke": "#9333ea",  # purple, matches frontend LoopBackEdge
                    "strokeWidth": 2.5,
                    "strokeDasharray": "5,5",
                }
                edge_type_for_reactflow = "loop_back"
            elif edge_type == "conditional":
                edge_style = {
                    "stroke": "#3b82f6",  # blue, matches frontend condition edge
                    "strokeWidth": 2,
                }
                edge_type_for_reactflow = "default"
            else:
                # normal or other types
                edge_style = {
                    "stroke": "#cbd5e1",  # matches frontend defaultEdgeOptions color
                    "strokeWidth": 1.5,
                }
                edge_type_for_reactflow = "default"

            # use default edge styles consistent with frontend (matches BuilderCanvas.tsx defaultEdgeOptions)
            frontend_edge = {
                "source": source_id,
                "target": target_id,
                "sourceHandle": None,
                "targetHandle": None,
                "type": edge_type_for_reactflow,  # set ReactFlow edge type
                "animated": True,
                "style": edge_style,
                "data": edge_data,  # restore edge metadata (edge_type, route_key, source_handle_id, etc.)
                "id": f"reactflow__edge-{source_id}-{target_id}",
            }
            frontend_edges.append(frontend_edge)

        # get viewport and variables
        viewport = graph.variables.get("viewport", {}) if graph.variables else {}
        variables = graph.variables or {}

        return {
            "nodes": frontend_nodes,
            "edges": frontend_edges,
            "viewport": viewport,
            "variables": variables,
        }

    async def get_graph_detail(
        self,
        graph_id: uuid.UUID,
        current_user: Optional[AuthUser] = None,
    ) -> Dict[str, Any]:
        """Get detailed graph information (including state)."""
        graph = await self.graph_repo.get(graph_id)
        if not graph:
            raise NotFoundException("Graph not found")

        if current_user:
            await self._ensure_access(graph, current_user, WorkspaceMemberRole.viewer)

        # load state
        state = await self.load_graph_state(graph_id, current_user)

        return {
            "id": str(graph.id),
            "name": graph.name,
            "description": graph.description,
            "workspaceId": str(graph.workspace_id) if graph.workspace_id else None,
            "folderId": str(graph.folder_id) if graph.folder_id else None,
            "parentId": str(graph.parent_id) if graph.parent_id else None,
            "color": graph.color,
            "isDeployed": graph.is_deployed,
            "variables": graph.variables or {},
            "createdAt": graph.created_at.isoformat() if graph.created_at else None,
            "updatedAt": graph.updated_at.isoformat() if graph.updated_at else None,
            **state,
        }

    async def create_default_deep_agents_graph(
        self,
        llm_model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        user_id: Optional[Any] = None,
        file_emitter: Optional[Any] = None,
    ) -> CompiledStateGraph:
        """
        Build a default DeepAgents single-node graph in memory (no DB persistence).
        Used for "default conversation" when graph_id is None in Chat API.

        Constructs one root node with useDeepAgents=true and no edges, then
        uses GraphBuilder so that DeepAgentsGraphBuilder builds a standalone
        create_deep_agent graph.

        Returns:
            CompiledStateGraph: Same type as create_graph_by_graph_id, ready for ainvoke/astream_events.
        """

        start_time = time.time()
        graph_id = uuid.uuid4()
        node_id = uuid.uuid4()

        # In-memory graph (not added to session)
        graph = AgentGraph(
            id=graph_id,
            name="Default Conversation",
            user_id=str(user_id) if user_id is not None else "",
            variables={},
        )

        # Single root node with DeepAgents enabled
        node = GraphNode(
            id=node_id,
            graph_id=graph_id,
            type="agent",
            data={
                "label": "Agent",
                "config": {"useDeepAgents": True, "skills": ["*"]},
            },
            position_x=0,
            position_y=0,
            width=0,
            height=0,
        )

        nodes: List[GraphNode] = [node]
        edges: List[GraphEdge] = []

        logger.info(
            f"[GraphService] ===== create_default_deep_agents_graph START ===== | "
            f"user_id={user_id} | llm_model={llm_model}"
        )

        model_service = ModelService(self.db)
        compiled_graph = await build_deep_agents_graph(
            graph=graph,
            nodes=nodes,
            edges=edges,
            llm_model=llm_model,
            api_key=api_key,
            base_url=base_url,
            user_id=user_id,
            model_service=model_service,
            file_emitter=file_emitter,
        )

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            f"[GraphService] ===== create_default_deep_agents_graph COMPLETE ===== | "
            f"user_id={user_id} | elapsed={elapsed_ms:.2f}ms"
        )
        return compiled_graph  # type: ignore[no-any-return]

    async def create_skill_creator_graph(
        self,
        user_id: str,
        workspace_id: Optional[uuid.UUID] = None,
    ) -> AgentGraph:
        """Create the persisted Skill Creator graph container.

        Frontend currently applies the `skill-creator` template from static assets after graph
        creation. This helper keeps a stable backend entry point for callers and tests that
        expect the Skill Creator graph to be a first-class graph type.
        """
        return await self.create_graph(
            name="Skill Creator",
            user_id=user_id,
            workspace_id=workspace_id,
            description="A specialized agent for creating and editing Skills",
        )

    async def create_graph_by_graph_id(
        self,
        graph_id: uuid.UUID,
        llm_model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        user_id: Optional[Any] = None,
        current_user: Optional[AuthUser] = None,
        file_emitter: Optional[Any] = None,
        thread_id: Optional[str] = None,
    ) -> CompiledStateGraph:
        """
        Create a LangGraph StateGraph from a graph stored in the database.

        Fetches the graph, nodes, and edges from the database and builds
        a compiled StateGraph where each node is an Agent.

        Args:
            graph_id: The UUID of the graph to build
            llm_model: Optional LLM model name
            api_key: Optional API key for the LLM
            base_url: Optional base URL for the LLM API
            user_id: User ID for workspace isolation
            current_user: Current authenticated user for permission checks

        Returns:
            CompiledStateGraph: The compiled graph ready for execution

        Raises:
            NotFoundException: If the graph is not found
            ForbiddenException: If the user doesn't have access to the graph
        """

        start_time = time.time()
        logger.info(
            f"[GraphService] ===== create_graph_by_graph_id START ===== | "
            f"graph_id={graph_id} | user_id={user_id} | llm_model={llm_model}"
        )

        # Fetch the graph
        logger.debug(f"[GraphService] Fetching graph from database | graph_id={graph_id}")
        graph = await self.graph_repo.get(graph_id)
        if not graph:
            logger.error(f"[GraphService] Graph not found | graph_id={graph_id}")
            raise NotFoundException(f"Graph with id {graph_id} not found")

        logger.info(
            f"[GraphService] Graph found | name='{graph.name}' | "
            f"is_deployed={graph.is_deployed} | workspace_id={graph.workspace_id}"
        )

        # Check access permissions if current_user is provided
        if current_user:
            logger.debug(
                f"[GraphService] Checking access permissions | user_id={current_user.id} | graph_owner={graph.user_id}"
            )
            await self._ensure_access(graph, current_user, WorkspaceMemberRole.viewer)
            logger.debug("[GraphService] Access permission check passed")

        # Check in-memory compile cache (keyed by graph + runtime prompt context)
        cache_key = _build_runtime_aware_compile_cache_key(graph, user_id=user_id, thread_id=thread_id)
        now_ts = time.time()
        if cache_key in _compile_cache:
            cached_graph, cached_at = _compile_cache[cache_key]
            if (now_ts - cached_at) < _COMPILE_CACHE_TTL:
                logger.info(f"[GraphService] Using cached compiled graph | graph_id={graph_id}")
                return cached_graph
            _compile_cache.pop(cache_key, None)

        # Code mode: bypass GraphBuilder entirely
        if (graph.variables or {}).get("graph_mode") == "code":
            logger.info(f"[GraphService] Code mode detected | graph_id={graph_id}")
            compiled_graph = await self._compile_code_graph(graph)
            _compile_cache[cache_key] = (compiled_graph, time.time())
            return compiled_graph  # type: ignore[no-any-return]

        # Load nodes and edges
        logger.debug(f"[GraphService] Loading nodes and edges for graph_id={graph_id}")
        nodes = await self.node_repo.list_by_graph(graph_id)
        edges = await self.edge_repo.list_by_graph(graph_id)
        await hydrate_nodes_a2a_secrets(self.db, nodes)

        logger.info(f"[GraphService] Loaded graph data | nodes_count={len(nodes)} | edges_count={len(edges)}")

        # Log node details
        for idx, node in enumerate(nodes):
            logger.debug(f"[GraphService] Node [{idx + 1}/{len(nodes)}] | id={node.id} | type={node.type}")

        # Build the graph
        logger.info("[GraphService] Building DeepAgents graph...")
        model_service = ModelService(self.db)
        compiled_graph = await build_deep_agents_graph(
            graph=graph,
            nodes=nodes,
            edges=edges,
            llm_model=llm_model,
            api_key=api_key,
            base_url=base_url,
            user_id=user_id,
            model_service=model_service,
            file_emitter=file_emitter,
            thread_id=thread_id,
        )

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            f"[GraphService] ===== create_graph_by_graph_id COMPLETE ===== | user_id={user_id} | "
            f"graph_id={graph_id} | graph_name='{graph.name}' | "
            f"nodes={len(nodes)} | edges={len(edges)} | elapsed={elapsed_ms:.2f}ms"
        )

        _compile_cache[cache_key] = (compiled_graph, time.time())
        return compiled_graph  # type: ignore[no-any-return]

    async def _compile_code_graph(self, graph):
        """Compile a code-mode graph: exec user code → get StateGraph → compile."""
        from app.core.agent.checkpointer.checkpointer import get_checkpointer
        from app.core.code_executor import execute_code

        code = (graph.variables or {}).get("code_content", "")
        if not code.strip():
            raise ValueError(f"Code graph {graph.id} has no code")

        state_graph = execute_code(code)
        compiled = state_graph.compile(checkpointer=get_checkpointer())
        return compiled
