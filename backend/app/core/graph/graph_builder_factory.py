"""
Graph Builder — entry point for building graphs from database definitions.

Only DeepAgents mode remains. Code mode bypasses this entirely
(handled by code_executor.py in graph_service).
"""

from typing import Any, List, Optional

from langgraph.graph.state import CompiledStateGraph
from loguru import logger

from app.core.graph.base_graph_builder import DEEPAGENTS_AVAILABLE, BaseGraphBuilder
from app.core.graph.deep_agents_builder import DeepAgentsGraphBuilder
from app.models.graph import AgentGraph, GraphEdge, GraphNode


class GraphBuilder:
    """Builds a compiled graph from DB node/edge definitions (DeepAgents only)."""

    def __init__(
        self,
        graph: AgentGraph,
        nodes: List[GraphNode],
        edges: List[GraphEdge],
        llm_model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        max_tokens: int = 4096,
        user_id: Optional[Any] = None,
        model_service: Optional[Any] = None,
        thread_id: Optional[str] = None,
        **kwargs,
    ):
        self.graph = graph
        self.nodes = nodes
        self.edges = edges
        self.llm_model = llm_model
        self.api_key = api_key
        self.base_url = base_url
        self.max_tokens = max_tokens
        self.user_id = user_id
        self.model_service = model_service
        self.thread_id = thread_id
        self.file_emitter = kwargs.pop("file_emitter", None)

    async def build(self) -> CompiledStateGraph:
        """Build and return a compiled StateGraph."""
        if not DEEPAGENTS_AVAILABLE:
            raise RuntimeError(
                "DeepAgents is not available. Install the deepagents package."
            )

        logger.info("[GraphBuilder] Building DeepAgents graph")
        builder = DeepAgentsGraphBuilder(
            self.graph,
            self.nodes,
            self.edges,
            self.llm_model,
            self.api_key,
            self.base_url,
            self.max_tokens,
            self.user_id,
            self.model_service,
            thread_id=self.thread_id,
            file_emitter=self.file_emitter,
        )
        return await builder.build()
