# mcp-preflight
[![Downloads](https://static.pepy.tech/badge/mcp-preflight)](https://pepy.tech/project/mcp-preflight)
[![PyPI version](https://img.shields.io/pypi/v/mcp-preflight.svg)](https://pypi.org/project/mcp-preflight/)

`ls -la` for MCP servers. Inspect what a server declares before giving it operational access.
`mcp-preflight` captures a server’s declared tools, schemas, resources, templates, prompts, and additional declared operations. It can save that surface as a deterministic snapshot, assign complete observations a stable SHA-256 identity, and show structural changes over time.



## Install

```bash
pipx install mcp-preflight
```

## Quick start

```bash
mcp-preflight "npx @modelcontextprotocol/server-filesystem /tmp"
```

## Example output

```text
my-server (MCP 2025-03-26)

  Caution: the server process runs locally without sandboxing.
  Use --isolate-home to prevent access to your real HOME directory.

  MCP Tools (client-visible):
    🟢 list_items     "List all items in the database"
    🟢 get_item       "Get a single item by ID"
    🟡 create_item    "Create a new item"
    🟡 update_item    "Update an existing item"
    🔴 delete_item    "Permanently delete an item"

  Resources:
    📄 my-server://items
    📄 my-server://items/{id}

  Additional declared operations (from server manifest, 12 across 3 tools):
    Not represented as separate entries in tools/list.
    These are server-declared actions multiplexed behind the tools above.
      ↳ items (8): list, get, create, update, delete, search, export, archive
      ↳ reports (3): daily, weekly, monthly
      ↳ auth_login (single action)

  Prompts:
    💬 analyze_items (project_name)

  Risk summary:
    write: 2
    destructive: 1
    read-only: 2
    (best-effort heuristic from tool names/descriptions; not enforced)
```

## Common workflows

```bash
# Run against your own server
mcp-preflight "uv run server.py"
mcp-preflight "npx my-mcp-server"
mcp-preflight "python3 /path/to/server.py"

# Save a snapshot (JSON)
mcp-preflight --save snapshot.json "uv run server.py"

# Diff two saved snapshots
mcp-preflight diff before.json after.json

# JSON output
mcp-preflight --json "uv run server.py"
```

## What changes can it detect?

Snapshots can reveal changes that do not alter a tool name, including:

- input fields added or removed
- enum actions added behind an existing tool
- required parameters changing
- descriptions changing
- resources, templates, prompts, or prompt arguments changing

## Notes

- Starts the server locally and performs MCP discovery without invoking the server’s declared tools.
- Lists the declared tools, descriptions, input schemas, resources, resource templates, prompts, and prompt arguments returned by the server.
- If a single tool supports multiple actions, publish a `{scheme}://mcp/manifest` resource so preflight can surface and diff them. See [server manifest docs](docs/server-manifest.md).

## Snapshot JSON format

`--json` and `--save` emit a **versioned snapshot**. Note: v0.2 replaces the previous report JSON format with this versioned snapshot format.

- **`observation`**: timestamp, command, negotiated protocol version, inspection status, coverage, notes, errors, and local heuristic annotations.
- **`surface`**: the server-declared tools, descriptions, the complete `inputSchema` returned by the server, resources, resource templates, prompts, prompt arguments, and additional declaration sources.

Only `surface` is deterministically normalized and hashed.

Normalization rules (high level):

- Lists are sorted by identity keys (tool name, resource URI, template URI template, prompt name).
- In JSON Schemas, `enum` and `required` arrays are treated as sets (order-insensitive).
- In server manifests (`://mcp/manifest`), per-tool `operations` lists are treated as sets (order-insensitive).
- Schema combinators like `oneOf` / `anyOf` / `allOf` preserve order.

If all identity-bearing sections are inspected successfully, the snapshot includes `surfaceDigest` (`sha256:...`).

If any identity-bearing section cannot be inspected, the snapshot is marked `surfaceCompleteness: "partial"` and no `surfaceDigest` is emitted.

Tool, resource, resource-template, and prompt descriptions participate in surface identity. Preflight-generated risk labels, signals, timestamps, commands, notes, and errors do not.

`protocolVersion` is preserved in `observation` but does not participate in `surfaceDigest`.

The digest identifies the normalized declaration observed when all identity-bearing inspection sections completed successfully. It does not verify that the server’s declaration is truthful, exhaustive, safe, or representative of runtime behavior.

<details>
<summary>Auth-gated servers / custom env</summary>

Some MCP servers only reveal tools/resources after authentication. `mcp-preflight` does not run login flows, so it may be unable to enumerate some or all of the declared surface until credentials are provided.

```bash
# Pass a token via env
export MCP_SERVER_TOKEN=...
mcp-preflight "npx -y my-mcp-server"

# Point HOME (and XDG_* dirs) somewhere else (useful for servers that read ~/.config, ~/.local, etc.)
mcp-preflight --home /tmp/mcp-preflight-home "npx -y my-mcp-server"

# Isolate HOME entirely to reduce side effects/pollution
mcp-preflight --isolate-home "npx -y my-mcp-server"
```

</details>

<details>
<summary>Risk classification heuristic</summary>

Based on tool names and descriptions (conservative by default):

- 🟢 **read-only**: `get`, `list`, `search`, `read`, `fetch`, `find`, `show`, `view`
- 🟡 **write**: `create`, `add`, `update`, `set`, `send`, `write`, `upload`
- 🔴 **destructive**: `delete`, `remove`, `destroy`, `drop`, `purge`, `clear`, `reset`
- Unknown → 🟡 (assume write until proven otherwise)

</details>

<details>
<summary>Signals (heuristic)</summary>

`mcp-preflight` can emit “signals” based on text matching (best-effort). These are hints, not guarantees, and may have false positives/negatives.

Disable with:

```bash
mcp-preflight --no-signals "uv run server.py"
```

</details>

## Non-goals

- No sandboxing
- No policy enforcement
- No runtime analysis

This tool inspects the declared interface presented by the server. It does not call tools (`call_tool`).

It may read declared resources (for example, a server manifest) via `read_resource`. From the client’s perspective that is a read-oriented operation, but **servers can execute arbitrary code on any request**, including resource reads. Preflight is visibility, not a safety guarantee.

## Principles
See [PRINCIPLES.md](PRINCIPLES.md).


## Project

- Bugs / feature requests: [GitHub Issues](https://github.com/jordanstarrk/mcp-preflight/issues)
