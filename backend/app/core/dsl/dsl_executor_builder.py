"""DSLExecutorBuilder — construct executor instances from GraphSchema.

Builds a ``{node_id: executor}`` map without requiring DB ``GraphNode`` rows.
A lightweight ``_NodeSchemaShim`` satisfies the ``node.data["config"]`` access
pattern that all existing executor constructors rely on.
"""

from __future__ import annotations

from typing import Any, Optional

from loguru import logger

from app.core.graph.graph_schema import GraphSchema, NodeSchema


# ---------------------------------------------------------------------------
# Shim: makes a NodeSchema look like a GraphNode for executor constructors
# ---------------------------------------------------------------------------


class _NodeSchemaShim:
    """Minimal shim satisfying ``GraphNode.data["config"]`` access pattern.

    Executor constructors read ``self.node.data["config"]`` and sometimes
    ``self.node.data["label"]``.  This shim provides exactly that interface
    without touching the database.
    """

    def __init__(self, node: NodeSchema) -> None:
        self.id = node.id
        self.type = node.type
        self.data: dict[str, Any] = {
            "config": dict(node.config),
            "label": node.label,
            "type": node.type,
        }
        self.config = node.config  # direct access alias


class DSLExecutorBuilder:
    """Build executor instances for all nodes in a ``GraphSchema``.

    Parameters
    ----------
    schema : GraphSchema
        The parsed graph schema.
    model_service : ModelService
        Service for resolving LLM model names to model instances.
    user_id : str | None
        Current user ID (needed for tool resolution).
    llm_model, api_key, base_url, max_tokens
        Default LLM parameters (can be overridden per-node).
    """

    def __init__(
        self,
        schema: GraphSchema,
        model_service: Any,
        user_id: Any,
        llm_model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        max_tokens: int = 4096,
    ) -> None:
        self._schema = schema
        self._model_service = model_service
        self._user_id = user_id
        self._llm_model = llm_model
        self._api_key = api_key
        self._base_url = base_url
        self._max_tokens = max_tokens

    async def build_executors(self) -> dict[str, Any]:
        """Return ``{node_id: executor}`` for every node in the schema."""
        executor_map: dict[str, Any] = {}
        for node in self._schema.nodes:
            try:
                executor = await self._create_executor(node)
                executor_map[node.id] = executor
            except Exception:
                logger.exception(
                    f"[DSLExecutorBuilder] Failed to create executor for "
                    f"node '{node.id}' (type={node.type})"
                )
                raise
        return executor_map

    async def _create_executor(self, node: NodeSchema) -> Any:
        """Instantiate the correct executor for *node*."""
        shim = _NodeSchemaShim(node)
        node_id = node.id

        if node.type == "agent":
            return await self._create_agent_executor(shim, node_id, node)
        elif node.type == "condition":
            from app.core.graph.executors.logic import ConditionNodeExecutor

            return ConditionNodeExecutor(shim, node_id)
        elif node.type == "router_node":
            from app.core.graph.executors.logic import RouterNodeExecutor

            return RouterNodeExecutor(shim, node_id)
        elif node.type == "function_node":
            from app.core.graph.executors.tool import FunctionNodeExecutor

            return FunctionNodeExecutor(shim, node_id)
        elif node.type == "http_request_node":
            from app.core.graph.executors.action import HttpRequestNodeExecutor

            return HttpRequestNodeExecutor(shim, node_id)
        elif node.type == "direct_reply":
            from app.core.graph.executors.action import DirectReplyNodeExecutor

            return DirectReplyNodeExecutor(shim, node_id)
        elif node.type == "human_input":
            from app.core.graph.executors.action import HumanInputNodeExecutor

            return HumanInputNodeExecutor(shim, node_id)
        elif node.type == "tool_node":
            from app.core.graph.executors.tool import ToolNodeExecutor

            return ToolNodeExecutor(shim, node_id, user_id=self._user_id)
        else:
            raise ValueError(
                f"Unsupported node type '{node.type}' for DSL executor builder"
            )

    async def _create_agent_executor(
        self, shim: _NodeSchemaShim, node_id: str, node: NodeSchema
    ) -> Any:
        """Create an AgentNodeExecutor with resolved model."""
        from app.core.graph.executors.agent import AgentNodeExecutor

        # Resolve model — same priority as BaseGraphBuilder._resolve_node_llm
        model_name = node.config.get("model") or self._llm_model
        resolved_model = None

        if self._model_service and model_name:
            try:
                resolved_model = await self._model_service.resolve_model(
                    model_name,
                    api_key=self._api_key,
                    base_url=self._base_url,
                    max_tokens=self._max_tokens,
                    user_id=self._user_id,
                )
            except Exception:
                logger.warning(
                    f"[DSLExecutorBuilder] Model resolution failed for "
                    f"'{model_name}', falling back to default"
                )

        return AgentNodeExecutor(
            shim,
            node_id,
            llm_model=self._llm_model,
            api_key=self._api_key,
            base_url=self._base_url,
            max_tokens=self._max_tokens,
            user_id=self._user_id,
            resolved_model=resolved_model,
        )
