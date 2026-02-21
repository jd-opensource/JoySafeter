"""
Node Executors - Facade for backward compatibility.

This module now re-exports executors from `app.core.graph.executors.*`.
"""

from app.core.graph.executors.action import (
    DirectReplyNodeExecutor,
    HttpRequestNodeExecutor,
    HumanInputNodeExecutor,
)
from app.core.graph.executors.agent import AgentNodeExecutor, CodeAgentNodeExecutor, apply_node_output_mapping
from app.core.graph.executors.logic import (
    ConditionAgentNodeExecutor,
    ConditionNodeExecutor,
    LoopConditionNodeExecutor,
    RouterNodeExecutor,
    increment_loop_count,
)
from app.core.graph.executors.state_management import (
    GetStateNodeExecutor,
    SetStateNodeExecutor,
)
from app.core.graph.executors.tool import FunctionNodeExecutor, ToolNodeExecutor
from app.core.graph.executors.transform import (
    AggregatorNodeExecutor,
    JSONParserNodeExecutor,
)
from app.core.graph.expression_evaluator import (
    StateWrapper,
    resolve_variable_expressions,
    validate_condition_expression,
)

__all__ = [
    "validate_condition_expression",
    "resolve_variable_expressions",
    "StateWrapper",
    "apply_node_output_mapping",
    "AgentNodeExecutor",
    "CodeAgentNodeExecutor",
    "ConditionNodeExecutor",
    "ConditionAgentNodeExecutor",
    "LoopConditionNodeExecutor",
    "RouterNodeExecutor",
    "increment_loop_count",
    "ToolNodeExecutor",
    "FunctionNodeExecutor",
    "DirectReplyNodeExecutor",
    "HumanInputNodeExecutor",
    "HttpRequestNodeExecutor",
    "JSONParserNodeExecutor",
    "AggregatorNodeExecutor",
    "GetStateNodeExecutor",
    "SetStateNodeExecutor",
]
