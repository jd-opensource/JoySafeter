"""OpenAI provider implementation."""

import asyncio
import time
from typing import Any, Dict, List, Union

from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

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

# GPT-4 pricing (per million tokens)
GPT4_INPUT_COST = 30.0
GPT4_OUTPUT_COST = 60.0


class OpenAIProvider:
    """
    OpenAI API provider.

    Supports GPT-4, GPT-3.5, and compatible APIs.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        default_model: str = "gpt-4-turbo-preview",
        max_retries: int = 3,
    ):
        """
        Initialize OpenAI provider.

        Args:
            api_key: OpenAI API key
            base_url: Custom base URL (for Azure, etc.)
            default_model: Default model to use
            max_retries: Maximum retry attempts
        """
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
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
        """Get completion from OpenAI."""
        start_time = time.time()
        model = options.model or self.default_model

        # Format messages
        api_messages = self._format_messages(messages, system_prompt)

        # Build request params
        params = {
            "model": model,
            "messages": api_messages,
            "max_tokens": options.max_tokens or 4096,
        }

        if tools:
            params["tools"] = [self._format_tool(t) for t in tools]
            params["tool_choice"] = "auto"

        if options.temperature is not None:
            params["temperature"] = options.temperature

        # Call API
        try:
            response = await self._call_with_retry(params, abort_signal)
        except Exception as e:
            return AssistantMessage(
                id="error",
                content=[TextBlock(text=f"API Error: {str(e)}")],
                usage=Usage(),
                is_api_error=True,
                duration_ms=int((time.time() - start_time) * 1000),
            )

        duration_ms = int((time.time() - start_time) * 1000)
        return self._convert_response(response, duration_ms)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=32))
    async def _call_with_retry(self, params: Dict[str, Any], abort_signal: asyncio.Event):
        """Call API with retry."""
        if abort_signal.is_set():
            raise Exception("Request aborted")

        response = await self.client.chat.completions.create(**params)
        return response

    def _format_messages(self, messages: List[MessageParam], system_prompt: List[str]) -> List[Dict[str, Any]]:
        """Format messages for OpenAI API."""
        result: List[Dict[str, Any]] = []

        # Add system prompt
        if system_prompt:
            result.append({"role": "system", "content": "\n\n".join(system_prompt)})

        # Add conversation messages
        for msg in messages:
            content = msg.content
            if isinstance(content, str):
                result.append({"role": msg.role.value, "content": content})
            else:
                # Convert content blocks - OpenAI accepts list of content blocks
                formatted_content = self._format_content(content)
                result.append({"role": msg.role.value, "content": formatted_content})

        return result

    def _format_content(self, content: List[Any]) -> List[Dict[str, Any]]:
        """Format content blocks."""
        result = []
        for block in content:
            if hasattr(block, "type"):
                if block.type == "text":
                    result.append({"type": "text", "text": block.text})
                elif block.type == "tool_result":
                    # OpenAI uses different format
                    result.append({"type": "text", "text": f"Tool result: {block.content}"})
        return result if result else [{"type": "text", "text": ""}]

    def _format_tool(self, tool: Dict[str, Any]) -> Dict[str, Any]:
        """Format tool for OpenAI API."""
        return {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {}),
            },
        }

    def _convert_response(self, response: Any, duration_ms: int) -> AssistantMessage:
        """Convert OpenAI response to our format."""
        choice = response.choices[0]
        message = choice.message

        # Convert content - AssistantMessage.content is List[Union[TextBlock, ToolUseBlock, ThinkingBlock]]
        content: List[Union[TextBlock, ToolUseBlock, ThinkingBlock]] = []
        if message.content:
            content.append(TextBlock(text=message.content))

        # Convert tool calls
        if message.tool_calls:
            for tool_call in message.tool_calls:
                content.append(
                    ToolUseBlock(
                        id=tool_call.id,
                        name=tool_call.function.name,
                        input=eval(tool_call.function.arguments),  # Parse JSON
                    )
                )

        # Calculate cost (simplified)
        usage = response.usage
        cost = calculate_cost(
            {"input_tokens": usage.prompt_tokens, "output_tokens": usage.completion_tokens},
            GPT4_INPUT_COST,
            GPT4_OUTPUT_COST,
        )

        return AssistantMessage(
            id=response.id,
            content=content,
            stop_reason=choice.finish_reason,
            usage=Usage(input_tokens=usage.prompt_tokens, output_tokens=usage.completion_tokens),
            cost_usd=cost,
            duration_ms=duration_ms,
        )
