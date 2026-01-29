"""Anthropic/Claude provider implementation."""

import asyncio
import time
from typing import Any, Dict, List

from anthropic import AsyncAnthropic
from anthropic.types import Message
from anthropic.types import TextBlock as AnthropicTextBlock
from anthropic.types import ToolUseBlock as AnthropicToolUseBlock
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.dynamic_agent.agent_core.providers.base import calculate_cost
from app.dynamic_agent.agent_core.types import (
    AssistantMessage,
    LLMProviderOptions,
    MessageParam,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    Usage,
)

# Claude Sonnet 3.5 pricing (per million tokens)
SONNET_INPUT_COST = 3.0
SONNET_OUTPUT_COST = 15.0
SONNET_CACHE_WRITE_COST = 3.75
SONNET_CACHE_READ_COST = 0.3

# Claude Haiku pricing
HAIKU_INPUT_COST = 0.8
HAIKU_OUTPUT_COST = 4.0
HAIKU_CACHE_WRITE_COST = 1.0
HAIKU_CACHE_READ_COST = 0.08


class AnthropicProvider:
    """
    Anthropic/Claude API provider.

    Supports:
    - Claude Sonnet 3.5 and Haiku
    - Prompt caching
    - Extended thinking
    - Streaming (future)
    - Retry with exponential backoff
    """

    def __init__(self, api_key: str, default_model: str = "claude-sonnet-3-5-20241022", max_retries: int = 3):
        """
        Initialize Anthropic provider.

        Args:
            api_key: Anthropic API key
            default_model: Default model to use
            max_retries: Maximum retry attempts
        """
        self.client = AsyncAnthropic(api_key=api_key)
        self.default_model = default_model
        self.max_retries = max_retries

    async def complete(
        self,
        messages: List[MessageParam],
        system_prompt: List[str],
        tools: List[Dict[str, Any]],
        abort_signal: asyncio.Event,
        options: LLMProviderOptions,
    ) -> AssistantMessage:
        """
        Get completion from Claude.

        Args:
            messages: Conversation history
            system_prompt: System prompt parts
            tools: Available tools
            abort_signal: Abort event
            options: Provider options

        Returns:
            Assistant message with content and usage
        """
        start_time = time.time()
        model = options.model or self.default_model

        # Format system prompt with caching
        system = self._format_system_prompt(system_prompt)

        # Format messages for API
        api_messages = self._format_messages(messages)

        # Format tools with caching
        api_tools = self._format_tools(tools) if tools else None

        # Build request params
        params = {
            "model": model,
            "max_tokens": options.max_tokens or 8192,
            "messages": api_messages,
            "system": system,
        }

        if api_tools:
            params["tools"] = api_tools

        if options.temperature is not None:
            params["temperature"] = options.temperature

        # Add extended thinking if requested
        if options.max_thinking_tokens and options.max_thinking_tokens > 0:
            params["thinking"] = {"type": "enabled", "budget_tokens": options.max_thinking_tokens}

        # Call API with retry
        try:
            response = await self._call_with_retry(params, abort_signal)
        except Exception as e:
            # Return error message
            return AssistantMessage(
                id="error",
                content=[TextBlock(text=f"API Error: {str(e)}")],
                usage=Usage(),
                is_api_error=True,
                duration_ms=int((time.time() - start_time) * 1000),
            )

        # Convert response to our format
        duration_ms = int((time.time() - start_time) * 1000)
        return self._convert_response(response, duration_ms, model)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=32),
        retry=retry_if_exception_type((Exception,)),
    )
    async def _call_with_retry(self, params: Dict[str, Any], abort_signal: asyncio.Event) -> Message:
        """Call API with retry logic."""
        if abort_signal.is_set():
            raise Exception("Request aborted")

        response = await self.client.messages.create(**params)
        return response  # type: ignore[no-any-return]

    def _format_system_prompt(self, parts: List[str]) -> List[Dict[str, Any]]:
        """Format system prompt with caching."""
        if not parts:
            return []

        # Join all parts
        full_prompt = "\n\n".join(parts)

        # Add cache control to last block
        return [{"type": "text", "text": full_prompt, "cache_control": {"type": "ephemeral"}}]

    def _format_messages(self, messages: List[MessageParam]) -> List[Dict[str, Any]]:
        """Format messages for API."""
        result: List[Dict[str, Any]] = []
        for msg in messages:
            content = msg.content
            if isinstance(content, str):
                result.append({"role": msg.role.value, "content": content})
            else:
                # List of content blocks - Anthropic API accepts list of content blocks
                formatted_blocks = [self._format_content_block(block) for block in content]
                result.append({"role": msg.role.value, "content": formatted_blocks})
        return result

    def _format_content_block(self, block: Any) -> Dict[str, Any]:
        """Format a single content block."""
        if hasattr(block, "model_dump"):
            result = block.model_dump(exclude_none=True)
            return result if isinstance(result, dict) else {"content": str(result)}
        if isinstance(block, dict):
            return block
        return {"content": str(block)}

    def _format_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Format tools with caching."""
        if not tools:
            return []

        # Add cache control to last tool
        formatted = []
        for i, tool in enumerate(tools):
            tool_dict = dict(tool)
            if i == len(tools) - 1:
                tool_dict["cache_control"] = {"type": "ephemeral"}
            formatted.append(tool_dict)

        return formatted

    def _convert_response(self, response: Message, duration_ms: int, model: str) -> AssistantMessage:
        """Convert Anthropic response to our format."""
        from typing import Union

        # Convert content blocks - AssistantMessage.content is List[Union[TextBlock, ToolUseBlock, ThinkingBlock]]
        content: List[Union[TextBlock, ToolUseBlock, ThinkingBlock]] = []
        for block in response.content:
            if isinstance(block, AnthropicTextBlock):
                content.append(TextBlock(text=block.text))
            elif isinstance(block, AnthropicToolUseBlock):
                content.append(ToolUseBlock(id=block.id, name=block.name, input=block.input))
            elif hasattr(block, "type") and block.type == "thinking":
                content.append(ThinkingBlock(text=getattr(block, "thinking", "")))

        # Calculate cost
        usage_dict = response.usage.model_dump() if hasattr(response.usage, "model_dump") else {}

        if "sonnet" in model.lower():
            cost = calculate_cost(
                usage_dict, SONNET_INPUT_COST, SONNET_OUTPUT_COST, SONNET_CACHE_WRITE_COST, SONNET_CACHE_READ_COST
            )
        else:
            cost = calculate_cost(
                usage_dict, HAIKU_INPUT_COST, HAIKU_OUTPUT_COST, HAIKU_CACHE_WRITE_COST, HAIKU_CACHE_READ_COST
            )

        return AssistantMessage(
            id=response.id,
            content=content,
            stop_reason=response.stop_reason,
            usage=Usage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                cache_creation_input_tokens=getattr(response.usage, "cache_creation_input_tokens", None),
                cache_read_input_tokens=getattr(response.usage, "cache_read_input_tokens", None),
            ),
            cost_usd=cost,
            duration_ms=duration_ms,
        )
