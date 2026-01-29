"""
Graph State definition and utilities.

Defines the state schema for LangGraph workflows.
"""

import operator
from typing import Any, Dict, List, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph import MessagesState
from typing_extensions import Annotated, TypedDict


def add_messages(left: List[BaseMessage], right: List[BaseMessage]) -> List[BaseMessage]:
    """Reducer function to combine message lists."""
    return left + right


def add_todos(left: List[Dict[str, Any]], right: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Reducer function to combine todo lists.

    Simply combines the lists. TodoListMiddleware handles the actual todo management logic.
    """
    if not left:
        return right if right else []
    if not right:
        return left
    # Combine both lists - TodoListMiddleware will handle deduplication and updates
    return left + right


def merge_dicts(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    """Merge two dictionaries, with right taking precedence for conflicts."""
    result = left.copy() if left else {}
    if right:
        result.update(right)
    return result


def add_task_results(left: List[Dict[str, Any]], right: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Reducer function to combine task results for parallel execution."""
    if not left:
        return right if right else []
    if not right:
        return left
    return left + right


def merge_loop_states(left: Dict[str, Dict[str, Any]], right: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Deep merge loop states to avoid concurrent write conflicts.

    Merges nested dictionaries, with right taking precedence for conflicts.
    """
    result = left.copy() if left else {}
    if right:
        for key, value in right.items():
            if key in result:
                # Deep merge nested dictionaries
                result[key] = {**result[key], **value}
            else:
                result[key] = value.copy() if isinstance(value, dict) else value
    return result


def merge_task_states(left: Dict[str, Dict[str, Any]], right: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Deep merge task states for parallel execution."""
    return merge_loop_states(left, right)  # Same logic


def merge_node_contexts(left: Dict[str, Dict[str, Any]], right: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Deep merge node contexts."""
    return merge_loop_states(left, right)  # Same logic


class BusinessState(TypedDict, total=False):
    """业务状态：存储工作流的业务数据。

    这部分状态包含实际的业务信息，不包含执行元数据。
    符合官方 LangGraph 设计原则：状态存储原始数据，格式化在节点内完成。

    Attributes:
        context: 业务上下文数据（用户输入、处理结果等）
        messages: 消息列表（继承自 MessagesState）
    """

    context: Dict[str, Any]
    # 注意：messages 继承自 MessagesState，属于业务数据


class ExecutionState(TypedDict, total=False):
    """执行状态：存储工作流执行的元数据。

    这部分状态用于跟踪执行流程、调试和监控，不包含业务数据。

    Attributes:
        current_node: 当前执行的节点名称
        route_decision: 路由决策结果
        route_history: 路由历史记录
        loop_count: 循环计数
        loop_condition_met: 循环条件是否满足
        max_loop_iterations: 最大循环次数
        task_results: 并行任务结果
        parallel_results: 并行执行结果
        loop_states: 循环状态隔离
        task_states: 任务状态隔离
        node_contexts: 节点上下文隔离
        todos: 待办事项列表（用于 TodoListMiddleware）
    """

    current_node: Optional[str]
    route_decision: str  # Route key selected by router nodes
    route_history: Annotated[List[str], operator.add]  # History of route decisions

    # Loop Control
    loop_count: int
    loop_condition_met: bool
    max_loop_iterations: int

    # Parallel Execution
    task_results: Annotated[List[Dict[str, Any]], add_task_results]
    parallel_results: Annotated[List[Any], operator.add]

    # State Isolation (Scoped State)
    loop_states: Annotated[Dict[str, Dict[str, Any]], merge_loop_states]
    task_states: Annotated[Dict[str, Dict[str, Any]], merge_task_states]
    node_contexts: Annotated[Dict[str, Dict[str, Any]], merge_node_contexts]

    # Todos for TodoListMiddleware
    todos: Annotated[List[Dict[str, Any]], add_todos]


class GraphState(MessagesState, BusinessState, ExecutionState):
    """工作流图状态：组合业务状态和执行状态。

    这个类组合了 BusinessState（业务数据）和 ExecutionState（执行元数据），
    提供了完整的状态管理功能，同时保持了概念上的分离。

    设计原则：
    - 业务数据存储在 BusinessState 中（context, messages）
    - 执行元数据存储在 ExecutionState 中（current_node, route_decision 等）
    - 状态存储原始数据，格式化在节点内完成

    Supports:
    - Serial execution (default)
    - Parallel execution (Fan-Out/Fan-In)
    - Conditional routing
    - Loops with state isolation
    """

    # Note: All fields are inherited from parent TypedDict classes
    # Do not redefine fields here to avoid TypedDict overwriting errors

    # Note: loop_states, task_states, node_contexts, and todos are inherited from ExecutionState
    # Do not redefine them here to avoid TypedDict overwriting errors
