import asyncio

from fastmcp import Client


class ConcurrentMcpClient(Client):
    async def call_tool_concurrent(self, name: str, arguments: dict):
        # Internally async, wrapped with Task here
        return await self.call_tool(name, arguments)


async def main():
    client = ConcurrentMcpClient("ws://localhost:3000/mcp")

    await client.connect()

    # Prepare three tool calls concurrently
    tasks = [
        asyncio.create_task(client.call_tool_concurrent("nmap_scan", {"target": "1.1.1.1"})),
        asyncio.create_task(client.call_tool_concurrent("gobuster_scan", {"domain": "example.com"})),
        asyncio.create_task(client.call_tool_concurrent("subfinder_scan", {"domain": "example.com"})),
    ]

    # Wait for all results
    results = await asyncio.gather(*tasks)

    for idx, r in enumerate(results):
        print(f"Result {idx + 1}:", r)

    await client.close()


asyncio.run(main())
