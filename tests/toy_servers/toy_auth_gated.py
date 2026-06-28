"""
Toy MCP server (stdio) that is "auth-gated" for mcp-surfaceprint integration tests.

Behavior:
- If TOY_TOKEN != "ok": emits an auth hint on stderr and exposes *no* capabilities.
- If TOY_TOKEN == "ok": exposes the same mixed capabilities as toy_open.

This matches how real servers often behave: they initialize, but list_* calls
return empty / error until credentials are present.
"""

from __future__ import annotations

import os
import sys

import anyio

from mcp.server.fastmcp import FastMCP


def _build_server() -> FastMCP:
    token = os.environ.get("TOY_TOKEN")

    if token != "ok":
        # mcp-surfaceprint infers auth gating from stderr hints + empty enumerations.
        sys.stderr.write("Authentication required: no auth token/credentials provided.\n")
        sys.stderr.flush()
        return FastMCP(name="toy-auth-gated", instructions="Toy auth-gated server for tests.")

    mcp = FastMCP(name="toy-auth-gated", instructions="Toy auth-gated server for tests.")

    @mcp.tool(description="List all items in the database")
    def list_items() -> list[str]:
        return ["a", "b"]

    @mcp.tool(description="Get a single item by ID")
    def get_item(item_id: str) -> dict:
        return {"id": item_id}

    @mcp.tool(description="Create a new item")
    def create_item(name: str) -> dict:
        return {"id": "new", "name": name}

    @mcp.tool(description="Permanently delete an item")
    def delete_item(item_id: str) -> bool:
        return True

    @mcp.resource("toy://items", description="All items")
    def items() -> str:
        return "items"

    @mcp.resource("toy://items/{item_id}", description="Single item by id")
    def item_by_id(item_id: str) -> str:
        return f"item:{item_id}"

    @mcp.prompt(description="Analyze items for a project")
    def analyze_items(project_name: str) -> str:
        return f"Analyze items for {project_name}"

    return mcp


def main() -> None:
    mcp = _build_server()
    anyio.run(mcp.run_stdio_async)


if __name__ == "__main__":
    main()

