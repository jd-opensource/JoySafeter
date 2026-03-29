"""
Node Type Registry - Unified node type management.

Provides centralized registry for node types, mapping between frontend and backend,
and metadata about node capabilities.  Each node type declares its default state
field dependencies (reads/writes) for the state-centric architecture.
"""

from typing import Dict, List, Optional, Type

from app.core.graph.node_executors import (
    AgentNodeExecutor,
    AggregatorNodeExecutor,
    CodeAgentNodeExecutor,
    ConditionAgentNodeExecutor,
    ConditionNodeExecutor,
    DirectReplyNodeExecutor,
    FunctionNodeExecutor,
    GetStateNodeExecutor,
    HttpRequestNodeExecutor,
    HumanInputNodeExecutor,
    JSONParserNodeExecutor,
    LoopConditionNodeExecutor,
    RouterNodeExecutor,
    SetStateNodeExecutor,
    ToolNodeExecutor,
)


class NodeTypeMetadata:
    """Node type metadata."""

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
    """Node type registry — unified management of frontend/backend node type mappings."""

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
        "condition_agent": NodeTypeMetadata(
            executor_class=ConditionAgentNodeExecutor,
            frontend_type="condition_agent",
            supports_loop_body=False,
            supports_parallel=False,
            requires_handle_mapping=True,
            description="AI Decision Split routing node",
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
        "human_input": NodeTypeMetadata(
            executor_class=HumanInputNodeExecutor,
            frontend_type="human_input",
            supports_loop_body=False,
            supports_parallel=False,
            requires_handle_mapping=False,
            description="Human-in-the-loop interrupt gate",
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
        "get_state_node": NodeTypeMetadata(
            executor_class=GetStateNodeExecutor,
            frontend_type="get_state_node",
            supports_loop_body=True,
            supports_parallel=True,
            requires_handle_mapping=False,
            description="Read global configuration or state into local tracking",
        ),
        "set_state_node": NodeTypeMetadata(
            executor_class=SetStateNodeExecutor,
            frontend_type="set_state_node",
            supports_loop_body=True,
            supports_parallel=True,
            requires_handle_mapping=False,
            description="Write local configuration into overarching state",
        ),
        "a2a_agent": NodeTypeMetadata(
            executor_class=AgentNodeExecutor,  # Fallback for standard builder; properly handled natively in deep_agents
            frontend_type="a2a_agent",
            supports_loop_body=True,
            supports_parallel=True,
            requires_handle_mapping=False,
            description="Remote Agent-to-Agent node",
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
