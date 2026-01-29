"""
Agent Runtime - Core orchestration engine.

Implements the main query loop that:
1. Calls LLM to get assistant response
2. Detects tool use requests
3. Executes tools (concurrently for read-only, serially for writes)
4. Recursively continues conversation with tool results
"""

import asyncio
from typing import AsyncGenerator, List, Set

from app.dynamic_agent.agent_core.types import (
    AgentRuntimeOptions,
    AssistantMessage,
    LLMProvider,
    LLMProviderOptions,
    Logger,
    Message,
    PermissionStrategy,
    Tool,
    ToolUseBlock,
    ToolUseContext,
    UserMessage,
)
from app.dynamic_agent.agent_core.utils.messages import (
    create_assistant_message,
    create_progress_message,
    create_user_message,
    normalize_messages_for_api,
)

MAX_TOOL_USE_CONCURRENCY = 10
INTERRUPT_MESSAGE = "<<INTERRUPT>>"


# todo remove?
class AgentRuntime:
    """
    Core agent runtime that orchestrates LLM calls and tool execution.

    This is the heart of the agent system, implementing the recursive
    query loop that enables multi-turn conversations with tool use.
    """

    def __init__(
        self,
        provider: LLMProvider,
        permissions: PermissionStrategy,
        logger: Logger,
        concurrency: int = MAX_TOOL_USE_CONCURRENCY,
    ):
        """
        Initialize agent runtime.

        Args:
            provider: LLM provider for completions
            permissions: Permission strategy for tool access
            logger: Logger for events and errors
            concurrency: Max concurrent tool executions
        """
        self.provider = provider
        self.permissions = permissions
        self.logger = logger
        self.concurrency = concurrency

    async def run(
        self,
        messages: List[Message],
        system_prompt: List[str],
        tools: List[Tool],
        abort_event: asyncio.Event,
        options: AgentRuntimeOptions,
        read_file_timestamps: dict[str, float],
    ) -> AsyncGenerator[Message, None]:
        """
        Run agent conversation loop.

        This is the main entry point that:
        1. Gets LLM response
        2. Yields assistant message
        3. Detects and executes tool uses
        4. Recursively continues if tools were used

        Args:
            messages: Conversation history
            system_prompt: System prompt parts
            tools: Available tools
            abort_event: Event to signal abort
            options: Runtime options
            read_file_timestamps: File modification tracking

        Yields:
            Messages (assistant, progress, user with tool results)
        """
        # Check for abort
        if abort_event.is_set():
            yield create_assistant_message(INTERRUPT_MESSAGE)
            return

        # Format system prompt
        full_system_prompt = self._format_system_prompt(system_prompt)

        # Normalize messages for API
        api_messages = normalize_messages_for_api(messages)

        # Get assistant response
        try:
            assistant_message = await self.provider.complete(
                messages=api_messages,
                system_prompt=full_system_prompt,
                tools=[self._tool_to_dict(t) for t in tools],
                abort_signal=abort_event,
                options=LLMProviderOptions(
                    model=options.slow_and_capable_model,
                    max_thinking_tokens=options.max_thinking_tokens,
                    dangerous_skip_permissions=options.dangerous_skip_permissions,
                ),
            )
        except Exception as e:
            self.logger.error(e)
            yield create_assistant_message(f"Error: {str(e)}", is_error=True)
            return

        # Yield assistant message
        yield assistant_message

        # Extract tool use blocks
        tool_use_blocks = [block for block in assistant_message.content if isinstance(block, ToolUseBlock)]

        # If no tool use, we're done
        if not tool_use_blocks:
            return

        # Check for abort before tool execution
        if abort_event.is_set():
            yield create_assistant_message(INTERRUPT_MESSAGE)
            return

        # Execute tools
        tool_results: List[UserMessage] = []

        # Decide concurrent vs serial execution
        found_tools = [self._find_tool(tools, block.name) for block in tool_use_blocks]
        all_read_only = all(tool.is_read_only() for tool in found_tools if tool is not None)

        if all_read_only:
            # Concurrent execution for read-only tools
            async for message in self._run_tools_concurrently(
                tool_use_blocks,
                tools,
                assistant_message,
                ToolUseContext(
                    abort_event=abort_event, options=options.model_dump(), read_file_timestamps=read_file_timestamps
                ),
                options.dangerous_skip_permissions,
            ):
                yield message
                if isinstance(message, UserMessage):
                    tool_results.append(message)
        else:
            # Serial execution for write tools
            async for message in self._run_tools_serially(
                tool_use_blocks,
                tools,
                assistant_message,
                ToolUseContext(
                    abort_event=abort_event, options=options.model_dump(), read_file_timestamps=read_file_timestamps
                ),
                options.dangerous_skip_permissions,
            ):
                yield message
                if isinstance(message, UserMessage):
                    tool_results.append(message)

        # Check for abort after tool execution
        if abort_event.is_set():
            yield create_assistant_message(INTERRUPT_MESSAGE)
            return

        # Recursively continue conversation with tool results
        async for message in self.run(
            messages=[*messages, assistant_message, *tool_results],
            system_prompt=system_prompt,
            tools=tools,
            abort_event=abort_event,
            options=options,
            read_file_timestamps=read_file_timestamps,
        ):
            yield message

    async def _run_tools_concurrently(
        self,
        tool_use_blocks: List[ToolUseBlock],
        tools: List[Tool],
        assistant_message: AssistantMessage,
        context: ToolUseContext,
        skip_permissions: bool,
    ) -> AsyncGenerator[Message, None]:
        """Execute tools concurrently with semaphore."""
        semaphore = asyncio.Semaphore(self.concurrency)

        async def run_with_semaphore(block: ToolUseBlock):
            async with semaphore:
                results = []
                async for msg in self._run_tool_use(
                    block, set(b.id for b in tool_use_blocks), tools, assistant_message, context, skip_permissions
                ):
                    results.append(msg)
                return results

        # Gather all tool executions
        tasks = [run_with_semaphore(block) for block in tool_use_blocks]
        results = await asyncio.gather(*tasks)

        # Yield all messages
        for tool_results in results:
            for msg in tool_results:
                yield msg

    async def _run_tools_serially(
        self,
        tool_use_blocks: List[ToolUseBlock],
        tools: List[Tool],
        assistant_message: AssistantMessage,
        context: ToolUseContext,
        skip_permissions: bool,
    ) -> AsyncGenerator[Message, None]:
        """Execute tools serially."""
        for block in tool_use_blocks:
            async for msg in self._run_tool_use(
                block, set(b.id for b in tool_use_blocks), tools, assistant_message, context, skip_permissions
            ):
                yield msg

    async def _run_tool_use(
        self,
        tool_use: ToolUseBlock,
        sibling_ids: Set[str],
        tools: List[Tool],
        assistant_message: AssistantMessage,
        context: ToolUseContext,
        skip_permissions: bool,
    ) -> AsyncGenerator[Message, None]:
        """Execute a single tool use."""
        tool = self._find_tool(tools, tool_use.name)

        # Check if tool exists
        if tool is None:
            self.logger.event(
                "tool_use_error",
                {"error": f"No such tool: {tool_use.name}", "tool_name": tool_use.name, "tool_use_id": tool_use.id},
            )
            yield create_user_message(tool_use.id, f"Error: No such tool available: {tool_use.name}", is_error=True)
            return

        # Check for abort
        if context.abort_event.is_set():
            self.logger.event("tool_use_cancelled", {"tool_name": tool.name, "tool_use_id": tool_use.id})
            yield create_user_message(tool_use.id, "Cancelled", is_error=True)
            return

        # Execute with permission checks and validation
        async for msg in self._check_permissions_and_call_tool(
            tool, tool_use.id, sibling_ids, tool_use.input, context, assistant_message, skip_permissions
        ):
            yield msg

    async def _check_permissions_and_call_tool(
        self,
        tool: Tool,
        tool_use_id: str,
        sibling_ids: Set[str],
        input_data: dict,
        context: ToolUseContext,
        assistant_message: AssistantMessage,
        skip_permissions: bool,
    ) -> AsyncGenerator[Message, None]:
        """Validate input, check permissions, and call tool."""

        # 1. Schema validation
        try:
            validated_input = tool.input_schema(**input_data)
        except Exception as e:
            self.logger.event(
                "tool_use_error",
                {"error": f"InputValidationError: {str(e)}", "tool_name": tool.name, "tool_use_id": tool_use_id},
            )
            yield create_user_message(tool_use_id, f"InputValidationError: {str(e)}", is_error=True)
            return

        # 2. Tool-specific validation
        validation = await tool.validate_input(validated_input, context)
        if not validation.result:
            error_msg = validation.message or "Validation failed"
            self.logger.event(
                "tool_use_error", {"error": error_msg, "tool_name": tool.name, "tool_use_id": tool_use_id}
            )
            yield create_user_message(tool_use_id, validation.message or "Validation failed", is_error=True)
            return

        # 3. Permission check
        if not skip_permissions and tool.needs_permissions(validated_input):
            permission = await self.permissions.check(tool, input_data, context, assistant_message)
            if not permission.result:
                yield create_user_message(tool_use_id, permission.message or "Permission denied", is_error=True)
                return

        # 4. Execute tool
        try:
            # tool.call returns AsyncGenerator[ToolResult, None]
            tool_generator = tool.call(validated_input, context, None)
            async for result in tool_generator:  # type: ignore[attr-defined]
                if result.type == "result":
                    self.logger.event("tool_use_success", {"tool_name": tool.name, "tool_use_id": tool_use_id})
                    yield create_user_message(
                        tool_use_id, result.result_for_assistant, is_error=False, data=result.data
                    )
                    return
                elif result.type == "progress":
                    self.logger.event("tool_use_progress", {"tool_name": tool.name, "tool_use_id": tool_use_id})
                    yield create_progress_message(
                        tool_use_id, sibling_ids, result.content, result.normalized_messages, result.tools
                    )
        except Exception as e:
            self.logger.error(e)
            self.logger.event("tool_use_error", {"error": str(e), "tool_name": tool.name, "tool_use_id": tool_use_id})
            yield create_user_message(tool_use_id, f"Error: {str(e)}", is_error=True)

    def _format_system_prompt(self, parts: List[str]) -> List[str]:
        """Format system prompt parts."""
        return parts

    def _find_tool(self, tools: List[Tool], name: str) -> Tool | None:
        """Find tool by name."""
        for tool in tools:
            if tool.name == name:
                return tool
        return None

    def _tool_to_dict(self, tool: Tool) -> dict:
        """Convert tool to dict for API."""
        return {
            "name": tool.name,
            "description": tool.__doc__ or "",
            "input_schema": tool.input_schema.model_json_schema(),
        }
