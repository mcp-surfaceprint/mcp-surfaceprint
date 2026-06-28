"""
Toy MCP server exposing a malformed ://mcp/manifest resource.

Specifically: the manifest declares duplicate operation values for a dispatched tool.
This should cause mcp-surfaceprint to mark manifest inspection incomplete, mark the
surface partial, and suppress surfaceDigest emission.
"""

from __future__ import annotations

import json

import anyio
from mcp.server.fastmcp import FastMCP


mcp = FastMCP(name="toy-manifest-dupe-ops", instructions="Toy server with duplicate manifest operations.")


MANIFEST_PAYLOAD = {
    "version": "1.0.0",
    "tools": {
        "task": {
            "description": "Task management",
            "dispatch_key": "action",
            # Duplicate value is malformed.
            "operations": ["list", "get", "get"],
        }
    },
}


@mcp.resource("toy://mcp/manifest", description="Server capabilities manifest (malformed)")
def manifest() -> str:
    return json.dumps(MANIFEST_PAYLOAD)


@mcp.tool(description="Task management")
def task(action: str) -> str:
    return f"task:{action}"


def main() -> None:
    anyio.run(mcp.run_stdio_async)


if __name__ == "__main__":
    main()

