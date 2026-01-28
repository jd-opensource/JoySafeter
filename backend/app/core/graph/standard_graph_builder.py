"""
LangGraph Model Builder - Builds standard LangGraph with START/END nodes.

Implements the standard workflow pattern with explicit START and END nodes.
Supports conditional routing, loops, and parallel execution.
"""

import asyncio
import time
import uuid
from typing import Any, Dict, List, Set

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from loguru import logger

try:
    from langgraph.types import Command

    COMMAND_AVAILABLE = True
except ImportError:
    COMMAND_AVAILABLE = False
    Command = None  # type: ignore[assignment, misc]
    logger.warning("[LanggraphModelBuilder] langgraph.types.Command not available")

try:
    from cachetools import TTLCache  # type: ignore[import-untyped]

    CACHE_AVAILABLE = True
except ImportError:
    # Fallback to dict if cachetools not available
    TTLCache = dict  # type: ignore[assignment, misc]
    CACHE_AVAILABLE = False
    logger.warning("[LanggraphModelBuilder] cachetools not available, using dict cache")

from app.core.graph.base_graph_builder import BaseGraphBuilder
from app.core.graph.graph_state import GraphState
from app.core.graph.node_executors import (
    ConditionNodeExecutor,
    LoopConditionNodeExecutor,
    RouterNodeExecutor,
)
from app.core.graph.node_wrapper import NodeExecutionWrapper


class GraphValidationError(Exception):
    """图结构验证失败异常"""

    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__(f"Graph validation failed with {len(errors)} error(s)")

    def __str__(self) -> str:
        return "Graph validation failed:\n" + "\n".join(f"  - {error}" for error in self.errors)


class LanggraphModelBuilder(BaseGraphBuilder):
    """Builds standard LangGraph with START/END nodes.

    Supports:
    - Conditional routing (RouterNodeExecutor, ConditionNodeExecutor)
    - Loops (LoopConditionNodeExecutor)
    - Parallel execution (Fan-Out/Fan-In)
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Track which nodes have conditional edges
        self._conditional_nodes: Set[str] = set()
        # Store handle-to-route mappings for router nodes
        self._handle_to_route_maps: Dict[str, Dict[str, str]] = {}
        # Cache executors to avoid recreating them (thread-safe with lock and TTL)
        if CACHE_AVAILABLE:
            self._executor_cache = TTLCache(maxsize=1000, ttl=300)  # 5 minutes TTL
        else:
            self._executor_cache: Dict[str, Any] = {}
        self._executor_cache_lock = asyncio.Lock()
        # Map loop body nodes to loop condition nodes
        self._loop_body_map: Dict[str, str] = {}  # loop_body_node_id -> loop_condition_node_id
        # Track parallel nodes (Fan-Out nodes)
        self._parallel_nodes: Set[str] = set()
        # Cache node types to avoid repeated computation
        self._node_types: Dict[uuid.UUID, str] = {}

    def _validate_edge_data(self, edge: Any, allowed_edge_types: List[str]) -> None:
        """
        Validate edge data for correctness.

        Args:
            edge: Edge object to validate
            allowed_edge_types: List of allowed edge_type values

        Raises:
            GraphValidationError: If edge data is invalid
        """
        edge_data = edge.data or {}
        edge_type = edge_data.get("edge_type", "normal")
        route_key = edge_data.get("route_key", "default")

        if edge_type not in allowed_edge_types:
            raise GraphValidationError(
                [
                    f"Invalid edge_type '{edge_type}' for edge {edge.source_node_id} -> {edge.target_node_id}. "
                    f"Allowed types: {allowed_edge_types}"
                ]
            )

        # Additional validation for special route keys
        if route_key in ["continue_loop", "exit_loop"]:
            if edge_type not in ["loop_back", "conditional", "normal"]:
                raise GraphValidationError(
                    [
                        f"Edge with route_key '{route_key}' must have edge_type in "
                        f"['loop_back', 'conditional', 'normal'], got '{edge_type}'"
                    ]
                )

    def _build_conditional_edges_generic(
        self,
        workflow: StateGraph,
        node: Any,
        node_name: str,
        executor: Any,
        edge_processor: Any,
    ) -> None:
        """统一的条件边构建方法，避免代码重复。

        Args:
            workflow: LangGraph StateGraph 实例
            node: 节点对象
            node_name: 节点名称
            executor: 节点执行器
            edge_processor: 边处理函数，接受 (edge, conditional_map, handle_to_route_map) 参数
        """
        conditional_map: Dict[str, Any] = {}
        handle_to_route_map: Dict[str, str] = {}

        # 收集并处理此节点的所有出边
        for edge in self.edges:
            if edge.source_node_id == node.id:
                edge_processor(edge, conditional_map, handle_to_route_map)

        # 添加条件边到工作流
        if conditional_map:
            workflow.add_conditional_edges(node_name, executor, conditional_map)  # type: ignore[arg-type]
            self._conditional_nodes.add(node_name)

    def _validate_router_edges(
        self,
        router_node_id: str,
        conditional_map: Dict[str, str],
        handle_to_route_map: Dict[str, str],
    ) -> None:
        """Validate that all router branches have corresponding downstream nodes."""
        if not conditional_map:
            logger.warning(f"[LanggraphModelBuilder] Router node '{router_node_id}' has no conditional edges")
            return

        # Check that all route keys have targets
        for route_key, target_name in conditional_map.items():
            if not target_name:
                logger.error(
                    f"[LanggraphModelBuilder] Router node '{router_node_id}' has invalid route: "
                    f"route_key='{route_key}' has no target"
                )

        logger.debug(
            f"[LanggraphModelBuilder] Router validation passed | "
            f"node_id={router_node_id} | routes={list(conditional_map.keys())}"
        )

    def _process_router_edge(
        self, edge: Any, conditional_map: Dict[str, str], handle_to_route_map: Dict[str, str]
    ) -> None:
        """处理路由器节点的边数据"""
        # Validate edge data
        self._validate_edge_data(edge, ["conditional", "normal"])

        edge_data = edge.data or {}
        source_handle_id = edge_data.get("source_handle_id")
        route_key = edge_data.get("route_key", "default")
        edge_label = edge_data.get("label", "")

        # Build Handle ID to route_key mapping
        if source_handle_id:
            handle_to_route_map[source_handle_id] = route_key

        target_name = self._node_id_to_name.get(edge.target_node_id)
        if target_name:
            conditional_map[route_key] = target_name
            # Log with label if available
            if edge_label:
                logger.debug(
                    f"[LanggraphModelBuilder] Router edge: {edge_label} | route_key={route_key} | target={target_name}"
                )

    def _create_router_wrapper(
        self,
        router_executor: RouterNodeExecutor,
        conditional_map: Dict[str, str],
    ) -> Any:
        """创建路由包装函数，处理 Command 对象返回值。

        Args:
            router_executor: 路由器执行器
            conditional_map: 路由键到目标节点的映射

        Returns:
            包装后的路由函数，总是返回字符串 route_key
        """

        async def router_wrapper(state: GraphState) -> str:
            """包装路由函数，处理 Command 对象。

            LangGraph 的 add_conditional_edges 期望返回字符串 route_key。
            如果执行器返回 Command，我们提取 goto 并映射回 route_key。
            """
            result = await router_executor(state)

            # 如果返回 Command 对象，提取 goto 信息
            if COMMAND_AVAILABLE and isinstance(result, Command):
                goto = result.goto if hasattr(result, "goto") else None
                if goto:
                    # 尝试从 conditional_map 反向查找 route_key
                    # 如果 goto 直接匹配某个 route_key，使用它
                    for route_key, target_node in conditional_map.items():
                        if target_node == goto:
                            logger.debug(
                                f"[LanggraphModelBuilder] Command goto mapped to route_key | "
                                f"goto={goto} | route_key={route_key}"
                            )
                            return route_key

                    # 如果找不到匹配，使用 goto 作为 route_key（假设它们匹配）
                    logger.warning(
                        f"[LanggraphModelBuilder] Command goto not found in conditional_map | "
                        f"goto={goto} | using as route_key"
                    )
                    return str(goto)

                # Command 没有 goto，使用默认路由
                return list(conditional_map.keys())[0] if conditional_map else "default"

            # 返回字符串 route_key（默认行为）
            return str(result) if result is not None else "default"

        return router_wrapper

    def _build_conditional_edges_for_router(
        self,
        workflow: StateGraph,
        router_node: Any,
        router_node_name: str,
        router_executor: RouterNodeExecutor,
    ) -> None:
        """Build conditional edges for a router node."""
        # 使用通用方法构建条件边
        conditional_map: Dict[str, Any] = {}
        handle_to_route_map: Dict[str, str] = {}

        # 收集并处理此节点的所有出边
        for edge in self.edges:
            if edge.source_node_id == router_node.id:
                self._process_router_edge(edge, conditional_map, handle_to_route_map)

        # Validate router edges
        self._validate_router_edges(
            router_node_name,
            conditional_map,
            handle_to_route_map,
        )

        # Store handle-to-route mapping for the executor
        router_executor.set_handle_to_route_map(handle_to_route_map)
        self._handle_to_route_maps[router_node_name] = handle_to_route_map

        # Add conditional edges
        if conditional_map:
            # 检查是否启用 Command 模式
            data = router_node.data or {}
            config = data.get("config", {})
            use_command_mode = config.get("useCommandMode", False) and COMMAND_AVAILABLE

            # 如果启用 Command 模式，使用包装函数
            router_func = (
                self._create_router_wrapper(router_executor, conditional_map) if use_command_mode else router_executor
            )

            workflow.add_conditional_edges(
                router_node_name,
                router_func,  # Router function returns route_key (or wrapped to handle Command)
                conditional_map,  # type: ignore[arg-type]
            )
            self._conditional_nodes.add(router_node_name)
            logger.info(
                f"[LanggraphModelBuilder] Added conditional edges for router | "
                f"node={router_node_name} | routes={list(conditional_map.keys())} | "
                f"command_mode={use_command_mode}"
            )

    def _process_condition_edge(
        self, edge: Any, conditional_map: Dict[str, str], handle_to_route_map: Dict[str, str]
    ) -> None:
        """处理条件节点的边数据"""
        # Validate edge data
        self._validate_edge_data(edge, ["conditional", "normal"])

        edge_data = edge.data or {}
        source_handle_id = edge_data.get("source_handle_id")
        route_key = edge_data.get("route_key")
        edge_label = edge_data.get("label", "")

        # Default route keys for condition nodes
        if not route_key:
            # Try to infer from handle_id
            if source_handle_id in ["true", "yes", "1"]:
                route_key = "true"
            elif source_handle_id in ["false", "no", "0"]:
                route_key = "false"
            else:
                route_key = source_handle_id or "default"

        if source_handle_id:
            handle_to_route_map[source_handle_id] = route_key

        target_name = self._node_id_to_name.get(edge.target_node_id)
        if target_name:
            conditional_map[route_key] = target_name
            # Log with label if available
            if edge_label:
                logger.debug(
                    f"[LanggraphModelBuilder] Condition edge: {edge_label} | "
                    f"route_key={route_key} | target={target_name}"
                )

    def _create_condition_wrapper(
        self,
        condition_executor: ConditionNodeExecutor,
        conditional_map: Dict[str, str],
    ) -> Any:
        """创建条件节点包装函数，处理 Command 对象和状态更新。

        Args:
            condition_executor: 条件节点执行器
            conditional_map: 路由键到目标节点的映射

        Returns:
            包装后的条件函数，总是返回字符串 route_key，并更新状态
        """

        async def condition_wrapper(state: GraphState) -> str:
            """包装条件函数，处理 Command 对象和状态更新。

            LangGraph 的 add_conditional_edges 期望返回字符串 route_key。
            ConditionNodeExecutor 现在返回字符串或 Command 对象。
            """
            result = await condition_executor(state)

            # 如果返回 Command 对象，提取 goto 信息并更新状态
            if COMMAND_AVAILABLE and isinstance(result, Command):
                goto = result.goto if hasattr(result, "goto") else None
                # 更新状态（通过返回字典，LangGraph 会自动合并）
                if hasattr(result, "update") and isinstance(result.update, dict):
                    # 注意：这里不能直接更新 state，因为这是路由函数
                    # 状态更新应该通过节点的正常执行来完成
                    pass

                if goto:
                    # 尝试从 conditional_map 反向查找 route_key
                    for route_key, target_node in conditional_map.items():
                        if target_node == goto:
                            logger.debug(
                                f"[LanggraphModelBuilder] Condition Command goto mapped to route_key | "
                                f"goto={goto} | route_key={route_key}"
                            )
                            return route_key

                    # 如果找不到匹配，使用 goto 作为 route_key
                    logger.warning(
                        f"[LanggraphModelBuilder] Condition Command goto not found in conditional_map | "
                        f"goto={goto} | using as route_key"
                    )
                    return str(goto)

                # Command 没有 goto，尝试从 update 中提取 route_decision
                if hasattr(result, "update") and isinstance(result.update, dict):
                    route_decision = result.update.get("route_decision")
                    if route_decision:
                        return str(route_decision)

                # 使用默认路由
                return list(conditional_map.keys())[0] if conditional_map else "default"

            # 现在 ConditionNodeExecutor 直接返回字符串 route_key
            if isinstance(result, str):
                return result

            # 向后兼容：如果返回字典（旧版本），提取 route_decision
            if isinstance(result, dict):
                route_decision = result.get("route_decision")
                if route_decision:
                    logger.warning(
                        "[LanggraphModelBuilder] Condition executor returned dict (legacy), extracting route_decision"
                    )
                    return str(route_decision)
                return list(conditional_map.keys())[0] if conditional_map else "default"

            # 其他情况，使用默认路由
            logger.warning(
                f"[LanggraphModelBuilder] Condition executor returned unexpected type | "
                f"type={type(result)} | using default"
            )
            return list(conditional_map.keys())[0] if conditional_map else "default"

        return condition_wrapper

    def _build_conditional_edges_for_condition(
        self,
        workflow: StateGraph,
        condition_node: Any,
        condition_node_name: str,
        condition_executor: ConditionNodeExecutor,
    ) -> None:
        """Build conditional edges for a condition node."""
        conditional_map: Dict[str, Any] = {}
        handle_to_route_map: Dict[str, str] = {}

        # 收集并处理此节点的所有出边
        for edge in self.edges:
            if edge.source_node_id == condition_node.id:
                self._process_condition_edge(edge, conditional_map, handle_to_route_map)

        # Store handle-to-route mapping
        condition_executor.set_handle_to_route_map(handle_to_route_map)

        # Add conditional edges
        if conditional_map:
            # 创建包装函数，从字典中提取 route_decision
            condition_func = self._create_condition_wrapper(condition_executor, conditional_map)

            workflow.add_conditional_edges(
                condition_node_name,
                condition_func,  # 包装后的函数返回字符串 route_key
                conditional_map,  # type: ignore[arg-type]
            )
            self._conditional_nodes.add(condition_node_name)
            logger.info(
                f"[LanggraphModelBuilder] Added conditional edges for condition | "
                f"node={condition_node_name} | routes={list(conditional_map.keys())}"
            )

    def _process_loop_edge(
        self, edge: Any, conditional_map: Dict[str, str], handle_to_route_map: Dict[str, str]
    ) -> None:
        """处理循环节点的边数据"""
        # Validate edge data (allow loop_back for loop edges)
        self._validate_edge_data(edge, ["loop_back", "conditional", "normal"])

        edge_data = edge.data or {}
        route_key = edge_data.get("route_key", "default")
        edge_label = edge_data.get("label", "")

        # Map continue_loop and exit_loop
        if route_key in ["continue_loop", "exit_loop"]:
            target_name = self._node_id_to_name.get(edge.target_node_id)
            if target_name:
                conditional_map[route_key] = target_name
                # Log with label if available
                if edge_label:
                    logger.debug(
                        f"[LanggraphModelBuilder] Loop edge: {edge_label} | "
                        f"route_key={route_key} | target={target_name}"
                    )

    def _build_conditional_edges_for_loop(
        self,
        workflow: StateGraph,
        loop_node: Any,
        loop_node_name: str,
        loop_executor: LoopConditionNodeExecutor,
    ) -> None:
        """Build conditional edges for a loop condition node."""
        conditional_map: Dict[str, Any] = {}

        # 收集并处理此节点的所有出边
        for edge in self.edges:
            if edge.source_node_id == loop_node.id:
                self._process_loop_edge(edge, conditional_map, {})  # loop不需要handle_to_route_map

        # Add conditional edges
        if conditional_map:
            workflow.add_conditional_edges(
                loop_node_name,
                loop_executor,  # Loop function returns 'continue_loop' or 'exit_loop'
                conditional_map,  # type: ignore[arg-type]
            )
            self._conditional_nodes.add(loop_node_name)
            logger.info(
                f"[LanggraphModelBuilder] Added conditional edges for loop | "
                f"node={loop_node_name} | routes={list(conditional_map.keys())}"
            )

    def _identify_loop_bodies(self) -> Dict[str, str]:
        """识别循环体节点。

        通过分析图结构，找到所有循环条件节点的 continue_loop 边指向的节点。
        处理复杂情况：循环嵌套、多个循环引用同一个节点等。

        Returns:
            Dict mapping loop_body_node_name -> loop_condition_node_name

        Raises:
            GraphValidationError: 当发现无效的循环结构时
        """
        loop_bodies: Dict[str, str] = {}
        validation_errors = []

        # 首先收集所有循环条件节点
        loop_condition_nodes = [node for node in self.nodes if self._node_types[node.id] == "loop_condition_node"]

        # 预构建节点到出边的映射，避免嵌套循环 O(V*E) → O(E)
        node_outgoing_edges: Dict[str, List[Any]] = {}
        for edge in self.edges:
            source_id = str(edge.source_node_id)
            if source_id not in node_outgoing_edges:
                node_outgoing_edges[source_id] = []
            node_outgoing_edges[source_id].append(edge)

        # 验证所有循环条件节点
        for loop_node in loop_condition_nodes:
            loop_node_name = self._get_node_name(loop_node)

            # 使用预构建的映射查找出边
            outgoing_edges = node_outgoing_edges.get(str(loop_node.id), [])

            # 找到此循环条件节点的所有 continue_loop 边
            continue_loop_targets = []
            for edge in outgoing_edges:
                edge_data = edge.data or {}
                if edge_data.get("route_key") == "continue_loop":
                    target_node_id = edge.target_node_id
                    target_node = self._node_map.get(target_node_id)
                    if target_node:
                        target_node_name = self._get_node_name(target_node)
                        continue_loop_targets.append((target_node_name, edge_data.get("label", "")))

            # 验证循环结构
            if len(continue_loop_targets) == 0:
                validation_errors.append(f"Loop condition node '{loop_node_name}' has no continue_loop edges")
            elif len(continue_loop_targets) > 1:
                validation_errors.append(
                    f"Loop condition node '{loop_node_name}' has multiple continue_loop edges: "
                    f"{[target for target, _ in continue_loop_targets]}"
                )
            else:
                # 只有一个 continue_loop 边，这是正确的
                target_node_name, edge_label = continue_loop_targets[0]

                # 检查是否已经被其他循环引用
                if target_node_name in loop_bodies:
                    existing_loop = loop_bodies[target_node_name]
                    if existing_loop != loop_node_name:
                        validation_errors.append(
                            f"Node '{target_node_name}' is referenced as loop body by multiple "
                            f"loop conditions: '{existing_loop}' and '{loop_node_name}'"
                        )
                else:
                    loop_bodies[target_node_name] = loop_node_name
                    logger.debug(
                        f"[LanggraphModelBuilder] Identified loop body | "
                        f"body_node={target_node_name} | loop_node={loop_node_name} | "
                        f"edge_label={edge_label or 'unnamed'}"
                    )

        # 检查循环嵌套（循环体本身是循环条件节点）
        for body_node_name, loop_node_name in loop_bodies.items():
            body_node = next((node for node in self.nodes if self._get_node_name(node) == body_node_name), None)
            if body_node and self._node_types[body_node.id] == "loop_condition_node":
                logger.warning(
                    f"[LanggraphModelBuilder] Detected nested loop structure | "
                    f"inner_loop_body={body_node_name} | outer_loop_condition={loop_node_name}"
                )

        # 如果有验证错误，抛出异常
        if validation_errors:
            raise GraphValidationError(validation_errors)

        return loop_bodies

    def _identify_parallel_nodes(self) -> Set[str]:
        """识别并行节点（Fan-Out 节点）。

        找到所有有多个出边的节点（Fan-Out）。
        预计算节点名称映射，避免重复的字典查找和方法调用。

        Returns:
            Set of parallel node names
        """
        from collections import Counter

        # 预计算有效的边和节点名称映射，避免重复查找
        valid_source_ids = {edge.source_node_id for edge in self.edges if edge.source_node_id in self._node_map}
        node_names = {node.id: self._get_node_name(node) for node in self.nodes}

        # 使用 Counter 一次性统计所有出边，O(E) 复杂度
        outgoing_count = Counter(
            node_names[edge.source_node_id] for edge in self.edges if edge.source_node_id in valid_source_ids
        )

        # 出边数 > 1 的节点是 Fan-Out 节点
        parallel_nodes = {node_name for node_name, count in outgoing_count.items() if count > 1}

        # 记录日志
        for node_name in parallel_nodes:
            count = outgoing_count[node_name]
            logger.debug(
                f"[LanggraphModelBuilder] Identified parallel node (Fan-Out) | "
                f"node={node_name} | outgoing_edges={count}"
            )

        return parallel_nodes

    async def _get_or_create_executor(
        self,
        node: Any,
        node_name: str,
    ) -> Any:
        """线程安全地获取或创建执行器，避免竞态条件。"""
        async with self._executor_cache_lock:
            if node_name in self._executor_cache:
                return self._executor_cache[node_name]

            executor = await self._create_node_executor(node, node_name)
            self._executor_cache[node_name] = executor
            return executor

    def _wrap_node_executor(
        self,
        executor: Any,
        node_name: str,
        node_type: str,
    ) -> Any:
        """包装节点执行器，添加自动状态更新功能。

        Args:
            executor: 原始执行器
            node_name: 节点名称
            node_type: 节点类型

        Returns:
            包装后的执行器
        """
        # 构建元数据
        metadata = {
            "is_loop_body": node_name in self._loop_body_map,
            "loop_node_id": self._loop_body_map.get(node_name),
            "is_parallel_node": node_name in self._parallel_nodes,
        }

        # 如果是循环体或并行节点，使用包装器
        if metadata["is_loop_body"] or metadata["is_parallel_node"]:
            return NodeExecutionWrapper(
                executor=executor,
                node_id=node_name,
                node_type=node_type,
                metadata=metadata,
            )

        # 否则直接返回原始执行器
        return executor

    def _add_regular_edges(self, workflow: StateGraph) -> int:
        """Add regular (non-conditional) edges to the workflow.

        Returns:
            Number of edges added.
        """
        edges_added = 0

        for edge in self.edges:
            source_name = self._node_id_to_name.get(edge.source_node_id)
            target_name = self._node_id_to_name.get(edge.target_node_id)

            # Skip if source or target not found
            if not source_name or not target_name:
                continue

            # Skip if source node has conditional edges (already handled)
            if source_name in self._conditional_nodes:
                continue

            # Add regular edge (supports parallel execution - Fan-Out/Fan-In)
            workflow.add_edge(source_name, target_name)
            edges_added += 1

        return edges_added

    async def build(self) -> Any:  # type: ignore[override]
        """异步构建 LangGraph StateGraph with START/END nodes.

        Supports conditional routing, loops, and parallel execution.
        """
        build_start_time = time.time()
        logger.info(
            f"[LanggraphModelBuilder] ========== Starting LangGraph model build ========== | "
            f"graph='{self.graph.name}' | graph_id={self.graph.id}"
        )

        workflow = StateGraph(GraphState)

        if not self.nodes:
            logger.warning("[LanggraphModelBuilder] No nodes, creating pass-through graph")

            async def pass_through(state: GraphState) -> Dict[str, Any]:
                return {"messages": [AIMessage(content="No workflow nodes configured.")]}

            workflow.add_node("pass_through", pass_through)
            workflow.add_edge(START, "pass_through")
            workflow.add_edge("pass_through", END)
            # Empty graph doesn't need interrupt configuration
            from app.core.agent.checkpointer.checkpointer import get_checkpointer

            compiled = workflow.compile(checkpointer=get_checkpointer())

            elapsed_ms = (time.time() - build_start_time) * 1000
            logger.info(f"[LanggraphModelBuilder] Build complete (empty) | elapsed={elapsed_ms:.2f}ms")
            return compiled

        # Step 0: Pre-compute node types to avoid repeated checks
        self._node_types = {node.id: self._get_node_type(node) for node in self.nodes}

        # Step 0.1: Validate graph structure (compile-time validation)
        structure_errors = self.validate_graph_structure()
        mapping_errors = self.validate_handle_to_route_mapping()

        if structure_errors or mapping_errors:
            all_errors = structure_errors + mapping_errors
            logger.error(f"[LanggraphModelBuilder] Graph validation failed with {len(all_errors)} error(s)")
            for error in all_errors:
                logger.error(f"[LanggraphModelBuilder]   - {error}")
            # 验证失败时抛出异常，阻止构建
            raise GraphValidationError(all_errors)

        # Step 1: Identify loop bodies and parallel nodes (before adding nodes)
        self._loop_body_map = self._identify_loop_bodies()
        self._parallel_nodes = self._identify_parallel_nodes()

        logger.info(
            f"[LanggraphModelBuilder] Identified {len(self._loop_body_map)} loop body nodes | "
            f"{len(self._parallel_nodes)} parallel nodes"
        )

        # Step 2: Add all nodes (parallel creation for better performance)
        logger.info(f"[LanggraphModelBuilder] Adding {len(self.nodes)} nodes...")

        # 首先建立节点名称映射（这个是串行的，因为需要避免名称冲突）
        for node in self.nodes:
            node_name = self._get_node_name(node)
            self._node_id_to_name[node.id] = node_name

        # 并行创建所有节点执行器
        if len(self.nodes) > 1:  # 只有在有多个节点时才使用并行
            logger.debug("[LanggraphModelBuilder] Creating nodes in parallel...")

            # 真正的并行：并发创建执行器
            tasks = []
            for node in self.nodes:
                node_name = self._get_node_name(node)
                task = self._get_or_create_executor(node, node_name)
                tasks.append(task)

            # 等待所有执行器创建完成
            executors = await asyncio.gather(*tasks)

            # 创建包装器并添加到工作流
            for node, executor in zip(self.nodes, executors):
                node_name = self._get_node_name(node)
                node_type = self._node_types[node.id]
                wrapped_executor = self._wrap_node_executor(executor, node_name, node_type)
                workflow.add_node(node_name, wrapped_executor)
        else:
            # 单个节点时使用串行创建
            for node in self.nodes:
                node_name = self._get_node_name(node)
                node_type = self._node_types[node.id]

                executor = await self._get_or_create_executor(node, node_name)
                wrapped_executor = self._wrap_node_executor(executor, node_name, node_type)

                workflow.add_node(node_name, wrapped_executor)

        # Step 3: Identify and build conditional edges for router/condition/loop nodes
        router_nodes = []
        condition_nodes = []
        loop_nodes = []

        for node in self.nodes:
            node_type = self._node_types[node.id]
            node_name = self._node_id_to_name[node.id]

            if node_type == "router_node":
                router_nodes.append((node, node_name))
            elif node_type == "condition":
                condition_nodes.append((node, node_name))
            elif node_type == "loop_condition_node":
                loop_nodes.append((node, node_name))

        # Build conditional edges for router nodes
        for router_node, router_node_name in router_nodes:
            executor = await self._get_or_create_executor(router_node, router_node_name)
            if isinstance(executor, RouterNodeExecutor):
                self._build_conditional_edges_for_router(workflow, router_node, router_node_name, executor)

        # Build conditional edges for condition nodes
        for condition_node, condition_node_name in condition_nodes:
            executor = await self._get_or_create_executor(condition_node, condition_node_name)
            if isinstance(executor, ConditionNodeExecutor):
                self._build_conditional_edges_for_condition(workflow, condition_node, condition_node_name, executor)

        # Build conditional edges for loop nodes
        for loop_node, loop_node_name in loop_nodes:
            executor = await self._get_or_create_executor(loop_node, loop_node_name)
            if isinstance(executor, LoopConditionNodeExecutor):
                self._build_conditional_edges_for_loop(workflow, loop_node, loop_node_name, executor)

        # Step 4: Add START edges
        start_nodes = self._find_start_nodes()

        # Special case: Loop condition nodes should be start nodes even if they have loop-back edges
        # Check if any loop condition nodes are missing from start_nodes
        loop_condition_start_nodes = []
        for node in self.nodes:
            node_type = self._node_types[node.id]
            if node_type == "loop_condition_node":
                # Check if this loop condition node is already in start_nodes
                is_already_start = any(sn.id == node.id for sn in start_nodes)

                if not is_already_start:
                    node_name = self._node_id_to_name[node.id]
                    # Check if all incoming edges are from loop body nodes (loop-back edges)
                    incoming_from_loop_body_only = True
                    if node.id in self._incoming_edges:
                        for source_node_id in self._incoming_edges[node.id]:
                            source_node = self._node_map.get(source_node_id)
                            if source_node:
                                source_node_name = self._get_node_name(source_node)
                                # Check if source is a loop body that maps to this loop condition
                                if source_node_name in self._loop_body_map:
                                    mapped_loop_condition = self._loop_body_map[source_node_name]
                                    if mapped_loop_condition != node_name:
                                        # This loop body belongs to a different loop condition
                                        incoming_from_loop_body_only = False
                                        break
                                else:
                                    # Source is not a loop body, so this is not a loop-back edge
                                    incoming_from_loop_body_only = False
                                    break

                    # If all incoming edges are from loop body (or no incoming edges), it's a start node
                    if incoming_from_loop_body_only:
                        loop_condition_start_nodes.append(node)
                        logger.debug(
                            f"[LanggraphModelBuilder] Identified loop condition as start node | node={node_name}"
                        )

        # Add START edges for regular start nodes
        for node in start_nodes:
            node_name = self._node_id_to_name[node.id]
            workflow.add_edge(START, node_name)

        # Add START edges for loop condition start nodes
        for node in loop_condition_start_nodes:
            node_name = self._node_id_to_name[node.id]
            workflow.add_edge(START, node_name)

        # Step 5: Add regular edges (supports parallel execution)
        edges_added = self._add_regular_edges(workflow)

        # Step 6: Add END edges
        end_nodes = self._find_end_nodes()
        for node in end_nodes:
            node_name = self._node_id_to_name[node.id]
            # Only add END edge if node doesn't have conditional edges
            if node_name not in self._conditional_nodes:
                workflow.add_edge(node_name, END)

        # Step 7: Collect interrupt configurations
        interrupt_before: List[str] = []
        interrupt_after: List[str] = []

        for node in self.nodes:
            node_name = self._node_id_to_name[node.id]
            data = node.data or {}
            config = data.get("config", {})

            # Check for interrupt_before configuration
            if config.get("interrupt_before", False):
                interrupt_before.append(node_name)
                logger.debug(f"[LanggraphModelBuilder] Node '{node_name}' configured for interrupt_before")

            # Check for interrupt_after configuration
            if config.get("interrupt_after", False):
                interrupt_after.append(node_name)
                logger.debug(f"[LanggraphModelBuilder] Node '{node_name}' configured for interrupt_after")

        if interrupt_before or interrupt_after:
            logger.info(
                f"[LanggraphModelBuilder] Interrupt configuration | "
                f"interrupt_before={len(interrupt_before)} | interrupt_after={len(interrupt_after)}"
            )

        # Step 8: Compile the workflow with interrupt configuration
        from app.core.agent.checkpointer.checkpointer import get_checkpointer

        compiled = workflow.compile(
            checkpointer=get_checkpointer(),
            interrupt_before=interrupt_before if interrupt_before else None,
            interrupt_after=interrupt_after if interrupt_after else None,
        )

        elapsed_ms = (time.time() - build_start_time) * 1000
        logger.info(
            f"[LanggraphModelBuilder] ========== Build complete ========== | "
            f"nodes={len(self.nodes)} | edges={edges_added} | "
            f"conditional_nodes={len(self._conditional_nodes)} | elapsed={elapsed_ms:.2f}ms"
        )

        return compiled
