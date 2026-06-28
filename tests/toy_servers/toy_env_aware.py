"""
Toy MCP server (stdio) that changes exposed tools based on environment variables.

Used to test mcp-surfaceprint's --env behavior (repeatable/override).
"""

from __future__ import annotations

import os

import anyio

from mcp.server.fastmcp import FastMCP


VAL = os.environ.get("TOY_ENV_VAL", "unset")

mcp = FastMCP(name="toy-env-aware", instructions="Toy server for --env tests.")


@mcp.tool(description="Always present")
def always() -> str:
    return "ok"


@mcp.tool(name=f"env_val_{VAL}", description="Tool name includes TOY_ENV_VAL")
def env_val() -> str:
    return VAL


def main() -> None:
    anyio.run(mcp.run_stdio_async)


if __name__ == "__main__":
    main()

