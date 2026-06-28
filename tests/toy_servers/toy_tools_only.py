"""
Toy MCP server (stdio) that only exposes tools — no resources or prompts.

Uses the low-level Server API (not FastMCP) so that capabilities.resources
and capabilities.prompts are genuinely None.  This lets mcp-surfaceprint test
the "not supported by server" display path.
"""

from __future__ import annotations

import anyio
import mcp.server.stdio
from mcp.server import Server
from mcp.types import TextContent, Tool


server = Server("toy-tools-only")


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    return [
        Tool(name="greet", description="Say hello", inputSchema={"type": "object", "properties": {"name": {"type": "string"}}}),
        Tool(name="get_time", description="Get the current time", inputSchema={"type": "object", "properties": {}}),
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None = None) -> list[TextContent]:
    if name == "greet":
        return [TextContent(type="text", text=f"Hello, {(arguments or {}).get('name', 'world')}!")]
    return [TextContent(type="text", text="12:00")]


async def main() -> None:
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(main)
