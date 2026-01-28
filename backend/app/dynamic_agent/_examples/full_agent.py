"""
Complete agent example with multiple tools.

This example demonstrates:
1. Registering multiple tools
2. Running an agent with file operations
3. Using sub-agents for complex tasks
4. Handling tool permissions
"""

import asyncio
import logging
import os
from pathlib import Path

from app.dynamic_agent_core.logging import ConsoleLogger
from app.dynamic_agent_core.permissions import DefaultPermissionStrategy
from app.dynamic_agent_core.providers.anthropic import AnthropicProvider
from app.dynamic_agent_core.registry import ToolRegistry
from app.dynamic_agent_core.runtime import AgentRuntime
from app.dynamic_agent_core.types import AgentRuntimeOptions

logger = logging.getLogger(__name__)
from tools import (  # noqa: E402
    AgentTool,
    BashTool,
    EchoTool,
    FileEditTool,
    FileReadTool,
    FileWriteTool,
    GlobTool,
    GrepTool,
    ListTool,
    MemoryTool,
    NotebookTool,
    WebSearchTool,
)


async def main():
    """Run complete agent example."""

    # Get API key
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        print("Set it with: export ANTHROPIC_API_KEY='your-key'")
        return

    # Get working directory
    work_dir = Path.cwd()
    print(f"Working directory: {work_dir}")
    print("-" * 80)

    # Create provider and runtime
    provider = AnthropicProvider(api_key=api_key)
    logger = ConsoleLogger()
    permissions = DefaultPermissionStrategy()

    runtime = AgentRuntime(provider=provider, permissions=permissions, logger=logger, concurrency=10)

    # Register tools
    ToolRegistry.clear()  # Clear any existing tools
    ToolRegistry.register(EchoTool())
    ToolRegistry.register(FileReadTool(allowed_directories=[str(work_dir)]))
    ToolRegistry.register(FileWriteTool(allowed_directories=[str(work_dir)]))
    ToolRegistry.register(FileEditTool(allowed_directories=[str(work_dir)]))
    ToolRegistry.register(BashTool(allowed_directory=str(work_dir)))
    ToolRegistry.register(GrepTool(allowed_directories=[str(work_dir)]))
    ToolRegistry.register(GlobTool(allowed_directories=[str(work_dir)]))
    ToolRegistry.register(ListTool(allowed_directories=[str(work_dir)]))
    ToolRegistry.register(MemoryTool())
    ToolRegistry.register(WebSearchTool())
    ToolRegistry.register(NotebookTool(allowed_directories=[str(work_dir)]))
    ToolRegistry.register(AgentTool(runtime=runtime))

    print("Registered tools:")
    for tool in ToolRegistry.get_all_tools():
        read_only = "read-only" if tool.is_read_only() else "write"
        print(f"  - {tool.name} ({read_only})")
    print("-" * 80)

    # System prompt
    system_prompt = [
        "You are a helpful AI assistant with access to comprehensive file operations and tools.",
        "You can:",
        "- Read, write, and edit files",
        "- Search for text in files (Grep)",
        "- Find files by pattern (Glob)",
        "- List directory contents (List)",
        "- Store and retrieve persistent memory (Memory)",
        "- Search the web (WebSearch)",
        "- Read and analyze Jupyter notebooks (Notebook)",
        "- Execute bash commands (with restrictions)",
        "- Launch sub-agents for complex tasks",
        "",
        "When using tools:",
        "- Always provide clear explanations",
        "- Use Grep to search for text across files",
        "- Use Glob to find files by pattern",
        "- Use List to explore directory structures",
        "- Use Memory to store important information across conversations",
        "- Use WebSearch for current information",
        "- Use Notebook to analyze .ipynb files",
        "- Use sub-agents for exploratory or multi-step tasks",
        "- Be careful with write operations",
    ]

    # Example task
    task = """
    Please help me analyze this Python agent project:

    1. Read the README.md file in the python_agent directory
    2. List the main Python files in agent_core/
    3. Give me a summary of what this project does
    """

    print(f"\nTask: {task}")
    print("=" * 80)
    print()

    # Create abort event
    abort_event = asyncio.Event()

    # Run agent
    try:
        message_count = 0
        async for message in runtime.run(
            messages=[],
            system_prompt=system_prompt,
            tools=ToolRegistry.get_all_tools(),
            abort_event=abort_event,
            options=AgentRuntimeOptions(
                verbose=True,
                max_thinking_tokens=2000,
                dangerous_skip_permissions=True,  # For demo purposes
            ),
            read_file_timestamps={},
        ):
            message_count += 1

            # Print message
            if hasattr(message, "content"):
                print(f"\n[Message {message_count}]")
                print("-" * 80)

                for block in message.content:
                    if hasattr(block, "text"):
                        print(f"Text: {block.text[:500]}")
                        if len(block.text) > 500:
                            print("... (truncated)")
                    elif hasattr(block, "name"):
                        print(f"Tool Use: {block.name}")
                        print(f"  Input: {block.input}")
                    elif hasattr(block, "type") and block.type == "thinking":
                        print(f"Thinking: {block.text[:200]}...")

                # Print usage if available
                if hasattr(message, "usage"):
                    usage = message.usage
                    print(f"\nTokens: in={usage.input_tokens} out={usage.output_tokens}")
                    if message.cost_usd > 0:
                        print(f"Cost: ${message.cost_usd:.4f}")

                print("-" * 80)

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        abort_event.set()
    except Exception as e:
        logger.error(f"Error: {e}")
        logger.exception("Full agent error")

    print("\n" + "=" * 80)
    print("Agent finished!")
    print(f"Total messages: {message_count}")


if __name__ == "__main__":
    asyncio.run(main())
