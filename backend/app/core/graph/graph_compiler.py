"""
Graph Compiler — Schema-to-LangGraph compilation.

Provides a stateless ``compile_from_schema`` function that transforms a
``GraphSchema`` into a compiled LangGraph ``StateGraph``.  The compiler
delegates executor creation to the builder (which handles LLM resolution
and service access) but owns the graph wiring logic.

Usage
-----
Direct compilation from a schema::

    from app.core.graph.graph_compiler import compile_from_schema
    compiled = await compile_from_schema(schema, builder=my_builder)

Via the refactored builder (backward-compatible)::

    compiled = await builder.build()  # internally calls compile_from_schema
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Set

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from loguru import logger

try:
    from langgraph.types import Command

    COMMAND_AVAILABLE = True
except ImportError:
    COMMAND_AVAILABLE = False
    Command = None  # type: ignore[assignment, misc]

from app.core.graph.graph_schema import EdgeType, GraphSchema, NodeSchema
from app.core.graph.graph_state import GraphState, build_state_class
from app.core.graph.node_executors import (
    ConditionNodeExecutor,
    LoopConditionNodeExecutor,
    RouterNodeExecutor,
)
from app.core.graph.node_wrapper import NodeExecutionWrapper

# ---------------------------------------------------------------------------
# Helper types
# ---------------------------------------------------------------------------


class CompilationResult:
    """Result of a graph compilation."""

    def __init__(
        self,
        compiled_graph: Any,
        schema: GraphSchema,
        state_class: type,
        *,
        build_time_ms: float = 0.0,
        warnings: Optional[List[str]] = None,
    ):
        self.compiled_graph = compiled_graph
        self.schema = schema
        self.state_class = state_class
        self.build_time_ms = build_time_ms
        self.warnings: List[str] = warnings or []


class CompilationError(Exception):
    """Raised when graph compilation fails."""

    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__(f"Compilation failed with {len(errors)} error(s)")

    def __str__(self) -> str:
        return "Compilation errors:\n" + "\n".join(f"  - {e}" for e in self.errors)


# ---------------------------------------------------------------------------
# Compiler Session
# ---------------------------------------------------------------------------


class _CompilerSession:
    """Encapsulates the state and step-by-step logic for graph compilation."""

    def __init__(
        self,
        schema: GraphSchema,
        builder: Any,
        checkpointer: Any,
        validate: bool,
    ):
        self.schema = schema
        self.builder = builder
        self.checkpointer = checkpointer
        self.validate = validate

        self.start_time = time.time()
        self.warnings: List[str] = []
        self.state_class = GraphState

        self.node_type_map: Dict[str, str] = {}
        self.node_name_map: Dict[str, str] = {}
        self.used_names: Set[str] = set()

        self.conditional_node_ids: Set[str] = set()
        self.router_node_ids: Set[str] = set()
        self.condition_node_ids: Set[str] = set()
        self.loop_node_ids: Set[str] = set()
        self.edges_by_source: Dict[str, List] = {}

        self.executors: Dict[str, Any] = {}
        self.workflow: StateGraph = None

    async def compile(self) -> CompilationResult:
        logger.info(
            f"[GraphCompiler] ========== Starting schema compilation ========== | "
            f"name='{self.schema.name}' | nodes={len(self.schema.nodes)} | edges={len(self.schema.edges)}"
        )

        self._generate_state_class()
        self._validate_state_dependencies()

        if not self.schema.nodes:
            return self._handle_empty_graph()

        self._precompute_maps()
        self._identify_node_classifications()

        self.workflow = StateGraph(self.state_class)
        await self._create_executors_and_nodes()
        self._build_conditional_edges()
        self._build_normal_edges()
        self._build_start_end_edges()

        compiled = self._compile_workflow()

        elapsed = (time.time() - self.start_time) * 1000
        logger.info(
            f"[GraphCompiler] ========== Compilation complete ========== | "
            f"elapsed={elapsed:.2f}ms | nodes={len(self.schema.nodes)} | edges={len(self.schema.edges)}"
        )
        return CompilationResult(
            compiled,
            self.schema,
            self.state_class,
            build_time_ms=elapsed,
            warnings=self.warnings,
        )

    def _generate_state_class(self):
        if self.schema.state_fields:
            self.state_class = build_state_class(
                self.schema.state_fields,
                extend_default=self.schema.use_default_state,
                class_name=f"{self.schema.name.replace(' ', '')}State",
            )
            logger.info(
                f"[GraphCompiler] Built dynamic state class with " f"{len(self.schema.state_fields)} custom fields"
            )

    def _validate_state_dependencies(self):
        if self.validate and self.schema.state_fields:
            dep_warnings = self.schema.validate_state_dependencies()
            if dep_warnings:
                self.warnings.extend(dep_warnings)
                for w in dep_warnings:
                    logger.warning(f"[GraphCompiler] {w}")

    def _handle_empty_graph(self) -> CompilationResult:
        logger.warning("[GraphCompiler] No nodes — creating pass-through graph")
        workflow = StateGraph(self.state_class)

        async def pass_through(state: GraphState) -> Dict[str, Any]:
            return {"messages": [AIMessage(content="No workflow nodes configured.")]}

        workflow.add_node("pass_through", pass_through)
        workflow.add_edge(START, "pass_through")
        workflow.add_edge("pass_through", END)

        if self.checkpointer is None and self.builder is not None:
            from app.core.agent.checkpointer.checkpointer import get_checkpointer

            self.checkpointer = get_checkpointer()

        compiled = workflow.compile(checkpointer=self.checkpointer)
        elapsed = (time.time() - self.start_time) * 1000
        logger.info(f"[GraphCompiler] Empty graph compiled | elapsed={elapsed:.2f}ms")
        return CompilationResult(
            compiled,
            self.schema,
            self.state_class,
            build_time_ms=elapsed,
            warnings=self.warnings,
        )

    def _precompute_maps(self):
        for node in self.schema.nodes:
            self.node_type_map[node.id] = node.type
            base = node.label or node.type
            name = _unique_name(base, self.used_names)
            self.used_names.add(name)
            self.node_name_map[node.id] = name

    def _identify_node_classifications(self):
        loop_body_map = _identify_loop_bodies(self.schema)
        parallel_nodes = _identify_parallel_nodes(self.schema)

        logger.info(
            f"[GraphCompiler] Identified {len(loop_body_map)} loop body nodes | "
            f"{len(parallel_nodes)} parallel nodes"
        )

        for edge in self.schema.edges:
            self.edges_by_source.setdefault(edge.source, []).append(edge)

        for node in self.schema.nodes:
            if node.type == "router_node":
                self.router_node_ids.add(node.id)
                self.conditional_node_ids.add(node.id)
            elif node.type == "condition":
                self.condition_node_ids.add(node.id)
                self.conditional_node_ids.add(node.id)
            elif node.type == "loop_condition_node":
                self.loop_node_ids.add(node.id)
                self.conditional_node_ids.add(node.id)

    async def _create_executors_and_nodes(self):
        fallback_node_name: Optional[str] = None
        if self.schema.fallback_node_id:
            fallback_node_name = self.node_name_map.get(self.schema.fallback_node_id)
            if fallback_node_name:
                logger.info(f"[GraphCompiler] Global error fallback enabled -> {fallback_node_name}")

        if self.builder is not None:
            self.executors = await _create_executors_via_builder(
                self.schema,
                self.builder,
                self.node_name_map,
            )

            for node in self.schema.nodes:
                name = self.node_name_map[node.id]
                executor = self.executors.get(node.id)
                if executor:
                    wrapped = NodeExecutionWrapper(
                        executor,
                        node_id=str(node.id),
                        node_type=node.type,
                        metadata=node.metadata,
                        fallback_node_name=fallback_node_name if node.id != self.schema.fallback_node_id else None,
                    )
                    self.workflow.add_node(name, wrapped)
        else:
            for node in self.schema.nodes:
                name = self.node_name_map[node.id]

                async def _stub_node(state: GraphState, _n: NodeSchema = node) -> Dict[str, Any]:
                    return {"current_node": _n.label}

                self.workflow.add_node(name, _stub_node)

    def _build_conditional_edges(self):
        if self.builder is None:
            return

        for node_id in self.router_node_ids:
            executor = self.executors.get(node_id)
            if isinstance(executor, RouterNodeExecutor):
                self._build_router_conditional_edges(node_id, executor)

        for node_id in self.condition_node_ids:
            executor = self.executors.get(node_id)
            if isinstance(executor, ConditionNodeExecutor):
                self._build_condition_conditional_edges(node_id, executor)

        for node_id in self.loop_node_ids:
            executor = self.executors.get(node_id)
            if isinstance(executor, LoopConditionNodeExecutor):
                self._build_loop_conditional_edges(node_id, executor)

    def _build_router_conditional_edges(self, node_id: str, executor: RouterNodeExecutor) -> None:
        conditional_map: Dict[str, str] = {}
        handle_to_route_map: Dict[str, str] = {}
        node_name = self.node_name_map[node_id]

        for edge in self.edges_by_source.get(node_id, []):
            route_key = edge.route_key or "default"
            target_name = self.node_name_map.get(edge.target)
            if target_name:
                conditional_map[route_key] = target_name
            if edge.source_handle_id:
                handle_to_route_map[edge.source_handle_id] = route_key

        if conditional_map:
            if handle_to_route_map:
                executor.set_handle_to_route_map(handle_to_route_map)

            self.workflow.add_conditional_edges(
                node_name,
                executor.route,
                conditional_map,
            )
            logger.info(f"[GraphCompiler] Router edges: {node_name} -> {conditional_map}")

    def _build_condition_conditional_edges(self, node_id: str, executor: ConditionNodeExecutor) -> None:
        conditional_map: Dict[str, str] = {}
        node_name = self.node_name_map[node_id]

        for edge in self.edges_by_source.get(node_id, []):
            route_key = edge.route_key or "default"
            target_name = self.node_name_map.get(edge.target)
            if target_name:
                conditional_map[route_key] = target_name

        if conditional_map:
            self.workflow.add_conditional_edges(
                node_name,
                executor.route,
                conditional_map,
            )
            logger.info(f"[GraphCompiler] Condition edges: {node_name} -> {conditional_map}")

    def _build_loop_conditional_edges(self, node_id: str, executor: LoopConditionNodeExecutor) -> None:
        conditional_map: Dict[str, str] = {}
        node_name = self.node_name_map[node_id]

        for edge in self.edges_by_source.get(node_id, []):
            route_key = edge.route_key or "default"
            target_name = self.node_name_map.get(edge.target)
            if target_name:
                if route_key in ("continue_loop", "continue"):
                    conditional_map["continue_loop"] = target_name
                elif route_key in ("exit_loop", "exit"):
                    conditional_map["exit_loop"] = target_name
                else:
                    conditional_map[route_key] = target_name

        if conditional_map:
            self.workflow.add_conditional_edges(
                node_name,
                executor.route,
                conditional_map,
            )
            logger.info(f"[GraphCompiler] Loop edges: {node_name} -> {conditional_map}")

    def _build_normal_edges(self):
        for edge in self.schema.edges:
            if edge.source in self.conditional_node_ids:
                continue
            source_name = self.node_name_map.get(edge.source)
            target_name = self.node_name_map.get(edge.target)
            if source_name and target_name:
                self.workflow.add_edge(source_name, target_name)

    def _build_start_end_edges(self):
        start_nodes = self.schema.get_start_nodes()
        end_nodes = self.schema.get_end_nodes()

        if start_nodes:
            if len(start_nodes) == 1:
                self.workflow.add_edge(START, self.node_name_map[start_nodes[0].id])
            else:
                for sn in start_nodes:
                    self.workflow.add_edge(START, self.node_name_map[sn.id])

        for en in end_nodes:
            if en.id not in self.conditional_node_ids:
                en_name = self.node_name_map.get(en.id)
                if en_name:
                    self.workflow.add_edge(en_name, END)

    def _compile_workflow(self) -> Any:
        interrupt_before = [self.node_name_map[n.id] for n in self.schema.nodes if n.interrupt_before]
        interrupt_after = [self.node_name_map[n.id] for n in self.schema.nodes if n.interrupt_after]

        if self.checkpointer is None and self.builder is not None:
            from app.core.agent.checkpointer.checkpointer import get_checkpointer

            self.checkpointer = get_checkpointer()

        compile_kwargs: Dict[str, Any] = {}
        if self.checkpointer:
            compile_kwargs["checkpointer"] = self.checkpointer
        if interrupt_before:
            compile_kwargs["interrupt_before"] = interrupt_before
            logger.info(f"[GraphCompiler] interrupt_before: {interrupt_before}")
        if interrupt_after:
            compile_kwargs["interrupt_after"] = interrupt_after
            logger.info(f"[GraphCompiler] interrupt_after: {interrupt_after}")

        return self.workflow.compile(**compile_kwargs)


# ---------------------------------------------------------------------------
# Core compilation
# ---------------------------------------------------------------------------


async def compile_from_schema(
    schema: GraphSchema,
    *,
    builder: Any = None,
    checkpointer: Any = None,
    validate: bool = True,
) -> CompilationResult:
    """Compile a ``GraphSchema`` into a runnable LangGraph ``StateGraph``.

    Parameters
    ----------
    schema : GraphSchema
        The graph definition to compile.
    builder : BaseGraphBuilder, optional
        A builder instance used for executor creation (LLM resolution, etc.).
        If ``None``, a lightweight compilation is performed (useful for
        validation-only or code-generation scenarios).
    checkpointer : optional
        LangGraph checkpointer instance.  If ``None`` and *builder* is
        provided, the default checkpointer is used.
    validate : bool
        Run structural validation before compilation.

    Returns
    -------
    CompilationResult
        Contains the compiled graph, schema, state class, and diagnostics.
    """
    session = _CompilerSession(schema=schema, builder=builder, checkpointer=checkpointer, validate=validate)
    return await session.compile()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _unique_name(base: str, used: Set[str]) -> str:
    """Generate a unique node name from a base label."""
    clean = "".join(c if c.isalnum() or c == "_" else "_" for c in base)
    if not clean or not clean[0].isalpha():
        clean = f"node_{clean}"

    if clean not in used:
        return clean

    counter = 2
    while f"{clean}_{counter}" in used:
        counter += 1
    return f"{clean}_{counter}"


async def _create_executors_via_builder(
    schema: GraphSchema,
    builder: Any,
    node_name_map: Dict[str, str],
) -> Dict[str, Any]:
    """Create all node executors using the builder's _create_node_executor."""
    db_node_by_id = {}
    for db_node in builder.nodes:
        db_node_by_id[str(db_node.id)] = db_node

    for node_id, name in node_name_map.items():
        builder._node_id_to_name[_to_uuid(node_id)] = name

    tasks = []
    node_ids = []

    for node in schema.nodes:
        db_node = db_node_by_id.get(node.id)
        if db_node is None:
            logger.warning(f"[GraphCompiler] No DB node found for schema node {node.id}, skipping")
            continue
        name = node_name_map[node.id]
        tasks.append(builder._get_or_create_executor(db_node, name))
        node_ids.append(node.id)

    executors_list = await asyncio.gather(*tasks)
    return dict(zip(node_ids, executors_list))


def _to_uuid(node_id: str) -> Any:
    """Convert string ID to UUID if possible."""
    import uuid as _uuid

    try:
        return _uuid.UUID(node_id)
    except (ValueError, AttributeError):
        return node_id


def _identify_loop_bodies(schema: GraphSchema) -> Dict[str, str]:
    """Identify nodes that are loop bodies (loop_back edges point to them)."""
    loop_body_map: Dict[str, str] = {}
    for edge in schema.edges:
        if edge.edge_type == EdgeType.LOOP_BACK:
            loop_body_map[edge.target] = edge.source
    return loop_body_map


def _identify_parallel_nodes(schema: GraphSchema) -> Set[str]:
    """Identify nodes that are fan-out (have multiple outgoing normal edges)."""
    out_counts: Dict[str, int] = {}
    for edge in schema.edges:
        if edge.edge_type == EdgeType.NORMAL:
            out_counts[edge.source] = out_counts.get(edge.source, 0) + 1
    return {nid for nid, cnt in out_counts.items() if cnt > 1}
