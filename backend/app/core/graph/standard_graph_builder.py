"""
LangGraph Model Builder - Builds standard LangGraph with START/END nodes.

Implements the standard workflow pattern with explicit START and END nodes.
delegating to GraphCompiler for the actual graph construction.
"""

import asyncio
from typing import Any, Dict, Optional

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from loguru import logger

try:
    from cachetools import TTLCache  # type: ignore[import-untyped]

    CACHE_AVAILABLE = True
except ImportError:
    # Fallback to dict if cachetools not available
    TTLCache = dict  # type: ignore[assignment, misc]
    CACHE_AVAILABLE = False
    logger.warning("[LanggraphModelBuilder] cachetools not available, using dict cache")

from app.core.graph.base_graph_builder import BaseGraphBuilder
from app.core.graph.graph_compiler import CompilationResult, compile_from_schema
from app.core.graph.graph_schema import GraphSchema
from app.core.graph.graph_state import GraphState


class LanggraphModelBuilder(BaseGraphBuilder):
    """Builds standard LangGraph with START/END nodes using GraphCompiler.

    Delegates to GraphCompiler for:
    - Conditional routing (RouterNodeExecutor, ConditionNodeExecutor)
    - Loops (LoopConditionNodeExecutor)
    - Parallel execution (Fan-Out/Fan-In)
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Cache executors to avoid recreating them (thread-safe with lock and TTL)
        if CACHE_AVAILABLE:
            self._executor_cache = TTLCache(maxsize=1000, ttl=300)  # 5 minutes TTL
        else:
            self._executor_cache: Dict[str, Any] = {}
        self._executor_cache_lock = asyncio.Lock()

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

    def _to_schema(self) -> GraphSchema:
        """Convert the builder's DB models to a GraphSchema."""
        return GraphSchema.from_db(self.graph, self.nodes, self.edges)

    async def build_from_schema(
        self,
        schema: Optional[GraphSchema] = None,
    ) -> CompilationResult:
        """Build graph via the schema-based compiler pipeline.

        This is the new, preferred build path.  It converts DB models to
        a ``GraphSchema``, then compiles via ``compile_from_schema``.

        Parameters
        ----------
        schema : GraphSchema, optional
            Pre-built schema.  If ``None``, one is generated from the
            builder's DB models via ``_to_schema()``.

        Returns
        -------
        CompilationResult
            Contains the compiled graph plus diagnostics.
        """
        if schema is None:
            schema = self._to_schema()

        from app.core.agent.checkpointer.checkpointer import get_checkpointer

        result = await compile_from_schema(
            schema,
            builder=self,
            checkpointer=get_checkpointer(),
            validate=True,
        )

        if result.warnings:
            for w in result.warnings:
                logger.warning(f"[LanggraphModelBuilder] {w}")

        return result

    async def build(self) -> Any:  # type: ignore[override]
        """Build LangGraph StateGraph (Schema-Driven).

        Delegates to ``build_from_schema`` and returns the compiled
        LangGraph runnable.
        """
        # If no nodes, return pass-through empty graph
        if not self.nodes:
            logger.warning("[LanggraphModelBuilder] No nodes, creating pass-through graph")
            workflow = StateGraph(GraphState)

            async def pass_through(state: GraphState) -> Dict[str, Any]:
                return {"messages": [AIMessage(content="No workflow nodes configured.")]}

            workflow.add_node("pass_through", pass_through)
            workflow.add_edge(START, "pass_through")
            workflow.add_edge("pass_through", END)
            
            from app.core.agent.checkpointer.checkpointer import get_checkpointer
            return workflow.compile(checkpointer=get_checkpointer())

        # Schema-driven build
        result = await self.build_from_schema()
        return result.compiled_graph
