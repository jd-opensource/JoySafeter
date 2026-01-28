"""
Core type definitions for Agent Core.

Defines the fundamental types used throughout the agent system:
- Messages (User, Assistant, Progress)
- Tool interface and results
- Context and validation types
"""

import asyncio
from enum import Enum
from typing import Any, AsyncGenerator, Dict, List, Optional, Protocol, Union

from pydantic import BaseModel, Field

# ============================================================================
# Message Types
# ============================================================================


class MessageRole(str, Enum):
    """Message role in conversation."""

    USER = "user"
    ASSISTANT = "assistant"


class ContentBlock(BaseModel):
    """Base content block."""

    type: str


class TextBlock(ContentBlock):
    """Text content block."""

    type: str = "text"
    text: str


class ToolUseBlock(ContentBlock):
    """Tool use request from assistant."""

    type: str = "tool_use"
    id: str
    name: str
    input: Dict[str, Any]


class ToolResultBlock(ContentBlock):
    """Tool execution result."""

    type: str = "tool_result"
    tool_use_id: str
    content: Union[str, List[ContentBlock]]
    is_error: bool = False


class ThinkingBlock(ContentBlock):
    """Extended thinking content (Anthropic)."""

    type: str = "thinking"
    text: str


Content = Union[str, List[Union[TextBlock, ToolUseBlock, ToolResultBlock, ThinkingBlock]]]


class MessageParam(BaseModel):
    """Message parameter for API calls."""

    role: MessageRole
    content: Content


class Usage(BaseModel):
    """Token usage statistics."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: Optional[int] = None
    cache_read_input_tokens: Optional[int] = None


class AssistantMessage(BaseModel):
    """Assistant message with metadata."""

    id: str = ""
    content: List[Union[TextBlock, ToolUseBlock, ThinkingBlock]]
    stop_reason: Optional[str] = None
    usage: Usage = Field(default_factory=Usage)
    cost_usd: float = 0.0
    duration_ms: int = 0
    is_api_error: bool = False


class UserMessage(BaseModel):
    """User message."""

    uuid: str
    message: MessageParam
    tool_use_result: Optional[Dict[str, Any]] = None


class ProgressMessage(BaseModel):
    """Progress message during tool execution."""

    uuid: str
    type: str = "progress"
    tool_use_id: str
    sibling_tool_use_ids: set[str]
    content: AssistantMessage
    normalized_messages: List[Any]
    tools: List[Any]


Message = Union[UserMessage, AssistantMessage, ProgressMessage]


# ============================================================================
# Tool Types
# ============================================================================


class ValidationResult(BaseModel):
    """Result of input validation."""

    result: bool
    message: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None


class ToolUseContext(BaseModel):
    """Context for tool execution."""

    abort_event: Any  # asyncio.Event, but avoid circular import
    options: Dict[str, Any] = Field(default_factory=dict)
    message_id: Optional[str] = None
    read_file_timestamps: Dict[str, float] = Field(default_factory=dict)

    class Config:
        arbitrary_types_allowed = True


class ToolResultProgress(BaseModel):
    """Progress update during tool execution."""

    type: str = "progress"
    content: AssistantMessage
    normalized_messages: List[Any]
    tools: List[Any]


class ToolResultFinal(BaseModel):
    """Final result from tool execution."""

    type: str = "result"
    data: Any
    result_for_assistant: Any
    normalized_messages: Optional[List[Any]] = None
    tools: Optional[List[Any]] = None


ToolResult = Union[ToolResultProgress, ToolResultFinal]


class Tool(Protocol):
    """
    Tool protocol defining the interface all tools must implement.

    This is the core abstraction that allows the agent to work with
    different tools in a uniform way.
    """

    name: str
    """Unique tool name."""

    input_schema: type[BaseModel]
    """Pydantic model class for input validation."""

    async def is_enabled(self) -> bool:
        """Check if tool is currently enabled."""
        ...

    def is_read_only(self) -> bool:
        """Check if tool only reads data (allows concurrent execution)."""
        ...

    def needs_permissions(self, input: BaseModel) -> bool:
        """Check if this tool invocation requires user permission."""
        ...

    async def validate_input(self, input: BaseModel, ctx: ToolUseContext) -> ValidationResult:
        """
        Validate tool input beyond schema validation.

        This can check file existence, path boundaries, etc.
        """
        ...

    async def call(
        self,
        input: BaseModel,
        ctx: ToolUseContext,
        can_use_tool: Any,  # CanUseToolFn type
    ) -> AsyncGenerator[ToolResult, None]:
        """
        Execute the tool and yield results.

        Can yield multiple progress updates before final result.
        """
        ...

    def user_facing_name(self, input: Optional[BaseModel] = None) -> str:
        """Get user-friendly name for this tool invocation."""
        ...

    def render_result_for_assistant(self, data: Any) -> Any:
        """Format result for assistant consumption."""
        ...


# ============================================================================
# Provider Types
# ============================================================================


class LLMProviderOptions(BaseModel):
    """Options for LLM provider."""

    model: Optional[str] = None
    max_thinking_tokens: Optional[int] = None
    dangerous_skip_permissions: bool = False
    prepend_cli_sysprompt: bool = True
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


class LLMProvider(Protocol):
    """
    LLM Provider protocol for model API abstraction.

    Allows swapping between Anthropic, OpenAI, etc.
    """

    async def complete(
        self,
        messages: List[MessageParam],
        system_prompt: List[str],
        tools: List[Dict[str, Any]],
        abort_signal: asyncio.Event,
        options: LLMProviderOptions,
    ) -> AssistantMessage:
        """
        Get completion from LLM.

        Returns a complete assistant message with tool uses if any.
        """
        ...


# ============================================================================
# Permission Types
# ============================================================================


class PermissionResult(BaseModel):
    """Result of permission check."""

    result: bool
    message: Optional[str] = None


class PermissionStrategy(Protocol):
    """
    Permission strategy for tool access control.

    Can be implemented to integrate with UI permission dialogs.
    """

    async def check(
        self, tool: Tool, input: Dict[str, Any], context: ToolUseContext, assistant_message: AssistantMessage
    ) -> PermissionResult:
        """Check if tool can be used with given input."""
        ...


# ============================================================================
# Logging Types
# ============================================================================


class Logger(Protocol):
    """Logger protocol for observability."""

    def event(self, name: str, props: Optional[Dict[str, str]] = None) -> None:
        """Log an event."""
        ...

    def error(self, err: Exception) -> None:
        """Log an error."""
        ...

    def info(self, message: str, **kwargs: Any) -> None:
        """Log info message."""
        ...

    def write_sidechain(self, path: str, messages: List[Message]) -> None:
        """Write sidechain log (optional)."""
        ...


# ============================================================================
# Runtime Types
# ============================================================================


class AgentRuntimeOptions(BaseModel):
    """Options for agent runtime."""

    dangerous_skip_permissions: bool = False
    fork_number: Optional[int] = None
    message_log_name: Optional[str] = None
    verbose: bool = False
    slow_and_capable_model: Optional[str] = None
    max_thinking_tokens: Optional[int] = None
    commands: List[Any] = Field(default_factory=list)


# class RunOptions(BaseModel):
#     """Options for a single agent run."""
#     messages: List[Message]
#     system_prompt: List[str]
#     tools: List[Tool]
#     abort_event: Any  # asyncio.Event
#     options: AgentRuntimeOptions = Field(default_factory=AgentRuntimeOptions)
#     read_file_timestamps: Dict[str, float] = Field(default_factory=dict)
#
#     class Config:
#         arbitrary_types_allowed = True
