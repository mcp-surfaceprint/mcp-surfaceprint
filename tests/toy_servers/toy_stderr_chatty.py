"""
Toy MCP server (stdio) that emits stderr output immediately.

Used to test mcp-surfaceprint's --quiet / --verbose stderr handling.
"""

from __future__ import annotations

import sys

import anyio

from mcp.server.fastmcp import FastMCP


sys.stderr.write("toy-stderr-chatty: hello stderr\n")
sys.stderr.flush()

mcp = FastMCP(name="toy-stderr-chatty", instructions="Toy server for stderr tests.")


@mcp.tool(description="Always present")
def ping() -> str:
    return "pong"


def main() -> None:
    anyio.run(mcp.run_stdio_async)


if __name__ == "__main__":
    main()

