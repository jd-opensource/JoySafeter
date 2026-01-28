"""
Node Type Registry - Unified node type management.

Provides centralized registry for node types, mapping between frontend and backend,
and metadata about node capabilities.
"""

from typing import Dict, Optional, Type

from loguru import logger

from app.core.graph.node_executors import (
    AgentNodeExecutor,
    AggregatorNodeExecutor,
    CodeAgentNodeExecutor,
    ConditionNodeExecutor,
    DirectReplyNodeExecutor,
    FunctionNodeExecutor,
    HttpRequestNodeExecutor,
    JSONParserNodeExecutor,
    LoopConditionNodeExecutor,
    RouterNodeExecutor,
    ToolNodeExecutor,
)


class NodeTypeMetadata:
    """节点类型元数据。"""

    def __init__(
        self,
        executor_class: Type,
        frontend_type: str,
        supports_loop_body: bool = True,
        supports_parallel: bool = True,
        requires_handle_mapping: bool = False,
        description: str = "",
    ):
        self.executor_class = executor_class
        self.frontend_type = frontend_type
        self.supports_loop_body = supports_loop_body
        self.supports_parallel = supports_parallel
        self.requires_handle_mapping = requires_handle_mapping
        self.description = description


class NodeTypeRegistry:
    """节点类型注册表，统一管理前后端节点类型映射。"""

    _registry: Dict[str, NodeTypeMetadata] = {
        "agent": NodeTypeMetadata(
            executor_class=AgentNodeExecutor,
            frontend_type="agent",
            supports_loop_body=True,
            supports_parallel=True,
            requires_handle_mapping=False,
            description="LLM Agent node with tools and middleware support",
        ),
        "code_agent": NodeTypeMetadata(
            executor_class=CodeAgentNodeExecutor,
            frontend_type="code_agent",
            supports_loop_body=True,
            supports_parallel=True,
            requires_handle_mapping=False,
            description="Python code execution agent with Thought-Code-Observation loop",
        ),
        "condition": NodeTypeMetadata(
            executor_class=ConditionNodeExecutor,
            frontend_type="condition",
            supports_loop_body=False,
            supports_parallel=False,
            requires_handle_mapping=True,
            description="Simple if/else condition node",
        ),
        "router_node": NodeTypeMetadata(
            executor_class=RouterNodeExecutor,
            frontend_type="router",
            supports_loop_body=False,
            supports_parallel=False,
            requires_handle_mapping=True,
            description="Multi-rule router node for complex routing",
        ),
        "loop_condition_node": NodeTypeMetadata(
            executor_class=LoopConditionNodeExecutor,
            frontend_type="loop_condition",
            supports_loop_body=False,
            supports_parallel=False,
            requires_handle_mapping=True,
            description="Loop condition evaluation node",
        ),
        "direct_reply": NodeTypeMetadata(
            executor_class=DirectReplyNodeExecutor,
            frontend_type="direct_reply",
            supports_loop_body=True,
            supports_parallel=True,
            requires_handle_mapping=False,
            description="Direct reply with template substitution",
        ),
        "tool_node": NodeTypeMetadata(
            executor_class=ToolNodeExecutor,
            frontend_type="tool",
            supports_loop_body=True,
            supports_parallel=True,
            requires_handle_mapping=False,
            description="Tool execution node",
        ),
        "function_node": NodeTypeMetadata(
            executor_class=FunctionNodeExecutor,
            frontend_type="function",
            supports_loop_body=True,
            supports_parallel=True,
            requires_handle_mapping=False,
            description="Custom function execution node (requires sandboxing)",
        ),
        "aggregator_node": NodeTypeMetadata(
            executor_class=AggregatorNodeExecutor,
            frontend_type="aggregator",
            supports_loop_body=False,
            supports_parallel=False,
            requires_handle_mapping=False,
            description="Fan-In aggregator node for parallel results",
        ),
        "json_parser_node": NodeTypeMetadata(
            executor_class=JSONParserNodeExecutor,
            frontend_type="json_parser",
            supports_loop_body=True,
            supports_parallel=True,
            requires_handle_mapping=False,
            description="JSON parser and transformer node",
        ),
        "http_request_node": NodeTypeMetadata(
            executor_class=HttpRequestNodeExecutor,
            frontend_type="http_request",
            supports_loop_body=True,
            supports_parallel=True,
            requires_handle_mapping=False,
            description="Enhanced HTTP request node with retry and auth",
        ),
    }

    @classmethod
    def get_metadata(cls, node_type: str) -> Optional[NodeTypeMetadata]:
        """获取节点类型元数据。"""
        return cls._registry.get(node_type)

    @classmethod
    def get_executor_class(cls, node_type: str) -> Optional[Type]:
        """获取节点执行器类。"""
        metadata = cls.get_metadata(node_type)
        return metadata.executor_class if metadata else None

    @classmethod
    def get_frontend_type(cls, node_type: str) -> Optional[str]:
        """获取前端节点类型。"""
        metadata = cls.get_metadata(node_type)
        return metadata.frontend_type if metadata else None

    @classmethod
    def is_loop_body_supported(cls, node_type: str) -> bool:
        """检查节点类型是否支持作为循环体。"""
        metadata = cls.get_metadata(node_type)
        return metadata.supports_loop_body if metadata else True  # 默认支持

    @classmethod
    def is_parallel_supported(cls, node_type: str) -> bool:
        """检查节点类型是否支持并行执行。"""
        metadata = cls.get_metadata(node_type)
        return metadata.supports_parallel if metadata else True  # 默认支持

    @classmethod
    def requires_handle_mapping(cls, node_type: str) -> bool:
        """检查节点类型是否需要 Handle ID 映射。"""
        metadata = cls.get_metadata(node_type)
        return metadata.requires_handle_mapping if metadata else False

    @classmethod
    def register_node_type(
        cls,
        node_type: str,
        executor_class: Type,
        frontend_type: str,
        supports_loop_body: bool = True,
        supports_parallel: bool = True,
        requires_handle_mapping: bool = False,
        description: str = "",
    ) -> None:
        """注册新的节点类型（用于扩展）。"""
        cls._registry[node_type] = NodeTypeMetadata(
            executor_class=executor_class,
            frontend_type=frontend_type,
            supports_loop_body=supports_loop_body,
            supports_parallel=supports_parallel,
            requires_handle_mapping=requires_handle_mapping,
            description=description,
        )
        logger.info(f"[NodeTypeRegistry] Registered new node type: {node_type}")

    @classmethod
    def list_all_types(cls) -> Dict[str, NodeTypeMetadata]:
        """列出所有注册的节点类型。"""
        return cls._registry.copy()

    @classmethod
    def validate_node_type(cls, node_type: str) -> bool:
        """验证节点类型是否已注册。"""
        return node_type in cls._registry
