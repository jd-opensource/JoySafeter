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
        return "Compilation errors:\n" + "\n".join(
            f"  - {e}" for e in self.errors
        )


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
    start_time = time.time()
    warnings: List[str] = []

    logger.info(
        f"[GraphCompiler] ========== Starting schema compilation ========== | "
        f"name='{schema.name}' | nodes={len(schema.nodes)} | edges={len(schema.edges)}"
    )

    # ------------------------------------------------------------------
    # Step 0: Generate state class
    # ------------------------------------------------------------------
    if schema.state_fields:
        state_class = build_state_class(
            schema.state_fields,
            extend_default=schema.use_default_state,
            class_name=f"{schema.name.replace(' ', '')}State",
        )
        logger.info(
            f"[GraphCompiler] Built dynamic state class with "
            f"{len(schema.state_fields)} custom fields"
        )
    else:
        state_class = GraphState

    # ------------------------------------------------------------------
    # Step 0.5: Validate state dependencies
    # ------------------------------------------------------------------
    if validate and schema.state_fields:
        dep_warnings = schema.validate_state_dependencies()
        if dep_warnings:
            warnings.extend(dep_warnings)
            for w in dep_warnings:
                logger.warning(f"[GraphCompiler] {w}")

    # ------------------------------------------------------------------
    # Step 1: Handle empty graph
    # ------------------------------------------------------------------
    if not schema.nodes:
        logger.warning("[GraphCompiler] No nodes — creating pass-through graph")
        workflow = StateGraph(state_class)

        async def pass_through(state: GraphState) -> Dict[str, Any]:
            return {"messages": [AIMessage(content="No workflow nodes configured.")]}

        workflow.add_node("pass_through", pass_through)
        workflow.add_edge(START, "pass_through")
        workflow.add_edge("pass_through", END)

        if checkpointer is None and builder is not None:
            from app.core.agent.checkpointer.checkpointer import get_checkpointer
            checkpointer = get_checkpointer()

        compiled = workflow.compile(checkpointer=checkpointer)
        elapsed = (time.time() - start_time) * 1000
        logger.info(f"[GraphCompiler] Empty graph compiled | elapsed={elapsed:.2f}ms")
        return CompilationResult(
            compiled, schema, state_class,
            build_time_ms=elapsed, warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Step 2: Pre-compute type and name maps
    # ------------------------------------------------------------------
    node_type_map: Dict[str, str] = {}
    node_name_map: Dict[str, str] = {}
    used_names: Set[str] = set()

    for node in schema.nodes:
        node_type_map[node.id] = node.type

        # Generate unique name
        base = node.label or node.type
        name = _unique_name(base, used_names)
        used_names.add(name)
        node_name_map[node.id] = name

    # ------------------------------------------------------------------
    # Step 3: Identify loop bodies and parallel nodes
    # ------------------------------------------------------------------
    loop_body_map = _identify_loop_bodies(schema, node_type_map)
    parallel_nodes = _identify_parallel_nodes(schema, node_type_map)

    logger.info(
        f"[GraphCompiler] Identified {len(loop_body_map)} loop body nodes | "
        f"{len(parallel_nodes)} parallel nodes"
    )

    # ------------------------------------------------------------------
    # Step 4: Create executors and add nodes
    # ------------------------------------------------------------------
    workflow = StateGraph(state_class)
    
    # Resolve fallback node name if configured
    fallback_node_name: Optional[str] = None
    if schema.fallback_node_id:
        fallback_node_name = node_name_map.get(schema.fallback_node_id)
        if fallback_node_name:
            logger.info(f"[GraphCompiler] Global error fallback enabled -> {fallback_node_name}")

    if builder is not None:
        # Delegate executor creation to the builder
        executors = await _create_executors_via_builder(
            schema, builder, node_name_map,
        )

        for node in schema.nodes:
            name = node_name_map[node.id]
            executor = executors[node.id]
            wrapped = NodeExecutionWrapper(
                executor,
                node_id=str(node.id),
                node_type=node.type,
                metadata=node.metadata,
                fallback_node_name=fallback_node_name if node.id != schema.fallback_node_id else None,
            )
            workflow.add_node(name, wrapped)
    else:
        # No builder — add stub nodes (for validation / code gen only)
        for node in schema.nodes:
            name = node_name_map[node.id]

            async def _stub_node(state: GraphState, _n: NodeSchema = node) -> Dict[str, Any]:
                return {"current_node": _n.label}

            workflow.add_node(name, _stub_node)

    # ------------------------------------------------------------------
    # Step 5: Build edges
    # ------------------------------------------------------------------
    # Collect edges by source for grouping
    edges_by_source: Dict[str, List] = {}
    for edge in schema.edges:
        edges_by_source.setdefault(edge.source, []).append(edge)

    # Classify nodes for edge building
    conditional_node_ids = set()
    router_node_ids = set()
    loop_node_ids = set()
    condition_node_ids = set()

    for node in schema.nodes:
        if node.type == "router_node":
            router_node_ids.add(node.id)
            conditional_node_ids.add(node.id)
        elif node.type == "condition":
            condition_node_ids.add(node.id)
            conditional_node_ids.add(node.id)
        elif node.type == "loop_condition_node":
            loop_node_ids.add(node.id)
            conditional_node_ids.add(node.id)

    # Build conditional edges for router/condition/loop nodes
    if builder is not None:
        for node_id in router_node_ids:
            name = node_name_map[node_id]
            executor = executors[node_id]
            if isinstance(executor, RouterNodeExecutor):
                _build_router_conditional_edges(
                    workflow, schema, node_id, name, executor,
                    node_name_map, edges_by_source,
                )

        for node_id in condition_node_ids:
            name = node_name_map[node_id]
            executor = executors[node_id]
            if isinstance(executor, ConditionNodeExecutor):
                _build_condition_conditional_edges(
                    workflow, schema, node_id, name, executor,
                    node_name_map, edges_by_source,
                )

        for node_id in loop_node_ids:
            name = node_name_map[node_id]
            executor = executors[node_id]
            if isinstance(executor, LoopConditionNodeExecutor):
                _build_loop_conditional_edges(
                    workflow, schema, node_id, name, executor,
                    node_name_map, edges_by_source,
                )



    # Build normal (non-conditional) edges
    for edge in schema.edges:
        if edge.source in conditional_node_ids:
            continue  # Already handled above

        source_name = node_name_map[edge.source]
        target_name = node_name_map[edge.target]
        workflow.add_edge(source_name, target_name)

    # ------------------------------------------------------------------
    # Step 6: START / END edges
    # ------------------------------------------------------------------
    start_nodes = schema.get_start_nodes()
    end_nodes = schema.get_end_nodes()

    if start_nodes:
        if len(start_nodes) == 1:
            workflow.add_edge(START, node_name_map[start_nodes[0].id])
        else:
            # Multiple start nodes — fan-out from START
            for sn in start_nodes:
                workflow.add_edge(START, node_name_map[sn.id])

    for en in end_nodes:
        en_name = node_name_map[en.id]
        # Don't add END edge if node already has conditional edges
        if en.id not in conditional_node_ids:
            workflow.add_edge(en_name, END)

    # ------------------------------------------------------------------
    # Step 7: Compile with interrupts and checkpointer
    # ------------------------------------------------------------------
    interrupt_before = [
        node_name_map[n.id] for n in schema.nodes if n.interrupt_before
    ]
    interrupt_after = [
        node_name_map[n.id] for n in schema.nodes if n.interrupt_after
    ]

    if checkpointer is None and builder is not None:
        from app.core.agent.checkpointer.checkpointer import get_checkpointer
        checkpointer = get_checkpointer()

    compile_kwargs: Dict[str, Any] = {}
    if checkpointer:
        compile_kwargs["checkpointer"] = checkpointer
    if interrupt_before:
        compile_kwargs["interrupt_before"] = interrupt_before
        logger.info(f"[GraphCompiler] interrupt_before: {interrupt_before}")
    if interrupt_after:
        compile_kwargs["interrupt_after"] = interrupt_after
        logger.info(f"[GraphCompiler] interrupt_after: {interrupt_after}")

    compiled = workflow.compile(**compile_kwargs)

    elapsed = (time.time() - start_time) * 1000
    logger.info(
        f"[GraphCompiler] ========== Compilation complete ========== | "
        f"elapsed={elapsed:.2f}ms | nodes={len(schema.nodes)} | edges={len(schema.edges)}"
    )

    return CompilationResult(
        compiled, schema, state_class,
        build_time_ms=elapsed, warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _unique_name(base: str, used: Set[str]) -> str:
    """Generate a unique node name from a base label."""
    # Sanitize: replace spaces, keep alphanum and underscores
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
    """Create all node executors using the builder's _create_node_executor.

    Returns a dict mapping node_id → executor instance.
    """
    # Build a node_id → db node mapping from the builder's node list
    db_node_by_id = {}
    for db_node in builder.nodes:
        db_node_by_id[str(db_node.id)] = db_node

    # Register name mappings with the builder
    for node_id, name in node_name_map.items():
        builder._node_id_to_name[_to_uuid(node_id)] = name

    # Create executors in parallel
    tasks = []
    node_ids = []

    for node in schema.nodes:
        db_node = db_node_by_id.get(node.id)
        if db_node is None:
            logger.warning(
                f"[GraphCompiler] No DB node found for schema node {node.id}, skipping"
            )
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


def _identify_loop_bodies(
    schema: GraphSchema, node_type_map: Dict[str, str],
) -> Dict[str, str]:
    """Identify nodes that are loop bodies (loop_back edges point to them)."""
    loop_body_map: Dict[str, str] = {}
    for edge in schema.edges:
        if edge.edge_type == EdgeType.LOOP_BACK:
            loop_body_map[edge.target] = edge.source
    return loop_body_map


def _identify_parallel_nodes(
    schema: GraphSchema, node_type_map: Dict[str, str],
) -> Set[str]:
    """Identify nodes that are fan-out (have multiple outgoing normal edges)."""
    out_counts: Dict[str, int] = {}
    for edge in schema.edges:
        if edge.edge_type == EdgeType.NORMAL:
            out_counts[edge.source] = out_counts.get(edge.source, 0) + 1
    return {nid for nid, cnt in out_counts.items() if cnt > 1}



# ---------------------------------------------------------------------------
# Conditional edge builders
# ---------------------------------------------------------------------------


def _build_router_conditional_edges(
    workflow: StateGraph,
    schema: GraphSchema,
    node_id: str,
    node_name: str,
    executor: RouterNodeExecutor,
    node_name_map: Dict[str, str],
    edges_by_source: Dict[str, list],
) -> None:
    """Build conditional edges for a router node."""
    conditional_map: Dict[str, str] = {}
    handle_to_route_map: Dict[str, str] = {}

    for edge in edges_by_source.get(node_id, []):
        route_key = edge.route_key or "default"
        target_name = node_name_map.get(edge.target)
        if target_name:
            conditional_map[route_key] = target_name
        if edge.source_handle_id:
            handle_to_route_map[edge.source_handle_id] = route_key

    if conditional_map:
        if handle_to_route_map:
            executor.set_handle_to_route_map(handle_to_route_map)

        workflow.add_conditional_edges(
            node_name,
            executor.route,
            conditional_map,
        )
        logger.info(
            f"[GraphCompiler] Router edges: {node_name} -> {conditional_map}"
        )


def _build_condition_conditional_edges(
    workflow: StateGraph,
    schema: GraphSchema,
    node_id: str,
    node_name: str,
    executor: ConditionNodeExecutor,
    node_name_map: Dict[str, str],
    edges_by_source: Dict[str, list],
) -> None:
    """Build conditional edges for a condition node (true/false branches)."""
    conditional_map: Dict[str, str] = {}

    for edge in edges_by_source.get(node_id, []):
        route_key = edge.route_key or "default"
        target_name = node_name_map.get(edge.target)
        if target_name:
            conditional_map[route_key] = target_name

    if conditional_map:
        workflow.add_conditional_edges(
            node_name,
            executor.route,
            conditional_map,
        )
        logger.info(
            f"[GraphCompiler] Condition edges: {node_name} -> {conditional_map}"
        )


def _build_loop_conditional_edges(
    workflow: StateGraph,
    schema: GraphSchema,
    node_id: str,
    node_name: str,
    executor: LoopConditionNodeExecutor,
    node_name_map: Dict[str, str],
    edges_by_source: Dict[str, list],
) -> None:
    """Build conditional edges for a loop condition node."""
    conditional_map: Dict[str, str] = {}

    for edge in edges_by_source.get(node_id, []):
        route_key = edge.route_key or "default"
        target_name = node_name_map.get(edge.target)
        if target_name:
            # Map loop-specific route keys
            if route_key in ("continue_loop", "continue"):
                conditional_map["continue_loop"] = target_name
            elif route_key in ("exit_loop", "exit"):
                conditional_map["exit_loop"] = target_name
            else:
                conditional_map[route_key] = target_name

    if conditional_map:
        workflow.add_conditional_edges(
            node_name,
            executor.route,
            conditional_map,
        )
        logger.info(
            f"[GraphCompiler] Loop edges: {node_name} -> {conditional_map}"
        )



