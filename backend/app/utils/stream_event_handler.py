"""
Stream Event Handler (Production)

处理 LangGraph 事件流，转换为标准化的 SSE 格式。
使用 Map-based 层级追踪（参考 Langfuse CallbackHandler 架构），
通过 run_id + parent_run_id 建立 N 层 Observation 层级。

核心设计：
- StreamState: Map-based observation 管理（替代 stack）
- ObservationRecord: 增强的内存 observation 记录
- StreamEventHandler: 事件 -> SSE 转换，所有 handler 接收 run_id/parent_run_id
- format_sse: 安全序列化，降级处理
"""

import json
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from langchain_core.messages.base import BaseMessage
from loguru import logger

from app.utils.message_serializer import serialize_messages, truncate_data
from app.utils.token_usage import extract_usage_from_output

# ============ LangGraph 控制流异常（不标记为 ERROR） ============

CONTROL_FLOW_EXCEPTIONS: set[type] = set()
try:
    from langgraph.errors import GraphBubbleUp

    CONTROL_FLOW_EXCEPTIONS.add(GraphBubbleUp)
except ImportError:
    pass


# ============ Observation Enums ============


class ObsType(str, Enum):
    SPAN = "SPAN"
    GENERATION = "GENERATION"
    TOOL = "TOOL"
    EVENT = "EVENT"


class ObsLevel(str, Enum):
    DEBUG = "DEBUG"
    DEFAULT = "DEFAULT"
    WARNING = "WARNING"
    ERROR = "ERROR"


class ObsStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


# ============ ObservationRecord ============


@dataclass
class ObservationRecord:
    """
    内存中的 Observation 记录。
    SSE 流结束后批量写入数据库。
    """

    id: str
    trace_id: str
    parent_observation_id: Optional[str]
    type: ObsType
    name: Optional[str]
    start_time: float  # epoch ms
    # Lifecycle
    end_time: Optional[float] = None
    duration_ms: Optional[int] = None
    status: ObsStatus = ObsStatus.RUNNING
    # I/O
    input_data: Optional[Any] = None
    output_data: Optional[Any] = None
    # Model info (GENERATION only)
    model_name: Optional[str] = None
    model_provider: Optional[str] = None
    model_parameters: Optional[dict] = None
    # Token usage (GENERATION only)
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    # Level / status
    level: ObsLevel = ObsLevel.DEFAULT
    status_message: Optional[str] = None
    # Timestamps
    completion_start_time: Optional[float] = None  # 首 token 时间 (GENERATION)
    # Meta
    metadata: Optional[dict] = None
    version: Optional[str] = None  # 代码/模型版本


# ============ StreamState ============


class StreamState:
    """
    流式状态追踪器。

    使用 Map-based 层级追踪（参考 Langfuse 的 runs + _child_to_parent_run_id_map），
    而非 stack-based 方式，正确支持并发事件和乱序到达。
    """

    def __init__(self, thread_id: str):
        self.thread_id = thread_id
        self.all_messages: list[BaseMessage] = []
        self.assistant_content = ""
        self.stopped = False
        self.has_error = False

        # 中断状态
        self.interrupted = False
        self.interrupt_node: str | None = None
        self.interrupt_state: dict | None = None

        # ============ Trace / Observation 追踪 ============
        self.trace_id: str = str(uuid.uuid4())
        self.trace_start_time: float = time.time() * 1000  # epoch ms

        # 核心映射（参考 Langfuse CallbackHandler）
        # run_id -> ObservationRecord (活跃的 observation)
        self._active: dict[str, ObservationRecord] = {}
        # run_id -> parent_run_id (层级关系)
        self._parent_map: dict[str, Optional[str]] = {}
        # 所有已完成的 observation (用于持久化)
        self._completed: list[ObservationRecord] = []
        # run_id -> observation_id (映射)
        self._run_to_obs: dict[str, str] = {}
        # observation_id -> run_id (反向映射)
        self._obs_to_run: dict[str, str] = {}
        # 首 token 标记追踪
        self._completion_start_tracked: set[str] = set()

    def append_content(self, chunk: str):
        """追加内容块"""
        self.assistant_content += chunk

    # ============ Observation 生命周期 ============

    def create_observation(
        self,
        *,
        run_id: str,
        parent_run_id: Optional[str] = None,
        obs_type: ObsType,
        name: Optional[str] = None,
        input_data: Optional[Any] = None,
        model_name: Optional[str] = None,
        model_provider: Optional[str] = None,
        model_parameters: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        """
        创建 observation，用 parent_run_id 建立层级（而非 stack push）。

        参考 Langfuse _attach_observation() + _child_to_parent_run_id_map。

        Returns:
            observation_id
        """
        obs_id = str(uuid.uuid4())

        # 建立层级关系
        self._parent_map[run_id] = parent_run_id

        # 解析 parent_observation_id（类似 Langfuse 的 _get_parent_observation）
        parent_obs_id: Optional[str] = None
        if parent_run_id and parent_run_id in self._run_to_obs:
            parent_obs_id = self._run_to_obs[parent_run_id]

        record = ObservationRecord(
            id=obs_id,
            trace_id=self.trace_id,
            parent_observation_id=parent_obs_id,
            type=obs_type,
            name=name,
            start_time=time.time() * 1000,
            input_data=input_data,
            model_name=model_name,
            model_provider=model_provider,
            model_parameters=model_parameters,
            metadata=metadata,
        )

        self._active[obs_id] = record
        self._run_to_obs[run_id] = obs_id
        self._obs_to_run[obs_id] = run_id

        return obs_id

    def end_observation(
        self,
        run_id: str,
        *,
        output_data: Optional[Any] = None,
        level: Optional[ObsLevel] = None,
        status_message: Optional[str] = None,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        status: ObsStatus = ObsStatus.COMPLETED,
    ) -> Optional[str]:
        """
        完成 observation 并移入已完成列表。

        参考 Langfuse _detach_observation()。

        Returns:
            observation_id，或 None（如果 run_id 未找到）
        """
        obs_id = self._run_to_obs.get(run_id)
        if not obs_id:
            logger.debug(f"end_observation: no observation for run_id={run_id[:8]}...")
            return None

        record = self._active.pop(obs_id, None)
        if not record:
            logger.debug(f"end_observation: observation {obs_id[:8]} not active")
            return obs_id  # 可能已经被 end 过

        now = time.time() * 1000
        record.end_time = now
        record.duration_ms = int(now - record.start_time)
        record.status = status

        if output_data is not None:
            record.output_data = output_data
        if level is not None:
            record.level = level
        if status_message is not None:
            record.status_message = status_message[:2000]  # 限制长度
        if prompt_tokens is not None:
            record.prompt_tokens = prompt_tokens
        if completion_tokens is not None:
            record.completion_tokens = completion_tokens
        if total_tokens is not None:
            record.total_tokens = total_tokens

        self._completed.append(record)

        # 清理映射
        del self._run_to_obs[run_id]
        self._obs_to_run.pop(obs_id, None)

        return obs_id

    def get_observation_id(self, run_id: str) -> Optional[str]:
        """获取 run_id 对应的 observation_id"""
        return self._run_to_obs.get(run_id)

    def get_parent_observation_id(self, run_id: str) -> Optional[str]:
        """获取 run_id 的父 observation_id（用于 SSE envelope）"""
        parent_run = self._parent_map.get(run_id)
        if parent_run and parent_run in self._run_to_obs:
            return self._run_to_obs[parent_run]
        return None

    def track_completion_start(self, run_id: str) -> None:
        """记录 GENERATION 的首 token 时间"""
        obs_id = self._run_to_obs.get(run_id)
        if obs_id and obs_id not in self._completion_start_tracked:
            record = self._active.get(obs_id)
            if record and record.type == ObsType.GENERATION:
                record.completion_start_time = time.time() * 1000
                self._completion_start_tracked.add(obs_id)

    def get_all_observations(self) -> list[ObservationRecord]:
        """
        获取所有 observations（已完成 + 未完成）。
        未完成的标记为 INTERRUPTED。
        """
        all_obs = list(self._completed)
        for obs in self._active.values():
            obs.status = ObsStatus.INTERRUPTED
            obs.end_time = time.time() * 1000
            obs.duration_ms = int(obs.end_time - obs.start_time)
            all_obs.append(obs)
        return all_obs


# ============ StreamEventHandler ============


class StreamEventHandler:
    """
    流式事件处理器（生产级）。

    所有 handle_* 方法签名统一接收 run_id 和 parent_run_id，
    使用 StreamState 的 map-based observation 管理。
    """

    @staticmethod
    def _extract_metadata(event: dict) -> dict:
        """提取标准化元数据"""
        metadata = event.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        config = metadata.get("config", {})
        if not isinstance(config, dict):
            config = {}
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
        if not isinstance(metadata, dict):
            metadata = {}
        config = metadata.get("config", {})
        if not isinstance(config, dict):
            config = {}

        node_name = metadata.get("langgraph_node") or event.get("name") or "unknown"

        tags = config.get("tags") or metadata.get("tags") or event.get("tags") or []
        if not isinstance(tags, list):
            tags = []

        first_tag = tags[0] if tags else None
        first_tag_label = first_tag.get("label") if isinstance(first_tag, dict) else None

        node_label = (
            config.get("node_label")
            or metadata.get("node_label")
            or first_tag_label
            or node_name.replace("_", " ").title()
        )

        return {
            "node_name": node_name,
            "node_label": node_label,
            "node_id": config.get("node_id") or metadata.get("node_id"),
            "node_type": config.get("node_type") or metadata.get("node_type"),
        }

    @staticmethod
    def _extract_model_parameters(event: dict) -> Optional[dict]:
        """从 LangGraph 事件中提取模型参数（temperature, max_tokens 等）"""
        metadata = event.get("metadata", {})
        if not isinstance(metadata, dict):
            return None
        invocation_params = metadata.get("ls_model_kwargs") or {}
        if not isinstance(invocation_params, dict):
            return None

        params = {}
        for key in [
            "temperature",
            "max_tokens",
            "max_completion_tokens",
            "top_p",
            "frequency_penalty",
            "presence_penalty",
            "stop",
            "request_timeout",
        ]:
            if key in invocation_params:
                params[key] = invocation_params[key]

        return params if params else None

    @staticmethod
    def format_sse(
        event_type: str,
        payload: dict,
        thread_id: str,
        state: Optional["StreamState"] = None,
    ) -> str:
        """
        构造标准 SSE Envelope。

        包含 trace / observation 层级信息。
        序列化失败时降级为简化事件。
        """
        meta = payload.pop("_meta", {})

        def _default(obj: Any) -> Any:
            if isinstance(obj, BaseMessage):
                return {
                    "type": obj.__class__.__name__,
                    "content": str(obj.content) if hasattr(obj, "content") else str(obj),
                }
            if isinstance(obj, Enum):
                return obj.value
            if hasattr(obj, "model_dump"):
                try:
                    return obj.model_dump()
                except Exception:
                    pass
            if hasattr(obj, "dict"):
                try:
                    return obj.dict()
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
            "trace_id": meta.get("trace_id", state.trace_id if state else ""),
            "observation_id": meta.get("observation_id", ""),
            "parent_observation_id": meta.get("parent_observation_id", ""),
            "data": payload,
        }

        try:
            return f"data: {json.dumps(envelope, ensure_ascii=False, default=_default)}\n\n"
        except (TypeError, ValueError, OverflowError) as e:
            logger.warning(f"SSE serialization failed for {event_type}: {e}")
            fallback = {
                "type": event_type,
                "thread_id": thread_id,
                "timestamp": int(time.time() * 1000),
                "trace_id": state.trace_id if state else "",
                "data": {"_serialization_error": str(e)[:200]},
            }
            return f"data: {json.dumps(fallback)}\n\n"

    # ==================== Handler Methods ====================

    async def handle_chat_model_start(
        self, event: dict, state: StreamState, run_id: str, parent_run_id: Optional[str]
    ) -> str:
        """处理模型开始事件。创建 GENERATION observation。"""
        try:
            event_data = event.get("data", {})
            input_data = event_data.get("input", {})
            raw_messages = input_data.get("messages", [])

            serialized_messages = serialize_messages(raw_messages)

            metadata = event.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            model_name = metadata.get("ls_model_name") or event.get("name", "unknown")
            model_provider = metadata.get("ls_provider") or "unknown"
            model_parameters = self._extract_model_parameters(event)

            obs_id = state.create_observation(
                run_id=run_id,
                parent_run_id=parent_run_id,
                obs_type=ObsType.GENERATION,
                name=model_name,
                input_data=truncate_data({"messages": serialized_messages}),
                model_name=model_name,
                model_provider=model_provider,
                model_parameters=model_parameters,
            )

            meta = self._extract_metadata(event)
            meta["trace_id"] = state.trace_id
            meta["observation_id"] = obs_id
            meta["parent_observation_id"] = state.get_parent_observation_id(run_id) or ""

            return self.format_sse(
                "model_input",
                {
                    "messages": serialized_messages,
                    "model_name": model_name,
                    "model_provider": model_provider,
                    "_meta": meta,
                },
                state.thread_id,
                state,
            )
        except Exception as e:
            logger.exception(f"handle_chat_model_start failed: {e}")
            return self.format_sse(
                "model_input",
                {
                    "messages": [],
                    "model_name": "unknown",
                    "model_provider": "unknown",
                    "_meta": self._extract_metadata(event),
                },
                state.thread_id,
                state,
            )

    async def handle_chat_model_stream(
        self, event: dict, state: StreamState, run_id: str, parent_run_id: Optional[str]
    ) -> Optional[str]:
        """处理文本流事件。记录首 token 时间。"""
        try:
            chunk = event.get("data", {}).get("chunk")
            if not chunk or not hasattr(chunk, "content") or not chunk.content:
                return None

            content = chunk.content
            state.append_content(content)

            # 记录首 token 时间
            state.track_completion_start(run_id)

            obs_id = state.get_observation_id(run_id) or ""

            meta = self._extract_metadata(event)
            meta["trace_id"] = state.trace_id
            meta["observation_id"] = obs_id
            meta["parent_observation_id"] = state.get_parent_observation_id(run_id) or ""

            return self.format_sse("content", {"delta": content, "_meta": meta}, state.thread_id, state)
        except Exception as e:
            logger.exception(f"handle_chat_model_stream failed: {e}")
            return None

    async def handle_chat_model_end(
        self, event: dict, state: StreamState, run_id: str, parent_run_id: Optional[str]
    ) -> str:
        """处理模型结束事件。精确解析 token usage（多厂商兼容）。"""
        try:
            event_data = event.get("data", {})
            output = event_data.get("output")

            metadata = event.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            model_name = metadata.get("ls_model_name") or event.get("name", "unknown")
            model_provider = metadata.get("ls_provider") or "unknown"

            # 多源 token usage 提取
            usage = extract_usage_from_output(output)
            prompt_tokens = usage.get("input", 0) if usage else 0
            completion_tokens = usage.get("output", 0) if usage else 0
            total_tokens = usage.get("total", 0) if usage else 0

            # 原始 usage_metadata 供前端展示
            usage_metadata = None
            if output and hasattr(output, "usage_metadata") and output.usage_metadata:
                um = output.usage_metadata
                if hasattr(um, "__dict__"):
                    usage_metadata = {k: v for k, v in um.__dict__.items() if not k.startswith("_")}
                elif isinstance(um, dict):
                    usage_metadata = um

            # 完成 GENERATION observation
            output_summary = truncate_data(str(output), max_length=2000) if output else None
            obs_id = state.end_observation(
                run_id,
                output_data={"output": output_summary} if output_summary else None,
                prompt_tokens=prompt_tokens or None,
                completion_tokens=completion_tokens or None,
                total_tokens=total_tokens or None,
            )

            meta = self._extract_metadata(event)
            meta["trace_id"] = state.trace_id
            meta["observation_id"] = obs_id or ""
            meta["parent_observation_id"] = state.get_parent_observation_id(run_id) or ""

            return self.format_sse(
                "model_output",
                {
                    "output": output,
                    "model_name": model_name,
                    "model_provider": model_provider,
                    "usage_metadata": usage_metadata,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "_meta": meta,
                },
                state.thread_id,
                state,
            )
        except Exception as e:
            logger.exception(f"handle_chat_model_end failed: {e}")
            return self.format_sse(
                "model_output",
                {
                    "output": None,
                    "model_name": "unknown",
                    "model_provider": "unknown",
                    "_meta": self._extract_metadata(event),
                },
                state.thread_id,
                state,
            )

    async def handle_tool_start(
        self, event: dict, state: StreamState, run_id: str, parent_run_id: Optional[str]
    ) -> str:
        """处理工具开始事件。创建 TOOL observation。"""
        try:
            tool_input = event.get("data", {}).get("input", {})
            if isinstance(tool_input, dict):
                tool_input = {k: v for k, v in tool_input.items() if k != "runtime"}

            tool_name = event.get("name")

            obs_id = state.create_observation(
                run_id=run_id,
                parent_run_id=parent_run_id,
                obs_type=ObsType.TOOL,
                name=tool_name,
                input_data=truncate_data({"tool_input": tool_input}),
            )

            meta = self._extract_metadata(event)
            meta["trace_id"] = state.trace_id
            meta["observation_id"] = obs_id
            meta["parent_observation_id"] = state.get_parent_observation_id(run_id) or ""

            return self.format_sse(
                "tool_start",
                {"tool_name": tool_name, "tool_input": tool_input, "_meta": meta},
                state.thread_id,
                state,
            )
        except Exception as e:
            logger.exception(f"handle_tool_start failed: {e}")
            return self.format_sse(
                "tool_start",
                {"tool_name": event.get("name"), "tool_input": {}, "_meta": self._extract_metadata(event)},
                state.thread_id,
                state,
            )

    async def handle_tool_end(self, event: dict, state: StreamState, run_id: str, parent_run_id: Optional[str]) -> str:
        """处理工具结束事件。完成 TOOL observation。"""
        try:
            raw_output = event.get("data", {}).get("output")
            output = raw_output.content if hasattr(raw_output, "content") else raw_output
            tool_name = event.get("name")

            # 检测错误
            has_error = _detect_error(output)

            output_summary = truncate_data(str(output), max_length=2000) if output else None
            obs_id = state.end_observation(
                run_id,
                output_data={"tool_output": output_summary} if output_summary else None,
                level=ObsLevel.ERROR if has_error else ObsLevel.DEFAULT,
                status_message=str(output)[:500] if has_error else None,
                status=ObsStatus.FAILED if has_error else ObsStatus.COMPLETED,
            )

            # 计算时长
            record = None
            for rec in state._completed:
                if rec.id == obs_id:
                    record = rec
                    break
            duration = record.duration_ms if record else None

            meta = self._extract_metadata(event)
            meta["trace_id"] = state.trace_id
            meta["observation_id"] = obs_id or ""
            meta["parent_observation_id"] = state.get_parent_observation_id(run_id) or ""

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
                state,
            )
        except Exception as e:
            logger.exception(f"handle_tool_end failed: {e}")
            return self.format_sse(
                "tool_end",
                {
                    "tool_name": event.get("name"),
                    "tool_output": None,
                    "status": "error",
                    "_meta": self._extract_metadata(event),
                },
                state.thread_id,
                state,
            )

    async def handle_node_start(
        self, event: dict, state: StreamState, run_id: str, parent_run_id: Optional[str]
    ) -> str:
        """处理节点开始事件。创建 SPAN observation。"""
        try:
            node_info = self._extract_node_info(event)
            node_name = node_info["node_name"]

            obs_id = state.create_observation(
                run_id=run_id,
                parent_run_id=parent_run_id,
                obs_type=ObsType.SPAN,
                name=node_name,
                metadata={"node_label": node_info.get("node_label"), "node_type": node_info.get("node_type")},
            )

            meta = self._extract_metadata(event)
            meta.update(node_info)
            meta["trace_id"] = state.trace_id
            meta["observation_id"] = obs_id
            meta["parent_observation_id"] = state.get_parent_observation_id(run_id) or ""

            return self.format_sse(
                "node_start",
                {
                    "node_name": node_name,
                    "node_label": node_info.get("node_label", node_name),
                    "node_id": node_info.get("node_id"),
                    "_meta": meta,
                },
                state.thread_id,
                state,
            )
        except Exception as e:
            logger.exception(f"handle_node_start failed: {e}")
            return self.format_sse(
                "node_start",
                {"node_name": "unknown", "node_label": "Unknown", "_meta": self._extract_metadata(event)},
                state.thread_id,
                state,
            )

    async def handle_node_end(
        self, event: dict, state: StreamState, run_id: str, parent_run_id: Optional[str]
    ) -> list[str]:
        """处理节点结束事件。返回多个 SSE 事件。"""
        try:
            node_info = self._extract_node_info(event)
            node_name = node_info["node_name"]
            node_type = node_info.get("node_type", "unknown")

            output = event.get("data", {}).get("output")
            has_error = _detect_error(output)

            # 完成 SPAN observation
            output_summary = None
            if output and isinstance(output, dict):
                output_summary = truncate_data(
                    {k: str(v)[:500] for k, v in list(output.items())[:10]},
                    max_length=5000,
                )

            obs_id = state.end_observation(
                run_id,
                output_data=output_summary,
                level=ObsLevel.ERROR if has_error else ObsLevel.DEFAULT,
                status_message=str(output)[:500] if has_error else None,
                status=ObsStatus.FAILED if has_error else ObsStatus.COMPLETED,
            )

            # 计算时长
            record = None
            for rec in state._completed:
                if rec.id == obs_id:
                    record = rec
                    break
            duration = record.duration_ms if record else None

            meta = self._extract_metadata(event)
            meta.update(node_info)
            meta["trace_id"] = state.trace_id
            meta["observation_id"] = obs_id or ""
            meta["parent_observation_id"] = state.get_parent_observation_id(run_id) or ""

            events: list[str] = []

            # 0. CodeAgent 事件
            if output and isinstance(output, dict):
                code_agent_events = output.get("code_agent_events", [])
                if code_agent_events:
                    events.extend(self._process_code_agent_events(code_agent_events, node_name, meta, state))

            # 获取当前节点的局部输出 (如果是 Option B 数据流)
            local_payload = None
            if output and isinstance(output, dict):
                node_outputs = output.get("node_outputs", {})
                if node_id := node_info.get("node_id"):
                    local_payload = node_outputs.get(node_id)
                elif node_name in node_outputs:  # Fallback backwards compat
                    local_payload = node_outputs.get(node_name)

            # 1. node_end 事件
            events.append(
                self.format_sse(
                    "node_end",
                    {
                        "node_name": node_name,
                        "node_label": node_info.get("node_label", node_name),
                        "node_id": node_info.get("node_id"),
                        "duration": duration,
                        "status": "error" if has_error else "success",
                        "payload": local_payload,  # Option B localized output
                        "_meta": meta,
                    },
                    state.thread_id,
                    state,
                )
            )

            # 2. Command / state 相关事件
            if output and isinstance(output, dict):
                events.extend(self._process_output_events(output, node_info, node_type, meta, state))

            return events
        except Exception as e:
            logger.exception(f"handle_node_end failed: {e}")
            meta = self._extract_metadata(event)
            return [
                self.format_sse(
                    "node_end",
                    {"node_name": "unknown", "status": "error", "_meta": meta},
                    state.thread_id,
                    state,
                )
            ]

    # ==================== Private Helpers ====================

    def _process_code_agent_events(
        self, code_agent_events: list, node_name: str, meta: dict, state: StreamState
    ) -> list[str]:
        """处理 CodeAgent 事件列表"""
        events = []
        type_map = {
            "thought": "code_agent_thought",
            "code": "code_agent_code",
            "observation": "code_agent_observation",
            "final_answer": "code_agent_final_answer",
            "planning": "code_agent_planning",
            "error": "code_agent_error",
        }

        for ca_event in code_agent_events:
            ca_type = ca_event.get("type", "unknown")
            ca_content = ca_event.get("content", "")
            ca_step = ca_event.get("step", 0)
            ca_metadata = ca_event.get("metadata", {})

            sse_type = type_map.get(ca_type)
            if not sse_type:
                continue

            payload: dict[str, Any] = {"node_name": node_name, "step": ca_step, "_meta": meta}

            if ca_type == "thought":
                payload["content"] = ca_content
            elif ca_type == "code":
                payload["code"] = ca_content
            elif ca_type == "observation":
                payload["observation"] = ca_content
                payload["has_error"] = bool(ca_metadata.get("error"))
            elif ca_type == "final_answer":
                payload["answer"] = ca_content
            elif ca_type == "planning":
                payload["plan"] = ca_content
                payload["is_update"] = ca_metadata.get("is_update", False)
            elif ca_type == "error":
                payload["error"] = ca_content

            events.append(self.format_sse(sse_type, payload, state.thread_id, state))

        return events

    def _process_output_events(
        self, output: dict, node_info: dict, node_type: str, meta: dict, state: StreamState
    ) -> list[str]:
        """处理节点 output 中的 Command / route / loop / parallel 事件"""
        events = []
        node_name = node_info["node_name"]
        route_decision = output.get("route_decision")
        route_reason = output.get("route_reason")

        # 路由决策
        if node_type in ["condition", "router", "loop"] and route_decision:
            events.append(
                self.format_sse(
                    "route_decision",
                    {
                        "node_id": node_info.get("node_id") or node_name,
                        "node_type": node_type,
                        "result": route_decision,
                        "reason": route_reason or f"路由决策: {route_decision}",
                        "goto": "unknown",
                    },
                    state.thread_id,
                    state,
                )
            )

        # Command 事件
        cleaned_update = {}
        for k, v in output.items():
            if k in ["route_decision", "route_reason"]:
                continue
            if k == "task_results" and isinstance(v, list):
                cleaned_update[k] = _clean_task_results(v)
            else:
                cleaned_update[k] = v

        events.append(
            self.format_sse(
                "command",
                {"update": cleaned_update, "goto": None, "reason": route_reason},
                state.thread_id,
                state,
            )
        )

        # 循环迭代
        loop_count = output.get("loop_count")
        if loop_count is not None:
            events.append(
                self.format_sse(
                    "loop_iteration",
                    {
                        "loop_node_id": node_info.get("node_id") or node_name,
                        "iteration": loop_count,
                        "max_iterations": output.get("max_loop_iterations", 0),
                        "condition_met": output.get("loop_condition_met", False),
                        "reason": output.get("route_reason") or f"第 {loop_count} 次迭代",
                    },
                    state.thread_id,
                    state,
                )
            )

        # 并行任务
        task_states = output.get("task_states")
        if task_states and isinstance(task_states, dict):
            for task_id, task_state in task_states.items():
                if isinstance(task_state, dict):
                    status_map = {"running": "started", "completed": "completed", "error": "error"}
                    events.append(
                        self.format_sse(
                            "parallel_task",
                            {
                                "task_id": task_id,
                                "status": status_map.get(task_state.get("status", ""), "started"),
                                "result": task_state.get("result"),
                                "error_msg": task_state.get("error_msg"),
                            },
                            state.thread_id,
                            state,
                        )
                    )

        # 状态更新
        updated_fields = [k for k in output.keys() if k not in ["route_decision", "route_reason"]]
        if updated_fields:
            events.append(
                self.format_sse(
                    "state_update",
                    {"updated_fields": updated_fields, "state_snapshot": output},
                    state.thread_id,
                    state,
                )
            )

        return events


# ============ Module-level Helpers ============


def _detect_error(output: Any) -> bool:
    """检测 output 中是否包含错误信息"""
    if isinstance(output, dict):
        return any(output.get(k) is not None for k in ("error", "exception", "Error"))
    if isinstance(output, str):
        lower = output.lower()
        return any(kw in lower for kw in ("error", "exception", "failed", "failure"))
    return False


def _clean_task_results(task_results: list) -> list:
    """清理 task_results 中的循环引用"""
    cleaned = []
    for tr in task_results:
        if isinstance(tr, dict):
            result = {"status": tr.get("status"), "task_id": tr.get("task_id")}
            if "error_msg" in tr:
                result["error_msg"] = tr.get("error_msg")
            rv = tr.get("result")
            if isinstance(rv, dict):
                result["result"] = {k: v for k, v in rv.items() if k != "task_results"}
            else:
                result["result"] = rv
            cleaned.append(result)
        else:
            cleaned.append(tr)
    return cleaned
