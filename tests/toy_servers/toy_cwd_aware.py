"""
Toy MCP server (stdio) that changes exposed tools based on cwd.

Used to test mcp-surfaceprint's --cwd behavior.
"""

from __future__ import annotations

from pathlib import Path

import anyio

from mcp.server.fastmcp import FastMCP


CWD_NAME = Path.cwd().name

mcp = FastMCP(name="toy-cwd-aware", instructions="Toy server for --cwd tests.")


@mcp.tool(description="Always present")
def always() -> str:
    return "ok"


@mcp.tool(name=f"cwd_{CWD_NAME}", description="Tool name includes current working directory name")
def cwd_name() -> str:
    return CWD_NAME


def main() -> None:
    anyio.run(mcp.run_stdio_async)


if __name__ == "__main__":
    main()

