"""
Stream Event Handler

处理 LangGraph 事件流，转换为标准化的 SSE 格式。
"""

import json
import time
from typing import Any

from langchain_core.messages.base import BaseMessage
from loguru import logger


class StreamState:
    """流式状态追踪器，用于在事件流中累积数据，确保断连时能保存"""

    def __init__(self, thread_id: str):
        self.thread_id = thread_id
        self.all_messages: list[BaseMessage] = []  # 最终的完整消息列表
        self.assistant_content = ""  # 累积的文本内容
        self.stopped = False  # 是否被用户停止
        self.has_error = False  # 是否发生错误

        # 中断状态
        self.interrupted = False  # 是否处于中断状态
        self.interrupt_node: str | None = None  # 中断的节点名称
        self.interrupt_state: dict | None = None  # 中断时的状态快照

        # 时间跟踪：用于计算执行时长
        self.node_start_times: dict[str, float] = {}  # node_name -> start_time
        self.tool_start_times: dict[str, tuple[str, float]] = {}  # tool_name -> (run_id, start_time)

    def append_content(self, chunk: str):
        """追加内容块"""
        self.assistant_content += chunk


class StreamEventHandler:
    """流式事件处理器，负责将 LangGraph 事件转换为标准化的 SSE 格式"""

    @staticmethod
    def _extract_metadata(event: dict) -> dict:
        """提取标准化元数据"""
        metadata = event.get("metadata", {})
        config = metadata.get("config", {})
        return {
            "node_name": metadata.get("langgraph_node") or event.get("name") or "unknown",
            "run_id": event.get("run_id", ""),
            "tags": config.get("tags") or metadata.get("tags") or event.get("tags") or [],
            "timestamp": int(time.time() * 1000),
        }

    @staticmethod
    def _extract_node_info(event: dict) -> dict:
        """提取节点信息（名称、标签、ID等）"""
        metadata = event.get("metadata", {})
        config = metadata.get("config", {})

        node_name = metadata.get("langgraph_node") or event.get("name") or "unknown"

        # 尝试从多个位置提取节点标签
        node_label = (
            config.get("node_label")
            or metadata.get("node_label")
            or (
                config.get("tags", [{}])[0].get("label")
                if config.get("tags") and isinstance(config.get("tags"), list) and len(config.get("tags")) > 0
                else None
            )
            or node_name.replace("_", " ").title()
        )

        return {
            "node_name": node_name,
            "node_label": node_label,
            "node_id": config.get("node_id") or metadata.get("node_id"),
            "node_type": config.get("node_type") or metadata.get("node_type"),
        }

    @staticmethod
    def format_sse(event_type: str, payload: dict, thread_id: str) -> str:
        """构造标准 SSE Envelope"""
        meta = payload.pop("_meta", {})

        def _default(obj: Any) -> Any:
            """处理不可序列化的对象"""
            if isinstance(obj, BaseMessage):
                return {
                    "type": obj.__class__.__name__,
                    "content": str(obj.content) if hasattr(obj, "content") else str(obj),
                }
            if hasattr(obj, "dict"):
                try:
                    return obj.dict()
                except Exception:
                    pass
            if hasattr(obj, "model_dump"):
                try:
                    return obj.model_dump()
                except Exception:
                    pass
            return str(obj)

        envelope = {
            "type": event_type,
            "thread_id": thread_id,
            "run_id": meta.get("run_id", ""),
            "node_name": meta.get("node_name", "system"),
            "timestamp": meta.get("timestamp", int(time.time() * 1000)),
            "tags": meta.get("tags", []),
            "data": payload,
        }
        return f"data: {json.dumps(envelope, ensure_ascii=False, default=_default)}\n\n"

    async def handle_chat_model_start(self, event: dict, state: StreamState) -> str:
        """处理模型开始事件，提取输入消息"""
        event_data = event.get("data", {})
        input_data = event_data.get("input", {})
        messages = input_data.get("messages", [])

        # 序列化消息列表
        serialized_messages = []
        for msg in messages:
            if isinstance(msg, list):
                # 处理嵌套的消息列表
                for sub_msg in msg:
                    serialized_messages.append(sub_msg)
            else:
                serialized_messages.append(msg)

        # 提取模型信息
        metadata = event.get("metadata", {})
        model_name = metadata.get("ls_model_name") or event.get("name", "unknown")
        model_provider = metadata.get("ls_provider") or "unknown"

        meta = self._extract_metadata(event)
        return self.format_sse(
            "model_input",
            {
                "messages": serialized_messages,
                "model_name": model_name,
                "model_provider": model_provider,
                "_meta": meta,
            },
            state.thread_id,
        )

    async def handle_chat_model_stream(self, event: dict, state: StreamState) -> str | None:
        """处理文本流事件"""
        chunk = event.get("data", {}).get("chunk")
        if not chunk or not hasattr(chunk, "content") or not chunk.content:
            return None

        content = chunk.content
        state.append_content(content)

        meta = self._extract_metadata(event)
        return self.format_sse("content", {"delta": content, "_meta": meta}, state.thread_id)

    async def handle_chat_model_end(self, event: dict, state: StreamState) -> str:
        """处理模型结束事件，提取完整输出"""
        event_data = event.get("data", {})
        output = event_data.get("output")

        # 输出消息（序列化在 format_sse 中统一处理）
        serialized_output = output

        # 提取模型信息
        metadata = event.get("metadata", {})
        model_name = metadata.get("ls_model_name") or event.get("name", "unknown")
        model_provider = metadata.get("ls_provider") or "unknown"

        # 提取使用情况（如果有）
        usage_metadata = None
        if output:
            if hasattr(output, "response_metadata"):
                response_metadata = output.response_metadata
                if isinstance(response_metadata, dict):
                    usage_metadata = response_metadata.get("usage_metadata")
                elif hasattr(response_metadata, "get"):
                    usage_metadata = response_metadata.get("usage_metadata")

        meta = self._extract_metadata(event)
        return self.format_sse(
            "model_output",
            {
                "output": serialized_output,
                "model_name": model_name,
                "model_provider": model_provider,
                "usage_metadata": usage_metadata,
                "_meta": meta,
            },
            state.thread_id,
        )

    async def handle_tool_start(self, event: dict, state: StreamState) -> str:
        """处理工具开始事件"""
        tool_input = event.get("data", {}).get("input", {})
        if isinstance(tool_input, dict):
            # 过滤掉 deepagents FilesystemMiddleware 注入的 runtime 参数
            tool_input = {k: v for k, v in tool_input.items() if k != "runtime"}

        tool_name = event.get("name")
        run_id = event.get("run_id", "")

        # 记录开始时间（使用 run_id 作为键的一部分，支持并发执行）
        if tool_name is not None:
            state.tool_start_times[tool_name] = (run_id, time.time())

        meta = self._extract_metadata(event)
        return self.format_sse(
            "tool_start", {"tool_name": tool_name, "tool_input": tool_input, "_meta": meta}, state.thread_id
        )

    async def handle_tool_end(self, event: dict, state: StreamState) -> str:
        """处理工具结束事件"""
        raw_output = event.get("data", {}).get("output")
        # 处理 ToolMessage 对象的情况
        if hasattr(raw_output, "content"):
            output = raw_output.content
        else:
            output = raw_output

        tool_name = event.get("name")
        run_id = event.get("run_id", "")

        # 计算执行时长
        start_info = state.tool_start_times.pop(tool_name, None) if tool_name is not None else None
        duration = None
        if start_info and start_info[0] == run_id:
            duration = int((time.time() - start_info[1]) * 1000)  # 转换为毫秒

        # 检测错误状态
        has_error = False
        if isinstance(output, dict):
            error = output.get("error") or output.get("exception") or output.get("Error")
            has_error = error is not None
        elif isinstance(output, str):
            error_lower = output.lower()
            has_error = any(keyword in error_lower for keyword in ["error", "exception", "failed", "failure"])

        meta = self._extract_metadata(event)
        return self.format_sse(
            "tool_end",
            {
                "tool_name": tool_name,
                "tool_output": output,
                "duration": duration,
                "status": "error" if has_error else "success",
                "_meta": meta,
            },
            state.thread_id,
        )

    async def handle_node_start(self, event: dict, state: StreamState) -> str:
        """处理节点开始事件"""
        node_info = self._extract_node_info(event)
        node_name = node_info["node_name"]

        # 记录开始时间
        state.node_start_times[node_name] = time.time()

        meta = self._extract_metadata(event)
        meta.update(node_info)

        return self.format_sse(
            "node_start",
            {
                "node_name": node_name,
                "node_label": node_info.get("node_label", node_name),
                "node_id": node_info.get("node_id"),
                "_meta": meta,
            },
            state.thread_id,
        )

    async def handle_node_end(self, event: dict, state: StreamState) -> list[str]:
        """处理节点结束事件，返回多个 SSE 事件（包括 Command、路由决策和 CodeAgent 事件）"""
        node_info = self._extract_node_info(event)
        node_name = node_info["node_name"]
        node_type = node_info.get("node_type", "unknown")

        # 计算执行时长
        start_time = state.node_start_times.pop(node_name, None)
        duration = None
        if start_time:
            duration = int((time.time() - start_time) * 1000)  # 转换为毫秒

        # 检测是否有错误
        output = event.get("data", {}).get("output")
        has_error = False
        if isinstance(output, dict):
            error = output.get("error") or output.get("exception") or output.get("Error")
            has_error = error is not None
        elif isinstance(output, str):
            error_lower = str(output).lower()
            has_error = any(keyword in error_lower for keyword in ["error", "exception", "failed", "failure"])

        meta = self._extract_metadata(event)
        meta.update(node_info)

        events = []

        # 0. 检查并处理 CodeAgent 事件 (优先发送，让前端能看到过程)
        if output and isinstance(output, dict):
            code_agent_events = output.get("code_agent_events", [])
            if code_agent_events:
                logger.debug(
                    f"[StreamEventHandler] Processing {len(code_agent_events)} CodeAgent events | node={node_name}"
                )
                for ca_event in code_agent_events:
                    ca_event_type = ca_event.get("type", "unknown")
                    ca_content = ca_event.get("content", "")
                    ca_step = ca_event.get("step", 0)
                    ca_metadata = ca_event.get("metadata", {})

                    # 根据 CodeAgent 事件类型生成对应的 SSE 事件
                    if ca_event_type == "thought":
                        events.append(
                            self.format_sse(
                                "code_agent_thought",
                                {
                                    "node_name": node_name,
                                    "step": ca_step,
                                    "content": ca_content,
                                    "_meta": meta,
                                },
                                state.thread_id,
                            )
                        )

                    elif ca_event_type == "code":
                        events.append(
                            self.format_sse(
                                "code_agent_code",
                                {
                                    "node_name": node_name,
                                    "step": ca_step,
                                    "code": ca_content,
                                    "_meta": meta,
                                },
                                state.thread_id,
                            )
                        )

                    elif ca_event_type == "observation":
                        events.append(
                            self.format_sse(
                                "code_agent_observation",
                                {
                                    "node_name": node_name,
                                    "step": ca_step,
                                    "observation": ca_content,
                                    "has_error": bool(ca_metadata.get("error")),
                                    "_meta": meta,
                                },
                                state.thread_id,
                            )
                        )

                    elif ca_event_type == "final_answer":
                        events.append(
                            self.format_sse(
                                "code_agent_final_answer",
                                {
                                    "node_name": node_name,
                                    "step": ca_step,
                                    "answer": ca_content,
                                    "_meta": meta,
                                },
                                state.thread_id,
                            )
                        )

                    elif ca_event_type == "planning":
                        events.append(
                            self.format_sse(
                                "code_agent_planning",
                                {
                                    "node_name": node_name,
                                    "step": ca_step,
                                    "plan": ca_content,
                                    "is_update": ca_metadata.get("is_update", False),
                                    "_meta": meta,
                                },
                                state.thread_id,
                            )
                        )

                    elif ca_event_type == "error":
                        events.append(
                            self.format_sse(
                                "code_agent_error",
                                {
                                    "node_name": node_name,
                                    "step": ca_step,
                                    "error": ca_content,
                                    "_meta": meta,
                                },
                                state.thread_id,
                            )
                        )

        # 1. 发送节点结束事件
        events.append(
            self.format_sse(
                "node_end",
                {
                    "node_name": node_name,
                    "node_label": node_info.get("node_label", node_name),
                    "node_id": node_info.get("node_id"),
                    "duration": duration,
                    "status": "error" if has_error else "success",
                    "_meta": meta,
                },
                state.thread_id,
            )
        )

        # 2. 检查是否有 Command 对象（从 output 中提取）
        # LangGraph 会在 output 中包含 Command 对象的信息
        if output and isinstance(output, dict):
            # 检查是否有 Command 相关的信息
            # 注意：LangGraph 可能不会直接返回 Command 对象，而是将其转换为状态更新
            # 我们需要从状态更新中推断 Command 信息

            # 检查是否有 route_decision（表示路由决策）
            route_decision = output.get("route_decision")
            route_reason = output.get("route_reason")

            # 尝试从状态中提取 goto 信息（如果 Command 被处理了）
            # 实际上，Command 的 goto 会被 LangGraph 处理，我们需要从下一个节点推断

            # 如果是 Condition/Router/Loop 节点，发送路由决策事件
            if node_type in ["condition", "router", "loop"] and route_decision:
                # 尝试从状态更新中推断 goto（实际上 goto 会被 LangGraph 处理，我们无法直接获取）
                # 但我们可以从 route_decision 推断路由方向
                decision_data = {
                    "node_id": node_info.get("node_id") or node_name,
                    "node_type": node_type,
                    "result": route_decision,
                    "reason": route_reason or f"路由决策: {route_decision}",
                    "goto": "unknown",  # 无法从 output 中获取，需要从下一个节点推断
                }

                events.append(self.format_sse("route_decision", decision_data, state.thread_id))

            # Command 事件 - 每个节点结束时都发送，包含节点状态信息
            # 这让前端能够了解每个节点执行后的完整状态
            cleaned_update = {}
            for k, v in output.items():
                if k in ["route_decision", "route_reason"]:
                    continue
                # 如果值是 task_results，需要清理其中的循环引用
                if k == "task_results" and isinstance(v, list):
                    cleaned_results = []
                    for task_result in v:
                        if isinstance(task_result, dict):
                            # 创建副本，只保留必要的字段
                            cleaned_result = {
                                "status": task_result.get("status"),
                                "task_id": task_result.get("task_id"),
                            }
                            # 添加 error_msg（如果有）
                            if "error_msg" in task_result:
                                cleaned_result["error_msg"] = task_result.get("error_msg")
                            # 处理 result 字段，避免循环引用
                            result_value = task_result.get("result")
                            if isinstance(result_value, dict):
                                # 如果 result 是字典，创建一个不包含 task_results 的浅拷贝
                                cleaned_result["result"] = {
                                    k2: v2 for k2, v2 in result_value.items() if k2 != "task_results"
                                }
                            else:
                                cleaned_result["result"] = result_value
                            cleaned_results.append(cleaned_result)
                        else:
                            cleaned_results.append(task_result)
                    cleaned_update[k] = cleaned_results
                else:
                    cleaned_update[k] = v

            events.append(
                self.format_sse(
                    "command",
                    {
                        "update": cleaned_update,
                        "goto": None,
                        "reason": route_reason,
                    },
                    state.thread_id,
                )
            )

            # 检查循环迭代信息
            loop_count = output.get("loop_count")
            if loop_count is not None:
                loop_iteration_data = {
                    "loop_node_id": node_info.get("node_id") or node_name,
                    "iteration": loop_count,
                    "max_iterations": output.get("max_loop_iterations", 0),
                    "condition_met": output.get("loop_condition_met", False),
                    "reason": output.get("route_reason") or f"第 {loop_count} 次迭代",
                }
                events.append(self.format_sse("loop_iteration", loop_iteration_data, state.thread_id))

            # 检查并行任务信息
            task_states = output.get("task_states")
            if task_states and isinstance(task_states, dict):
                for task_id, task_state in task_states.items():
                    if isinstance(task_state, dict):
                        task_status = task_state.get("status", "pending")
                        # 转换为前端期望的状态格式
                        if task_status == "running":
                            status_str = "started"
                        elif task_status == "completed":
                            status_str = "completed"
                        elif task_status == "error":
                            status_str = "error"
                        else:
                            status_str = "started"  # pending -> started

                        parallel_task_data = {
                            "task_id": task_id,
                            "status": status_str,
                            "result": task_state.get("result"),
                            "error_msg": task_state.get("error_msg"),
                        }
                        events.append(self.format_sse("parallel_task", parallel_task_data, state.thread_id))

            # 发送状态更新事件
            updated_fields = [k for k in output.keys() if k not in ["route_decision", "route_reason"]]
            if updated_fields:
                state_update_data = {
                    "updated_fields": updated_fields,
                    "state_snapshot": output,
                }
                events.append(self.format_sse("state_update", state_update_data, state.thread_id))

        return events
