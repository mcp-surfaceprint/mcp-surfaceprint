"""
Toy MCP server (stdio) used for mcp-surfaceprint integration tests.

This server always exposes a mix of tools/resources/prompts so the preflight
can validate enumeration and risk classification deterministically.
"""

from __future__ import annotations

import anyio

from mcp.server.fastmcp import FastMCP


mcp = FastMCP(name="toy-open", instructions="Toy server for mcp-surfaceprint tests.")


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


@mcp.tool(description="An oddly-named tool with no obvious verb")
def frobnicate() -> str:
    return "ok"


@mcp.resource("toy://items", description="All items")
def items() -> str:
    return "items"


# Resource template: in FastMCP, URIs with `{...}` become templates.
@mcp.resource("toy://items/{item_id}", description="Single item by id")
def item_by_id(item_id: str) -> str:
    return f"item:{item_id}"


@mcp.prompt(description="Analyze items for a project")
def analyze_items(project_name: str) -> str:
    return f"Analyze items for {project_name}"


def main() -> None:
    anyio.run(mcp.run_stdio_async)


if __name__ == "__main__":
    main()

