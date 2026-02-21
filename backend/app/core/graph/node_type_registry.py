"""
Node Type Registry - Unified node type management.

Provides centralized registry for node types, mapping between frontend and backend,
and metadata about node capabilities.  Each node type declares its default state
field dependencies (reads/writes) for the state-centric architecture.
"""

from typing import Dict, List, Optional, Type

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
    """Node type metadata with state dependency declarations."""

    def __init__(
        self,
        executor_class: Type,
        frontend_type: str,
        supports_loop_body: bool = True,
        supports_parallel: bool = True,
        requires_handle_mapping: bool = False,
        description: str = "",
        default_reads: Optional[List[str]] = None,
        default_writes: Optional[List[str]] = None,
    ):
        self.executor_class = executor_class
        self.frontend_type = frontend_type
        self.supports_loop_body = supports_loop_body
        self.supports_parallel = supports_parallel
        self.requires_handle_mapping = requires_handle_mapping
        self.description = description
        # State-centric: declare which state fields this node type reads/writes
        # ["*"] means all fields (wildcard) — backward-compatible default
        self.default_reads: List[str] = default_reads or ["*"]
        self.default_writes: List[str] = default_writes or ["*"]


class NodeTypeRegistry:
    """Node type registry — unified management of frontend/backend node type mappings."""

    _registry: Dict[str, NodeTypeMetadata] = {
        "agent": NodeTypeMetadata(
            executor_class=AgentNodeExecutor,
            frontend_type="agent",
            supports_loop_body=True,
            supports_parallel=True,
            requires_handle_mapping=False,
            description="LLM Agent node with tools and middleware support",
            default_reads=["messages", "context"],
            default_writes=["messages", "current_node"],
        ),
        "code_agent": NodeTypeMetadata(
            executor_class=CodeAgentNodeExecutor,
            frontend_type="code_agent",
            supports_loop_body=True,
            supports_parallel=True,
            requires_handle_mapping=False,
            description="Python code execution agent with Thought-Code-Observation loop",
            default_reads=["messages", "context"],
            default_writes=["messages", "current_node", "context"],
        ),
        "condition": NodeTypeMetadata(
            executor_class=ConditionNodeExecutor,
            frontend_type="condition",
            supports_loop_body=False,
            supports_parallel=False,
            requires_handle_mapping=True,
            description="Simple if/else condition node",
            default_reads=["*"],
            default_writes=["route_decision", "route_history"],
        ),
        "router_node": NodeTypeMetadata(
            executor_class=RouterNodeExecutor,
            frontend_type="router",
            supports_loop_body=False,
            supports_parallel=False,
            requires_handle_mapping=True,
            description="Multi-rule router node for complex routing",
            default_reads=["*"],
            default_writes=["route_decision", "route_history"],
        ),
        "loop_condition_node": NodeTypeMetadata(
            executor_class=LoopConditionNodeExecutor,
            frontend_type="loop_condition",
            supports_loop_body=False,
            supports_parallel=False,
            requires_handle_mapping=True,
            description="Loop condition evaluation node",
            default_reads=["loop_count", "loop_condition_met", "context", "loop_states"],
            default_writes=["loop_count", "loop_condition_met", "loop_states"],
        ),
        "direct_reply": NodeTypeMetadata(
            executor_class=DirectReplyNodeExecutor,
            frontend_type="direct_reply",
            supports_loop_body=True,
            supports_parallel=True,
            requires_handle_mapping=False,
            description="Direct reply with template substitution",
            default_reads=["messages", "context"],
            default_writes=["messages", "current_node"],
        ),
        "human_input": NodeTypeMetadata(
            executor_class=DirectReplyNodeExecutor,  # Placeholder — uses HumanInputNodeExecutor
            frontend_type="human_input",
            supports_loop_body=False,
            supports_parallel=False,
            requires_handle_mapping=False,
            description="Human-in-the-loop interrupt gate",
            default_reads=["messages"],
            default_writes=["messages", "current_node"],
        ),
        "tool_node": NodeTypeMetadata(
            executor_class=ToolNodeExecutor,
            frontend_type="tool",
            supports_loop_body=True,
            supports_parallel=True,
            requires_handle_mapping=False,
            description="Tool execution node",
            default_reads=["messages", "context"],
            default_writes=["messages", "context", "current_node"],
        ),
        "function_node": NodeTypeMetadata(
            executor_class=FunctionNodeExecutor,
            frontend_type="function",
            supports_loop_body=True,
            supports_parallel=True,
            requires_handle_mapping=False,
            description="Custom function execution node (requires sandboxing)",
            default_reads=["messages", "context"],
            default_writes=["messages", "context", "current_node"],
        ),
        "aggregator_node": NodeTypeMetadata(
            executor_class=AggregatorNodeExecutor,
            frontend_type="aggregator",
            supports_loop_body=False,
            supports_parallel=False,
            requires_handle_mapping=False,
            description="Fan-In aggregator node for parallel results",
            default_reads=["task_results", "parallel_results", "task_states"],
            default_writes=["messages", "context", "current_node"],
        ),
        "json_parser_node": NodeTypeMetadata(
            executor_class=JSONParserNodeExecutor,
            frontend_type="json_parser",
            supports_loop_body=True,
            supports_parallel=True,
            requires_handle_mapping=False,
            description="JSON parser and transformer node",
            default_reads=["messages", "context"],
            default_writes=["messages", "context", "current_node"],
        ),
        "http_request_node": NodeTypeMetadata(
            executor_class=HttpRequestNodeExecutor,
            frontend_type="http_request",
            supports_loop_body=True,
            supports_parallel=True,
            requires_handle_mapping=False,
            description="Enhanced HTTP request node with retry and auth",
            default_reads=["messages", "context"],
            default_writes=["messages", "context", "current_node"],
        ),
    }

    @classmethod
    def get_metadata(cls, node_type: str) -> Optional[NodeTypeMetadata]:
        """Get node type metadata."""
        return cls._registry.get(node_type)

    @classmethod
    def get_executor_class(cls, node_type: str) -> Optional[Type]:
        """Get the executor class for a node type."""
        metadata = cls.get_metadata(node_type)
        return metadata.executor_class if metadata else None

    @classmethod
    def get_frontend_type(cls, node_type: str) -> Optional[str]:
        """Get the frontend type string for a node type."""
        metadata = cls.get_metadata(node_type)
        return metadata.frontend_type if metadata else None

    @classmethod
    def get_default_reads(cls, node_type: str) -> List[str]:
        """Get default state fields read by this node type."""
        metadata = cls.get_metadata(node_type)
        return metadata.default_reads if metadata else ["*"]

    @classmethod
    def get_default_writes(cls, node_type: str) -> List[str]:
        """Get default state fields written by this node type."""
        metadata = cls.get_metadata(node_type)
        return metadata.default_writes if metadata else ["*"]



    @classmethod
    def is_loop_body_supported(cls, node_type: str) -> bool:
        """Check if node type supports being a loop body."""
        metadata = cls.get_metadata(node_type)
        return metadata.supports_loop_body if metadata else True

    @classmethod
    def is_parallel_supported(cls, node_type: str) -> bool:
        """Check if node type supports parallel execution."""
        metadata = cls.get_metadata(node_type)
        return metadata.supports_parallel if metadata else True

    @classmethod
    def requires_handle_mapping(cls, node_type: str) -> bool:
        """Check if node type requires Handle ID mapping."""
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
        default_reads: Optional[List[str]] = None,
        default_writes: Optional[List[str]] = None,
    ) -> None:
        """Register a new node type (for extension)."""
        cls._registry[node_type] = NodeTypeMetadata(
            executor_class=executor_class,
            frontend_type=frontend_type,
            supports_loop_body=supports_loop_body,
            supports_parallel=supports_parallel,
            requires_handle_mapping=requires_handle_mapping,
            description=description,
            default_reads=default_reads,
            default_writes=default_writes,
        )
        logger.info(f"[NodeTypeRegistry] Registered new node type: {node_type}")

    @classmethod
    def list_all_types(cls) -> Dict[str, NodeTypeMetadata]:
        """List all registered node types."""
        return cls._registry.copy()

    @classmethod
    def validate_node_type(cls, node_type: str) -> bool:
        """Validate that a node type is registered."""
        return node_type in cls._registry

