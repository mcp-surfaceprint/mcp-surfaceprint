"""
Toy MCP server (stdio) that intentionally times out on list_prompts.

Used to deterministically test mcp-preflight's distinction between:
- prompts unsupported (toy_tools_only.py) -> complete surface + digest
- prompts supported but list_prompts fails -> partial surface + no digest
"""

from __future__ import annotations

import anyio

from mcp.server.fastmcp import FastMCP


class SlowListPromptsMCP(FastMCP):
    async def list_prompts(self):  # type: ignore[override]
        # Sleep long enough to exceed the test timeout, but still bounded.
        await anyio.sleep(5.0)
        return await super().list_prompts()


mcp = SlowListPromptsMCP(name="toy-partial-prompts", instructions="Toy server for partial prompts status tests.")


@mcp.tool(description="Always present")
def ping() -> str:
    return "pong"


@mcp.prompt(description="Analyze a project")
def analyze(project: str) -> str:
    return f"Analyze {project}"


def main() -> None:
    anyio.run(mcp.run_stdio_async)


if __name__ == "__main__":
    main()

