"""
Graph Builder - Factory class that selects appropriate builder.

Main entry point for building graphs from database definitions.
Automatically detects if DeepAgents mode should be used and delegates
to the appropriate builder implementation.
"""

from typing import Any, List, Optional

from langgraph.graph.state import CompiledStateGraph
from loguru import logger

# Import DEEPAGENTS_AVAILABLE from base_graph_builder
from app.core.graph.base_graph_builder import DEEPAGENTS_AVAILABLE, BaseGraphBuilder
from app.core.graph.deep_agents_builder import DeepAgentsGraphBuilder
from app.core.graph.standard_graph_builder import LanggraphModelBuilder
from app.models.graph import AgentGraph, GraphEdge, GraphNode


class GraphBuilder:
    """
    Factory class that selects appropriate builder based on graph configuration.

    Automatically detects if DeepAgents mode should be used and delegates
    to the appropriate builder implementation.

    使用方式：await builder.build()
    """

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
    ):
        self.graph = graph
        self.nodes = nodes
        self.edges = edges
        self.llm_model = llm_model
        self.api_key = api_key
        self.base_url = base_url
        self.max_tokens = max_tokens
        self.user_id = user_id
        # 可选：传入 ModelService，便于在 Builder 中按 model_name 解析模型
        self.model_service = model_service

    def _has_deep_agents_nodes(self) -> bool:
        """Check if any node has DeepAgents enabled."""
        if not DEEPAGENTS_AVAILABLE:
            return False
        for node in self.nodes:
            data = node.data or {}
            config = data.get("config", {})
            if config.get("useDeepAgents", False) is True:
                return True
        return False

    def _create_builder(self) -> BaseGraphBuilder:
        """创建合适的构建器实例。"""
        if self._has_deep_agents_nodes():
            logger.info("[GraphBuilder] Detected DeepAgents nodes, using DeepAgentsGraphBuilder")
            return DeepAgentsGraphBuilder(
                self.graph,
                self.nodes,
                self.edges,
                self.llm_model,
                self.api_key,
                self.base_url,
                self.max_tokens,
                self.user_id,
                self.model_service,
            )
        else:
            logger.debug("[GraphBuilder] No DeepAgents nodes, using LanggraphModelBuilder")
            return LanggraphModelBuilder(
                self.graph,
                self.nodes,
                self.edges,
                self.llm_model,
                self.api_key,
                self.base_url,
                self.max_tokens,
                self.user_id,
                self.model_service,
            )

    async def build(self) -> CompiledStateGraph:
        """
        异步构建并编译 StateGraph。

        自动选择 LanggraphModelBuilder 或 DeepAgentsGraphBuilder。

        使用方式：await builder.build()
        """
        logger.info(
            f"[GraphBuilder] ========== Starting graph build ========== | "
            f"graph='{self.graph.name}' | graph_id={self.graph.id}"
        )

        builder = self._create_builder()
        result = await builder.build()  # type: ignore[misc]
        return result  # type: ignore
