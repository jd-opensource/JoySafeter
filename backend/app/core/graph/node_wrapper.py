"""
Node Execution Wrapper - Provides unified node execution with hooks.

Automatically handles:
- Loop body state updates
- Parallel execution result collection
- Trace recording
- Error handling
- Command object support (optional)
"""

from typing import Any, Dict, List, Optional, Union

from loguru import logger

try:
    from langgraph.types import Command

    COMMAND_AVAILABLE = True
except ImportError:
    COMMAND_AVAILABLE = False
    Command = None  # type: ignore[assignment,misc]

from app.core.graph.graph_state import GraphState
from app.core.graph.node_executors import increment_loop_count
from app.core.graph.trace_utils import create_node_trace, log_node_execution


class NodeExecutionWrapper:
    """统一的节点执行包装器，提供执行前/后钩子。

    自动处理：
    - 循环体状态更新
    - 并行执行结果收集
    - Trace 记录
    - 错误处理
    """

    def __init__(
        self,
        executor: Any,
        node_id: str,
        node_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.executor = executor
        self.node_id = node_id
        self.node_type = node_type
        self.metadata = metadata or {}

    async def _before_execute(self, state: GraphState) -> GraphState:
        """执行前钩子：初始化状态。"""
        # 初始化循环状态（如果是循环体）
        if self.metadata.get("is_loop_body"):
            loop_node_id = self.metadata.get("loop_node_id")
            if loop_node_id:
                loop_states = state.get("loop_states", {})
                if loop_node_id not in loop_states:
                    loop_states = loop_states.copy()
                    loop_states[loop_node_id] = {"loop_count": 0}
                    state = {**state, "loop_states": loop_states}

        return state

    async def _after_execute(
        self, state: GraphState, result: Union[Dict[str, Any], Command, str]
    ) -> Union[Dict[str, Any], Command]:
        """执行后钩子：自动更新状态。

        Args:
            state: 当前状态
            result: 节点执行结果（Dict、Command 对象或字符串）

        Returns:
            Union[Dict[str, Any], Command]: 处理后的结果
        """
        # 如果是 Command 对象，提取 update 部分进行处理
        is_command = COMMAND_AVAILABLE and isinstance(result, Command)
        if is_command:
            # Command 对象：提取 update 字典进行处理
            update_dict = result.update if hasattr(result, "update") else {}
        elif isinstance(result, str):
            # 条件节点或路由节点返回字符串 route_key，需要转换为字典以更新状态
            # 这通常发生在 condition 或 router 节点作为普通节点执行时
            update_dict = {
                "current_node": self.node_id,
                "route_decision": result,
                "route_history": [result],
            }
            logger.debug(
                f"[NodeExecutionWrapper] Converted string result to dict for state update | "
                f"node_id={self.node_id} | route_key={result}"
            )
        else:
            # 普通字典
            update_dict = result if isinstance(result, dict) else {}

        # 自动更新循环计数（如果是循环体）
        if self.metadata.get("is_loop_body") and isinstance(update_dict, dict):
            loop_node_id = self.metadata.get("loop_node_id")
            if loop_node_id:
                try:
                    loop_update = increment_loop_count(state, loop_node_id)
                    update_dict = {**update_dict, **loop_update}
                    logger.debug(
                        f"[NodeExecutionWrapper] Auto-incremented loop count | "
                        f"node_id={self.node_id} | loop_node_id={loop_node_id}"
                    )
                except Exception as e:
                    logger.warning(
                        f"[NodeExecutionWrapper] Failed to auto-increment loop count | "
                        f"node_id={self.node_id} | error={type(e).__name__}: {e}"
                    )

        # 自动填充 task_results（如果是并行节点）
        if self.metadata.get("is_parallel_node") and isinstance(update_dict, dict):
            # 提取 result 字段，如果不存在则创建一个不包含 task_results 的副本
            # 避免循环引用：task_result.result 不应该包含 task_results 本身
            result_value = update_dict.get("result")
            if result_value is None:
                # 创建一个不包含 task_results 和其他元数据的副本
                result_value = {
                    k: v
                    for k, v in update_dict.items()
                    if k not in ["task_results", "current_node", "route_decision", "route_history"]
                }
                # 如果过滤后为空，使用一个简单的标识
                if not result_value:
                    result_value = {"node_id": self.node_id, "status": "completed"}

            task_result = {
                "status": "success",
                "result": result_value,
                "task_id": self.node_id,
            }

            # 检查是否有错误
            if "error" in update_dict or "error_msg" in update_dict:
                task_result["status"] = "error"
                task_result["error_msg"] = update_dict.get("error_msg") or str(
                    update_dict.get("error", "Unknown error")
                )

            # 如果 result 中已有 task_results，合并；否则创建新列表
            existing_results = update_dict.get("task_results", [])
            update_dict["task_results"] = existing_results + [task_result]

            logger.debug(
                f"[NodeExecutionWrapper] Auto-filled task_results | "
                f"node_id={self.node_id} | status={task_result['status']}"
            )

        # 如果是 Command 对象，更新其 update 字段
        if is_command:
            # 创建新的 Command 对象，保留 goto 信息
            goto = result.goto if hasattr(result, "goto") else None
            return Command(update=update_dict, goto=goto)  # type: ignore[return-value]

        # 返回更新后的字典
        return update_dict  # type: ignore[return-value]

    async def __call__(self, state: GraphState) -> Union[Dict[str, Any], Command]:
        """执行节点，包含前后钩子。

        Returns:
            Union[Dict[str, Any], Command]: 节点执行结果，可能是字典或 Command 对象
        """
        # 创建 trace
        trace = create_node_trace(self.node_id, self.node_type, state)

        try:
            # 执行前钩子
            state = await self._before_execute(state)

            # 执行节点
            result = await self.executor(state)

            # 执行后钩子（自动更新状态）
            result = await self._after_execute(state, result)

            # 完成 trace（提取 update 部分用于 trace）
            import time

            trace_data_raw = result.update if (COMMAND_AVAILABLE and isinstance(result, Command)) else result
            trace_data: Dict[str, Any] = trace_data_raw if isinstance(trace_data_raw, dict) else {}  # type: ignore[assignment]
            trace.finish(time.time(), trace_data)
            log_node_execution(trace, self.node_id, self.node_type)

            return result
        except Exception as e:
            # 错误处理
            import time

            trace.error = e
            trace.finish(time.time())
            log_node_execution(trace, self.node_id, self.node_type)

            logger.error(
                f"[NodeExecutionWrapper] Node execution failed | "
                f"node_id={self.node_id} | node_type={self.node_type} | "
                f"error={type(e).__name__}: {e}"
            )

            # 返回错误结果
            error_result = {
                "current_node": self.node_id,
                "error": str(e),
                "error_msg": str(e),
            }

            # 如果是并行节点，也要填充 task_results
            if self.metadata.get("is_parallel_node"):
                task_results_list: List[Dict[str, str]] = [
                    {
                        "status": "error",
                        "error_msg": str(e),
                        "task_id": self.node_id,
                    }
                ]
                error_result["task_results"] = task_results_list  # type: ignore[assignment]

            return error_result
