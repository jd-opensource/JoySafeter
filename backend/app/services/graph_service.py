"""
Graph 相关 Service
"""

import uuid
from typing import Any, Dict, List, Optional, Tuple

from langgraph.graph.state import CompiledStateGraph
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.core.graph.graph_builder_factory import GraphBuilder
from app.models.auth import AuthUser
from app.models.graph import AgentGraph, GraphNode
from app.models.workspace import WorkspaceMemberRole
from app.repositories.graph import GraphEdgeRepository, GraphNodeRepository, GraphRepository

from .base import BaseService
from .model_service import ModelService
from .workspace_permission import check_workspace_access


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
        确保用户有访问图的权限

        Args:
            graph: 要访问的图
            current_user: 当前用户
            required_role: 所需的最低工作空间角色（仅对工作空间图有效）

        Raises:
            ForbiddenException: 如果用户没有访问权限
        """
        # 超级用户有所有权限
        if current_user.is_superuser:
            return

        # 如果是图的所有者，直接允许
        if graph.user_id == current_user.id:
            return

        # 如果是工作空间图，检查工作空间权限
        if graph.workspace_id:
            has_access = await check_workspace_access(
                self.db,
                graph.workspace_id,
                current_user,
                required_role,
            )
            if has_access:
                return

        # 无权限
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
        使用指定的 ID 创建图（用于 upsert 场景）

        Args:
            graph_id: 指定的图ID
            name: 图名称
            user_id: 用户ID
            workspace_id: 工作空间ID（可选）
            description: 描述（可选）

        Returns:
            创建的图对象
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
        创建新图

        Args:
            name: 图名称
            user_id: 用户ID
            workspace_id: 工作空间ID（可选）
            folder_id: 文件夹ID（可选）
            parent_id: 父图ID（可选）
            description: 描述（可选）
            color: 颜色（可选）
            variables: 变量（可选）

        Returns:
            创建的图对象

        Raises:
            NotFoundException: 如果父图不存在
        """
        # 验证 parent_id 是否存在
        if parent_id:
            parent_graph = await self.graph_repo.get(parent_id)
            if not parent_graph:
                raise NotFoundException(f"Parent graph with id {parent_id} not found")

        # 验证 folder_id 是否存在且属于指定的 workspace
        if folder_id:
            from app.repositories.workspace_folder import WorkflowFolderRepository

            folder_repo = WorkflowFolderRepository(self.db)
            folder = await folder_repo.get(folder_id)
            if not folder:
                raise NotFoundException(f"Folder with id {folder_id} not found")
            # 如果指定了 workspace_id，确保 folder 属于该 workspace
            if workspace_id and folder.workspace_id != workspace_id:
                raise BadRequestException(f"Folder {folder_id} does not belong to workspace {workspace_id}")
            # 如果没有指定 workspace_id，则从 folder 中获取
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
        # upsert 参数
        name: Optional[str] = None,
        workspace_id: Optional[uuid.UUID] = None,
    ) -> Dict[str, Any]:
        """
        保存图的完整状态（节点和边）- 支持 upsert 模式

        如果图不存在且提供了 name 参数，会自动创建新图。

        前端格式：
        {
            "nodes": [...],
            "edges": [...],
            "viewport": {...},
            ...
        }
        """
        # 使用事务确保原子性：所有操作要么全部成功，要么全部失败
        # 检查是否已经在事务中，避免重复开始事务
        if self.db.in_transaction():
            # 已经在事务中，直接执行操作
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
            # 不在事务中，开始新事务
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
        # upsert 参数
        name: Optional[str] = None,
        workspace_id: Optional[uuid.UUID] = None,
    ) -> Dict[str, Any]:
        """内部方法：实际执行保存图状态的逻辑"""
        # 获取图
        graph = await self.graph_repo.get(graph_id)
        if not graph:
            # Upsert 模式：如果图不存在，自动创建新图
            if current_user:
                # 如果没有提供工作空间ID，查找用户的默认工作空间
                if not workspace_id:
                    from app.repositories.workspace import WorkspaceRepository

                    workspace_repo = WorkspaceRepository(self.db)
                    workspace = await workspace_repo.get_by_name_and_owner(
                        name="默认工作空间",
                        owner_id=current_user.id,
                    )
                    if workspace:
                        workspace_id = workspace.id

                # 使用默认名称如果没有提供
                graph_name = name or "未命名图"

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

        # 加载现有节点，建立前端ID到数据库ID的映射
        existing_nodes = await self.node_repo.list_by_graph(graph_id)
        existing_node_map: Dict[str, GraphNode] = {}
        for node in existing_nodes:
            # 前端使用数据库UUID的字符串形式作为节点ID
            frontend_id = str(node.id)
            existing_node_map[frontend_id] = node

        # 创建节点映射（前端ID -> 数据库UUID）
        node_id_map: Dict[str, uuid.UUID] = {}
        nodes_to_create: List[Dict[str, Any]] = []
        nodes_to_update: List[Tuple[uuid.UUID, Dict[str, Any]]] = []

        # 保存节点
        for node_data in nodes:
            # 转换前端节点格式到数据库格式
            node_id = node_data.get("id")
            if not node_id:
                continue

            # 尝试将前端ID解析为UUID，如果成功且节点已存在，则更新；否则创建新节点
            db_node_id: uuid.UUID
            try:
                # 尝试将前端ID解析为UUID
                node_id_str = str(node_id)
                parsed_uuid = uuid.UUID(node_id_str)
                if str(parsed_uuid) in existing_node_map:
                    # 节点已存在，更新
                    db_node_id = parsed_uuid
                    nodes_to_update.append((db_node_id, node_data))
                else:
                    # UUID格式但节点不存在，创建新节点
                    db_node_id = uuid.uuid4()
                    nodes_to_create.append(node_data)
            except (ValueError, AttributeError):
                # 前端ID不是UUID格式（如 node_xxx），创建新节点
                db_node_id = uuid.uuid4()
                nodes_to_create.append(node_data)

            node_id_map[node_id] = db_node_id

        # 删除不再存在的节点和所有边（稍后会重新创建边）
        # 建立数据库UUID集合，用于判断哪些节点需要删除
        # node_id_map 的 value 是数据库 UUID，key 是前端 ID
        existing_db_node_ids = set(node_id_map.values())
        # 还要包含已更新的节点（这些节点会保留，不应该删除）
        for db_node_id, _ in nodes_to_update:
            existing_db_node_ids.add(db_node_id)

        nodes_to_delete = [
            node.id for node_id_str, node in existing_node_map.items() if node.id not in existing_db_node_ids
        ]
        if nodes_to_delete:
            await self.node_repo.delete_by_ids(graph_id, nodes_to_delete)
            await self.edge_repo.delete_by_graph(graph_id)

        # 创建新节点
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
            config = data_payload.get("config", {}) if isinstance(data_payload, dict) else {}
            node_type = data_payload.get("type") or node_data.get("type") or "agent"

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
                "prompt": "",
                "tools": (config.get("tools") if isinstance(config, dict) else None)
                or data_payload.get("tools", {})
                or {},
                "memory": data_payload.get("memory", {}) if isinstance(data_payload, dict) else {},
                "data": data_payload,
            }

            if "systemPrompt" in config:
                node_create_data["prompt"] = config["systemPrompt"]
            elif "prompt" in config:
                node_create_data["prompt"] = config["prompt"]

            await self.node_repo.create(node_create_data)

        # 更新现有节点
        for db_node_id, node_data in nodes_to_update:
            position = node_data.get("position", {})
            position_absolute = node_data.get("positionAbsolute", position)
            data_payload = node_data.get("data", {}) or {}
            config = data_payload.get("config", {}) if isinstance(data_payload, dict) else {}
            node_type = data_payload.get("type") or node_data.get("type") or "agent"

            update_data = {
                "type": node_type,
                "position_x": float(position.get("x", 0)),
                "position_y": float(position.get("y", 0)),
                "position_absolute_x": float(position_absolute.get("x", position.get("x", 0))),
                "position_absolute_y": float(position_absolute.get("y", position.get("y", 0))),
                "width": float(node_data.get("width", 0)),
                "height": float(node_data.get("height", 0)),
                "tools": (config.get("tools") if isinstance(config, dict) else None)
                or data_payload.get("tools", {})
                or {},
                "memory": data_payload.get("memory", {}) if isinstance(data_payload, dict) else {},
                "data": data_payload,
            }

            if "systemPrompt" in config:
                update_data["prompt"] = config["systemPrompt"]
            elif "prompt" in config:
                update_data["prompt"] = config["prompt"]

            await self.node_repo.update(db_node_id, update_data)

        # 保存边（带去重）
        saved_edges_count = 0
        skipped_edges_count = 0
        seen_edges: set[tuple[str, str]] = set()  # 用于去重

        for edge_data in edges:
            source_id = edge_data.get("source")
            target_id = edge_data.get("target")

            if not source_id or not target_id:
                skipped_edges_count += 1
                continue

            # 边去重：同一 source-target 组合只保存一次
            edge_key = (source_id, target_id)
            if edge_key in seen_edges:
                skipped_edges_count += 1
                continue
            seen_edges.add(edge_key)

            # 查找对应的数据库节点ID
            source_node_id = node_id_map.get(source_id)
            target_node_id = node_id_map.get(target_id)

            if not source_node_id or not target_node_id:
                skipped_edges_count += 1
                continue

            # 提取边的 data 字段（包括 edge_type, route_key, source_handle_id 等）
            edge_data_payload = edge_data.get("data", {}) or {}

            edge_create_data = {
                "graph_id": graph_id,
                "source_node_id": source_node_id,
                "target_node_id": target_node_id,
                "data": edge_data_payload,  # 保存边的元数据（edge_type, route_key 等）
            }

            await self.edge_repo.create(edge_create_data)
            saved_edges_count += 1

        # 更新图的变量（保存 viewport 和 context 变量等元数据）和更新时间
        update_data = {}
        graph_variables = graph.variables or {}

        if viewport:
            graph_variables["viewport"] = viewport

        # 如果提供了 variables，合并到 graph_variables 中
        if variables:
            # 合并 variables，保留现有的 viewport 等字段
            for key, value in variables.items():
                graph_variables[key] = value

        if viewport or variables:
            update_data["variables"] = graph_variables

        # 更新图的更新时间（确保列表排序正确）
        # BaseModel 使用 updated_at 字段，SQLAlchemy 的 onupdate 会自动更新
        # 但为了确保更新，我们显式触发一次更新
        from app.utils.datetime import utc_now

        update_data["updated_at"] = utc_now()

        if update_data:
            await self.graph_repo.update(graph_id, update_data)

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
        加载图的完整状态（节点和边）

        返回前端期望的格式：
        {
            "nodes": [...],
            "edges": [...],
            "viewport": {...},
            ...
        }
        """
        # 获取图
        graph = await self.graph_repo.get(graph_id, relations=["nodes", "edges"])
        if not graph:
            raise NotFoundException("Graph not found")

        # 权限检查
        if current_user:
            await self._ensure_access(graph, current_user, WorkspaceMemberRole.viewer)

        # 加载节点和边
        nodes = await self.node_repo.list_by_graph(graph_id)
        edges = await self.edge_repo.list_by_graph(graph_id)

        # 构建节点映射（数据库UUID -> 前端ID）
        node_id_map: Dict[uuid.UUID, str] = {}
        frontend_nodes = []

        for node in nodes:
            # 生成前端ID（使用节点ID的字符串形式）
            frontend_id = str(node.id)
            node_id_map[node.id] = frontend_id

            # 构建前端节点格式
            # 注意：ReactFlow 的 type 字段应该是 "custom"（所有节点都使用 BuilderNode 组件）
            # 而实际的节点类型（如 "agent", "condition" 等）存储在 data.type 中
            node_data = node.data or {}

            # 确保 data.type 存在（用于从 nodeRegistry 获取颜色等信息）
            # 如果 node.data 中没有 type，则使用数据库的 node.type 字段
            if "type" not in node_data:
                node_data["type"] = node.type

            # 恢复位置信息：使用保存的 position 和 positionAbsolute
            # 如果 position_absolute_x/y 不存在（旧数据），则使用 position_x/y 作为回退
            pos_x = float(node.position_x)
            pos_y = float(node.position_y)
            pos_abs_x = float(node.position_absolute_x) if node.position_absolute_x is not None else pos_x
            pos_abs_y = float(node.position_absolute_y) if node.position_absolute_y is not None else pos_y

            frontend_node: Dict[str, Any] = {
                "id": frontend_id,
                "type": "custom",  # ReactFlow 节点类型，所有节点都使用 BuilderNode
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

            # 确保 config 字段存在
            node_data_dict = frontend_node["data"] if isinstance(frontend_node["data"], dict) else {}
            if "config" not in node_data_dict:
                node_data_dict["config"] = {}
            frontend_node["data"] = node_data_dict

            # 优先使用 node.data.config 中已有的值，如果没有则从 node.prompt/node.tools 恢复
            # 这是为了确保从部署版本回滚时，能保留完整的配置信息
            config = node_data_dict.get("config", {})
            if isinstance(config, dict):
                # systemPrompt: 优先使用 config 中的值
                if "systemPrompt" not in config or not config.get("systemPrompt"):
                    if node.prompt:
                        config["systemPrompt"] = node.prompt

                # tools: 优先使用 config 中的值
                if "tools" not in config or not config.get("tools"):
                    if node.tools:
                        config["tools"] = node.tools

            # memory: 优先使用 data.config 中的值
            if "memory" not in node_data_dict or not node_data_dict.get("memory"):
                if node.memory:
                    node_data_dict["memory"] = node.memory

            frontend_nodes.append(frontend_node)

        # 构建前端边格式
        frontend_edges = []
        for edge in edges:
            source_id = node_id_map.get(edge.source_node_id)
            target_id = node_id_map.get(edge.target_node_id)

            if not source_id or not target_id:
                continue

            # 从数据库恢复边的 data 字段
            edge_data = edge.data or {}
            edge_type = edge_data.get("edge_type", "normal")

            # 根据 edge_type 设置样式和类型
            if edge_type == "loop_back":
                edge_style = {
                    "stroke": "#9333ea",  # 紫色，与前端 LoopBackEdge 一致
                    "strokeWidth": 2.5,
                    "strokeDasharray": "5,5",
                }
                edge_type_for_reactflow = "loop_back"
            elif edge_type == "conditional":
                edge_style = {
                    "stroke": "#3b82f6",  # 蓝色，与前端条件边一致
                    "strokeWidth": 2,
                }
                edge_type_for_reactflow = "default"
            else:
                # normal 或其他类型
                edge_style = {
                    "stroke": "#cbd5e1",  # 与前端 defaultEdgeOptions 中的颜色一致
                    "strokeWidth": 1.5,
                }
                edge_type_for_reactflow = "default"

            # 使用与前端一致的默认边样式（与 BuilderCanvas.tsx 中的 defaultEdgeOptions 保持一致）
            frontend_edge = {
                "source": source_id,
                "target": target_id,
                "sourceHandle": None,
                "targetHandle": None,
                "type": edge_type_for_reactflow,  # 设置 ReactFlow 边类型
                "animated": True,
                "style": edge_style,
                "data": edge_data,  # 恢复边的元数据（edge_type, route_key, source_handle_id 等）
                "id": f"reactflow__edge-{source_id}-{target_id}",
            }
            frontend_edges.append(frontend_edge)

        # 获取 viewport 和 variables
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
        """获取图的详细信息（包括状态）"""
        graph = await self.graph_repo.get(graph_id)
        if not graph:
            raise NotFoundException("Graph not found")

        if current_user:
            await self._ensure_access(graph, current_user, WorkspaceMemberRole.viewer)

        # 加载状态
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

    async def create_graph_by_graph_id(
        self,
        graph_id: uuid.UUID,
        llm_model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        max_tokens: int = 4096,
        user_id: Optional[Any] = None,
        current_user: Optional[AuthUser] = None,
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
            max_tokens: Maximum tokens for LLM responses
            user_id: User ID for workspace isolation
            current_user: Current authenticated user for permission checks

        Returns:
            CompiledStateGraph: The compiled graph ready for execution

        Raises:
            NotFoundException: If the graph is not found
            ForbiddenException: If the user doesn't have access to the graph
        """
        import time

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

        # Load nodes and edges
        logger.debug(f"[GraphService] Loading nodes and edges for graph_id={graph_id}")
        nodes = await self.node_repo.list_by_graph(graph_id)
        edges = await self.edge_repo.list_by_graph(graph_id)

        logger.info(f"[GraphService] Loaded graph data | nodes_count={len(nodes)} | edges_count={len(edges)}")

        # Log node details
        for idx, node in enumerate(nodes):
            logger.debug(
                f"[GraphService] Node [{idx + 1}/{len(nodes)}] | "
                f"id={node.id} | type={node.type} | has_prompt={bool(node.prompt)}"
            )

        # Build the graph
        logger.info("[GraphService] Starting GraphBuilder...")
        # 为当前请求构建一个 ModelService，用于在图执行中按 model_name 解析模型
        model_service = ModelService(self.db)
        builder = GraphBuilder(
            graph=graph,
            nodes=nodes,
            edges=edges,
            llm_model=llm_model,
            api_key=api_key,
            base_url=base_url,
            max_tokens=max_tokens,
            user_id=user_id,
            model_service=model_service,
        )

        # 异步构建
        compiled_graph = await builder.build()

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            f"[GraphService] ===== create_graph_by_graph_id COMPLETE ===== | user_id={user_id} | "
            f"graph_id={graph_id} | graph_name='{graph.name}' | "
            f"nodes={len(nodes)} | edges={len(edges)} | elapsed={elapsed_ms:.2f}ms"
        )

        return compiled_graph
