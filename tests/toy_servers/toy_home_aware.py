"""
Toy MCP server (stdio) that changes exposed tools based on HOME.

Used to test mcp-surfaceprint's --home and --isolate-home wiring.
"""

from __future__ import annotations

import os
from pathlib import Path

import anyio

from mcp.server.fastmcp import FastMCP


HOME = Path(os.environ.get("HOME", "")).name

mcp = FastMCP(name="toy-home-aware", instructions="Toy server for HOME/XDG tests.")


@mcp.tool(description="No-op tool")
def noop() -> str:
    return "ok"


if HOME.startswith("mcp-surfaceprint-home-"):

    @mcp.tool(description="Present when --isolate-home is used")
    def home_isolated_flag() -> bool:
        return True

elif HOME.endswith("custom-home"):

    @mcp.tool(description="Present when --home .../custom-home is used")
    def home_custom_flag() -> bool:
        return True

else:

    @mcp.tool(description="Present when no HOME override is used")
    def home_default_flag() -> bool:
        return True


def main() -> None:
    anyio.run(mcp.run_stdio_async)


if __name__ == "__main__":
    main()

