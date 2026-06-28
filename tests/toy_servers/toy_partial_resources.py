"""
Toy MCP server (stdio) that intentionally times out on list_resources.

Used to deterministically test mcp-surfaceprint's "partial" status behavior:
- list_tools succeeds quickly
- list_resources sleeps longer than the client's timeout
"""

from __future__ import annotations

import anyio

from mcp.server.fastmcp import FastMCP


class SlowListResourcesMCP(FastMCP):
    async def list_resources(self):  # type: ignore[override]
        # Sleep long enough to exceed the test timeout, but still bounded.
        await anyio.sleep(2.0)
        return await super().list_resources()


mcp = SlowListResourcesMCP(name="toy-partial-resources", instructions="Toy server for partial status tests.")


@mcp.tool(description="Always present")
def ping() -> str:
    return "pong"


@mcp.resource("toy://ok", description="Would be listed if not timed out")
def ok() -> str:
    return "ok"


def main() -> None:
    anyio.run(mcp.run_stdio_async)


if __name__ == "__main__":
    main()

