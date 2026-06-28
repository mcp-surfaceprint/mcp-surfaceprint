# Exposing a Server Manifest (for mcp-surfaceprint)

Some MCP servers route many operations through a single tool (for example, an `invoice` tool that handles `list`, `get`, `create`, `send`, `mark_paid`).
To MCP introspection, this still looks like *one tool*.

If your server exposes a **manifest resource**, mcp-surfaceprint can surface and diff those hidden operations.

## What to do

Expose a **read-oriented MCP resource** at:

```
{your-scheme}://mcp/manifest
```

Examples:
- `acme://mcp/manifest`
- `myserver://mcp/manifest`

mcp-surfaceprint will automatically read this resource if present.

## What it should return

Return JSON describing the tools your server exposes and the operations each tool supports.

Minimal example:

```json
{
  "version": "1.0.0",
  "tools": {
    "invoice": {
      "operations": ["list", "get", "create", "send", "mark_paid"]
    },
    "task": {
      "operations": ["list", "get", "create", "update", "complete"]
    },
    "auth_login": {}
  }
}
```

Keys under `tools` must match your MCP tool names.

`operations` lists the action values your tool dispatches on.

Tools without `operations` are treated as single-purpose.

Additional fields are allowed and ignored unless explicitly supported.

## How to implement it

Register the resource like any other MCP resource, and generate the manifest dynamically from your existing tool registry when it’s read.

Because it’s generated from the same source as your tools:

- it stays in sync automatically
- there’s nothing extra to maintain

## Design principles

- **Read-oriented**: this is introspection, not execution (servers may still run arbitrary code to service any request)
- **Declared, not inferred**: the server reports what exists
- **Lens, not a judge**: no risk scoring or policy decisions
- **Optional**: servers without a manifest still work fine

## What this enables

With a manifest, mcp-surfaceprint can make capability changes explicit:

- `invoice`: 5 → 8 operations (added: `send`, `mark_paid`)
- `task`: added operation `assign`

Helping teams see what changed before they upgrade.
