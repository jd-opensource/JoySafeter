"""
Stream Event Handler (Production)

Process LangGraph event streams and convert them to standardized SSE format.
Use map-based hierarchy tracking (modeled after Langfuse CallbackHandler architecture),
establishing N-level observation hierarchy via run_id + parent_run_id.

Core design:
- StreamState: map-based observation management (replaces stack)
- ObservationRecord: enhanced in-memory observation record
- StreamEventHandler: event -> SSE conversion; all handlers receive run_id/parent_run_id
- format_sse: safe serialization with graceful degradation
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

# ============ LangGraph control-flow exceptions (not marked as ERROR) ============

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
    In-memory observation record.
    Batch-written to the database after the SSE stream ends.
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
    completion_start_time: Optional[float] = None  # time-to-first-token (GENERATION)
    # Meta
    metadata: Optional[dict] = None
    version: Optional[str] = None  # code/model version


# ============ StreamState ============


class StreamState:
    """
    Streaming state tracker.

    Use map-based hierarchy tracking (modeled after Langfuse runs + _child_to_parent_run_id_map)
    instead of stack-based approach, correctly supporting concurrent and out-of-order events.
    """

    def __init__(self, thread_id: str):
        self.thread_id = thread_id
        self.all_messages: list[BaseMessage] = []
        self.assistant_content = ""
        self.stopped = False
        self.has_error = False

        # agent run artifacts directory (artifacts API)
        self.artifact_run_id: str = str(uuid.uuid4())

        # interrupt state
        self.interrupted = False
        self.interrupt_node: str | None = None
        self.interrupt_state: dict | None = None

        # ============ Trace / Observation tracking ============
        self.trace_id: str = str(uuid.uuid4())
        self.trace_start_time: float = time.time() * 1000  # epoch ms

        # core mappings (modeled after Langfuse CallbackHandler)
        # run_id -> ObservationRecord (active observations)
        self._active: dict[str, ObservationRecord] = {}
        # run_id -> parent_run_id (hierarchy)
        self._parent_map: dict[str, Optional[str]] = {}
        # all completed observations (for persistence)
        self._completed: list[ObservationRecord] = []
        # run_id -> observation_id mapping
        self._run_to_obs: dict[str, str] = {}
        # observation_id -> run_id (reverse mapping)
        self._obs_to_run: dict[str, str] = {}
        # first-token tracking
        self._completion_start_tracked: set[str] = set()

    def append_content(self, chunk: str):
        """Append a content chunk."""
        self.assistant_content += chunk

    # ============ Observation lifecycle ============

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
        Create an observation, establishing hierarchy via parent_run_id (not stack push).

        Modeled after Langfuse _attach_observation() + _child_to_parent_run_id_map.

        Returns:
            observation_id
        """
        obs_id = str(uuid.uuid4())

        # establish hierarchy
        self._parent_map[run_id] = parent_run_id

        # resolve parent_observation_id (similar to Langfuse _get_parent_observation)
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
        Complete an observation and move it to the completed list.

        Modeled after Langfuse _detach_observation().

        Returns:
            observation_id, or None if run_id was not found
        """
        obs_id = self._run_to_obs.get(run_id)
        if not obs_id:
            logger.debug(f"end_observation: no observation for run_id={run_id[:8]}...")
            return None

        record = self._active.pop(obs_id, None)
        if not record:
            logger.debug(f"end_observation: observation {obs_id[:8]} not active")
            return obs_id  # may have already been ended

        now = time.time() * 1000
        record.end_time = now
        record.duration_ms = int(now - record.start_time)
        record.status = status

        if output_data is not None:
            record.output_data = output_data
        if level is not None:
            record.level = level
        if status_message is not None:
            record.status_message = status_message[:2000]  # cap length
        if prompt_tokens is not None:
            record.prompt_tokens = prompt_tokens
        if completion_tokens is not None:
            record.completion_tokens = completion_tokens
        if total_tokens is not None:
            record.total_tokens = total_tokens

        self._completed.append(record)

        # clean up mappings
        del self._run_to_obs[run_id]
        self._obs_to_run.pop(obs_id, None)

        return obs_id

    def get_observation_id(self, run_id: str) -> Optional[str]:
        """Return the observation_id for a given run_id."""
        return self._run_to_obs.get(run_id)

    def get_parent_observation_id(self, run_id: str) -> Optional[str]:
        """Return the parent observation_id for a run_id (used in SSE envelope)."""
        parent_run = self._parent_map.get(run_id)
        if parent_run and parent_run in self._run_to_obs:
            return self._run_to_obs[parent_run]
        return None

    def track_completion_start(self, run_id: str) -> None:
        """Record time-to-first-token for a GENERATION observation."""
        obs_id = self._run_to_obs.get(run_id)
        if obs_id and obs_id not in self._completion_start_tracked:
            record = self._active.get(obs_id)
            if record and record.type == ObsType.GENERATION:
                record.completion_start_time = time.time() * 1000
                self._completion_start_tracked.add(obs_id)

    def get_all_observations(self) -> list[ObservationRecord]:
        """
        Return all observations (completed + incomplete).
        Mark incomplete ones as INTERRUPTED.
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
    Production-grade streaming event handler.

    All handle_* methods uniformly accept run_id and parent_run_id,
    using StreamState's map-based observation management.
    """

    @staticmethod
    def _extract_metadata(event: dict) -> dict:
        """Extract standardized metadata."""
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
        """Extract node info (name, label, ID, etc.)."""
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
        """Extract model parameters (temperature, max_tokens, etc.) from a LangGraph event."""
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
        Build a standard SSE envelope.

        Include trace / observation hierarchy info.
        Degrade to a simplified event on serialization failure.
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

    # Max chars per message content in the model_input SSE frame.
    # The system prompt + full conversation history in skill-creator turns can
    # easily exceed 500 KB, causing the WS frame to be dropped by the browser.
    _MODEL_INPUT_MSG_CONTENT_LIMIT = 2000

    @staticmethod
    def _truncate_messages_for_sse(messages: list[dict]) -> list[dict]:
        """Truncate individual message content so the model_input SSE frame stays small.

        Keeps message structure (role, tool_calls, etc.) intact; only shortens
        the 'content' field of each message to avoid oversized WS frames.
        """
        limit = StreamEventHandler._MODEL_INPUT_MSG_CONTENT_LIMIT
        result = []
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, str) and len(content) > limit:
                msg = {**msg, "content": content[:limit] + "… [truncated]"}
            elif isinstance(content, list):
                # Multimodal content blocks — truncate text parts
                truncated_parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text = part.get("text", "")
                        if len(text) > limit:
                            part = {**part, "text": text[:limit] + "… [truncated]"}
                    truncated_parts.append(part)
                msg = {**msg, "content": truncated_parts}
            result.append(msg)
        return result

    async def handle_chat_model_start(
        self, event: dict, state: StreamState, run_id: str, parent_run_id: Optional[str]
    ) -> str:
        """Handle model start event. Create a GENERATION observation."""
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
                    "messages": self._truncate_messages_for_sse(serialized_messages),
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
        """Handle text stream event. Record time-to-first-token."""
        try:
            chunk = event.get("data", {}).get("chunk")
            if not chunk or not hasattr(chunk, "content") or not chunk.content:
                return None

            content = chunk.content
            state.append_content(content)

            # record time-to-first-token
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
        """Handle model end event. Parse token usage precisely (multi-vendor compatible)."""
        try:
            event_data = event.get("data", {})
            output = event_data.get("output")

            metadata = event.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            model_name = metadata.get("ls_model_name") or event.get("name", "unknown")
            model_provider = metadata.get("ls_provider") or "unknown"

            # multi-source token usage extraction
            usage = extract_usage_from_output(output)
            prompt_tokens = usage.get("input", 0) if usage else 0
            completion_tokens = usage.get("output", 0) if usage else 0
            total_tokens = usage.get("total", 0) if usage else 0

            # raw usage_metadata for frontend display
            usage_metadata = None
            if output and hasattr(output, "usage_metadata") and output.usage_metadata:
                um = output.usage_metadata
                if hasattr(um, "__dict__"):
                    usage_metadata = {k: v for k, v in um.__dict__.items() if not k.startswith("_")}
                elif isinstance(um, dict):
                    usage_metadata = um

            # complete GENERATION observation
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
        """Handle tool start event. Create a TOOL observation."""
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
        """Handle tool end event. Complete the TOOL observation."""
        try:
            raw_output = event.get("data", {}).get("output")
            output = raw_output.content if hasattr(raw_output, "content") else raw_output
            tool_name = event.get("name")

            # detect errors
            has_error = _detect_error(output)

            output_summary = truncate_data(str(output), max_length=2000) if output else None
            obs_id = state.end_observation(
                run_id,
                output_data={"tool_output": output_summary} if output_summary else None,
                level=ObsLevel.ERROR if has_error else ObsLevel.DEFAULT,
                status_message=str(output)[:500] if has_error else None,
                status=ObsStatus.FAILED if has_error else ObsStatus.COMPLETED,
            )

            # compute duration
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
        """Handle node start event. Create a SPAN observation."""
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
        """Handle node end event. Return multiple SSE events."""
        try:
            node_info = self._extract_node_info(event)
            node_name = node_info["node_name"]
            node_type = node_info.get("node_type", "unknown")

            output = event.get("data", {}).get("output")
            has_error = _detect_error(output)

            # complete SPAN observation
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

            # compute duration
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

            # 0. CodeAgent events
            if output and isinstance(output, dict):
                code_agent_events = output.get("code_agent_events", [])
                if code_agent_events:
                    events.extend(self._process_code_agent_events(code_agent_events, node_name, meta, state))

            # get the current node's local output (if using Option B data flow)
            local_payload = None
            if output and isinstance(output, dict):
                node_outputs = output.get("node_outputs", {})
                if node_id := node_info.get("node_id"):
                    local_payload = node_outputs.get(node_id)
                elif node_name in node_outputs:  # Fallback backwards compat
                    local_payload = node_outputs.get(node_name)

            # 1. node_end event
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

            # 2. Command / state related events
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
        """Process a list of CodeAgent events."""
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
        """Process Command / route / loop / parallel events from node output."""
        events = []
        node_name = node_info["node_name"]
        route_decision = output.get("route_decision")
        route_reason = output.get("route_reason")

        # routing decision
        if node_type in ["condition", "router", "loop"] and route_decision:
            events.append(
                self.format_sse(
                    "route_decision",
                    {
                        "node_id": node_info.get("node_id") or node_name,
                        "node_type": node_type,
                        "result": route_decision,
                        "reason": route_reason or f"routing decision: {route_decision}",
                        "goto": "unknown",
                    },
                    state.thread_id,
                    state,
                )
            )

        # Command events
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

        # loop iteration
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
                        "reason": output.get("route_reason") or f"iteration {loop_count}",
                    },
                    state.thread_id,
                    state,
                )
            )

        # parallel tasks
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

        # state update
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
    """Detect whether the output contains error information."""
    if isinstance(output, dict):
        return any(output.get(k) is not None for k in ("error", "exception", "Error"))
    if isinstance(output, str):
        lower = output.lower()
        return any(kw in lower for kw in ("error", "exception", "failed", "failure"))
    return False


def _clean_task_results(task_results: list) -> list:
    """Remove circular references from task_results."""
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
