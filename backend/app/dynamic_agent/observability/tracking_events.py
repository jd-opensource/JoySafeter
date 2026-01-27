"""
Tracking Event Models for Queue-based Database Operations.

This module defines the event types that are sent from callback handlers
to the main event loop for database persistence.
"""

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID


class TrackingEventType(str, Enum):
    """Types of tracking events."""

    # Tool events
    TOOL_START = "tool_start"
    TOOL_END = "tool_end"
    TOOL_ERROR = "tool_error"

    # LLM events
    LLM_START = "llm_start"
    LLM_END = "llm_end"
    LLM_ERROR = "llm_error"

    # Chat model events
    CHAT_MODEL_START = "chat_model_start"
    CHAT_MODEL_END = "chat_model_end"
    CHAT_MODEL_ERROR = "chat_model_error"


@dataclass
class TrackingEvent:
    """Base tracking event."""

    event_type: TrackingEventType
    task_id: Optional[UUID]
    run_id: str
    step_key: Optional[str] = None
    pre_generated_step_id: Optional[UUID] = None  # Pre-generated step_id from callback
    timestamp: float = field(default_factory=time.time)


@dataclass
class ToolStartEvent(TrackingEvent):
    """Event when a tool starts execution."""

    event_type: TrackingEventType = field(default=TrackingEventType.TOOL_START, init=False)
    tool_name: str = ""
    input_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolEndEvent(TrackingEvent):
    """Event when a tool finishes execution."""

    event_type: TrackingEventType = field(default=TrackingEventType.TOOL_END, init=False)
    output_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolErrorEvent(TrackingEvent):
    """Event when a tool call fails."""

    event_type: TrackingEventType = field(default=TrackingEventType.TOOL_ERROR, init=False)
    error_message: str = ""


@dataclass
class LLMStartEvent(TrackingEvent):
    """Event when LLM starts generating."""

    event_type: TrackingEventType = field(default=TrackingEventType.LLM_START, init=False)
    model_name: str = ""
    prompts: List[str] = field(default_factory=list)
    invocation_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMEndEvent(TrackingEvent):
    """Event when LLM finishes generating."""

    event_type: TrackingEventType = field(default=TrackingEventType.LLM_END, init=False)
    output_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatModelStartEvent(TrackingEvent):
    """Event when ChatModel starts generating."""

    event_type: TrackingEventType = field(default=TrackingEventType.CHAT_MODEL_START, init=False)
    model_name: str = ""
    messages_data: List[Any] = field(default_factory=list)


@dataclass
class ChatModelEndEvent(TrackingEvent):
    """Event when ChatModel finishes generating."""

    event_type: TrackingEventType = field(default=TrackingEventType.CHAT_MODEL_END, init=False)
    output_data: Dict[str, Any] = field(default_factory=dict)


# Global event queue
_tracking_event_queue: Optional[asyncio.Queue] = None


def get_tracking_queue() -> asyncio.Queue:
    """Get the global tracking event queue."""
    global _tracking_event_queue
    if _tracking_event_queue is None:
        _tracking_event_queue = asyncio.Queue()
    return _tracking_event_queue
