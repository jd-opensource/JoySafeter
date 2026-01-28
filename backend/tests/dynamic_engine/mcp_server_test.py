"""
MCP Client Demo using official MCP SDK

Simple demonstration of using MCP client to connect to server and call tools.
"""

import asyncio
import json
import sys
from datetime import timedelta
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_path))

from mcp import ClientSession  # noqa: E402
from mcp.client.sse import sse_client  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402
from mcp.client.streamable_http import streamablehttp_client  # noqa: E402


async def demo_stdio():
    """Demo: Connect to MCP server via stdio."""
    print("\n=== Demo 1: STDIO Transport ===")

    # Create stdio client
    stdio_params = {
        "command": "python",
        "args": ["-m", "mcp.server"],  # Replace with your MCP server command
    }

    try:
        async with stdio_client(**stdio_params) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                # Initialize session
                await session.initialize()

                # List available tools
                tools = await session.list_tools()
                print(f"Available tools ({len(tools.tools)}):")
                for tool in tools.tools[:10]:
                    print(f"  - {tool.name}: {tool.description}")

                # Call a tool
                if tools.tools:
                    result = await session.call_tool(tools.tools[0].name, {})
                    print(f"\nTool result: {result}")

    except Exception as e:
        print(f"Error: {e}")


async def demo_sse(host: str = "http://localhost:8000/sse"):
    """Demo: Connect to MCP server via SSE."""
    print("\n=== Demo 2: SSE Transport ===")

    try:
        async with sse_client(host) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                # Initialize session
                await session.initialize()

                # List available tools
                tools = await session.list_tools()
                print(f"Available tools ({len(tools.tools)}):")
                for tool in tools.tools[:10]:
                    print(f"  - {tool.name}: {tool.description}")

                # Call a tool
                # result = await session.call_tool("list_all_tool_categories", {})
                # print(f"\nTool result: {result}")

                while True:
                    tool_name = input("Enter tool name: ")
                    input_json = input("Enter kwargs: ")
                    kwargs = {}
                    try:
                        kwargs = json.loads(input_json)
                    except Exception:
                        try:
                            kwargs = eval(input_json)
                        except Exception as e:
                            print(f"Error: {e}")
                            continue
                    result = await session.call_tool(tool_name, arguments=kwargs)
                    print(f"\nTool result: {result}")

    except Exception as e:
        print(f"Error: {e}")


async def demo_streamable_http():
    """Demo: Connect to MCP server via Streamable HTTP."""
    print("\n=== Demo 3: Streamable HTTP Transport ===")

    try:
        async with streamablehttp_client("http://localhost:8000/mcp") as streams:
            async with ClientSession(streams[0], streams[1], read_timeout_seconds=timedelta(seconds=30)) as session:
                # Initialize session
                await session.initialize()

                # List available tools
                tools = await session.list_tools()
                print(f"Available tools ({len(tools.tools)}):")
                for tool in tools.tools[:10]:
                    print(f"  - {tool.name}")

                # Call a tool
                result = await session.call_tool(
                    "execute_shell_command", {"command": "echo", "args": ["Hello from MCP!"]}
                )
                print(f"\nTool result: {result}")

    except Exception as e:
        print(f"Error: {e}")


async def demo_list_resources():
    """Demo: List resources from MCP server."""
    print("\n=== Demo 4: List Resources ===")

    try:
        async with streamablehttp_client("http://localhost:8000/mcp") as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()

                # List resources
                resources = await session.list_resources()
                print(f"Available resources ({len(resources.resources)}):")
                for resource in resources.resources[:5]:
                    print(f"  - {resource.uri}: {resource.name}")

    except Exception as e:
        print(f"Error: {e}")


async def demo_list_prompts():
    """Demo: List prompts from MCP server."""
    print("\n=== Demo 5: List Prompts ===")

    try:
        async with streamablehttp_client("http://localhost:8000/mcp") as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()

                # List prompts
                prompts = await session.list_prompts()
                print(f"Available prompts ({len(prompts.prompts)}):")
                for prompt in prompts.prompts[:5]:
                    print(f"  - {prompt.name}: {prompt.description}")

    except Exception as e:
        print(f"Error: {e}")


async def main():
    # Uncomment the demo you want to run:

    # Demo 1: STDIO (requires MCP server command)
    # await demo_stdio()

    # Demo 2: SSE (requires MCP server on localhost:8000)
    await demo_sse(host="http://localhost:9100/sse")

    # Demo 3: Streamable HTTP (requires MCP server)
    # await demo_streamable_http()

    # Demo 4: List resources
    # await demo_list_resources()

    # Demo 5: List prompts
    # await demo_list_prompts()


if __name__ == "__main__":
    asyncio.run(main())
