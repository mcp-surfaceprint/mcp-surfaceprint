# mcp-preflight
[![Downloads](https://static.pepy.tech/badge/mcp-preflight)](https://pepy.tech/project/mcp-preflight)
[![PyPI version](https://img.shields.io/pypi/v/mcp-preflight.svg)](https://pypi.org/project/mcp-preflight/)

`ls -la` for MCP servers. Inspect what a server declares before giving it operational access.
`mcp-preflight` captures a server’s declared tools, schemas, resources, templates, prompts, and additional declared operations. It can save that surface as a deterministic snapshot, assign complete observations a stable SHA-256 identity, and show structural changes over time.

## TL;DR

- **Inspect**: show the client-visible MCP surface (tools, schemas, resources/templates, prompts).
- **Snapshot**: `--save` / `--json` emit a versioned snapshot JSON you can commit.
- **Fingerprint**: complete snapshots get a deterministic `surfaceDigest` (sha256 of the canonical surface).
- **Diff**: `mcp-preflight diff` reports structural capability changes (not just tool-count changes).
- **Evidence-aware comparisons**: legacy/partial inputs don’t support complete identity claims; limitations and evidence gaps are rendered explicitly.
- **Manifest support**: can read `{scheme}://mcp/manifest` to surface multiplexed per-tool operations.



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

### CI-friendly usage (snapshot + diff)

```bash
# Create and commit a baseline snapshot (one-time)
mcp-preflight --save mcp-surface.json "uv run server.py"
git add mcp-surface.json

# Later (e.g. after an upgrade): re-inspect and diff
mcp-preflight --save mcp-surface-current.json "uv run server.py" || true
mcp-preflight diff mcp-surface.json mcp-surface-current.json
```

Notes:

- `mcp-preflight` exits **nonzero** when inspection is partial/failed, but it can still save a snapshot; `|| true` lets a CI job continue to run `diff`.
- `mcp-preflight diff` currently prints a human diff and does not return “changed vs unchanged” via exit code.

### CI gate: `mcp-preflight check`

For pull-request gating, use `check` (a single command with stable exit codes):

```bash
# Create and commit a baseline snapshot (one-time)
mcp-preflight --save mcp-surface.json "uv run server.py"
git add mcp-surface.json

# In CI / pull requests
mcp-preflight check mcp-surface.json "uv run server.py"
```

Exit codes:

- **0**: unchanged (complete identity comparable; `surfaceDigest` matches)
- **1**: changed (complete identity comparable; `surfaceDigest` differs)
- **2**: inspection failed (timeout, auth required, startup error, etc.)
- **3**: inspection partial / identity incomparable
- **4**: invalid baseline (missing/partial snapshot, unsupported snapshot version, invalid JSON)

`check --json` prints a machine-readable result (suitable for CI bots and wrappers).

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

`--json` and `--save` emit a **versioned snapshot**. (Older `mcp-preflight` versions emitted an unversioned “report” JSON format; snapshots are the stable format going forward.)

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

### Exit codes

`mcp-preflight` is designed to be usable in CI. It returns a nonzero exit code when it cannot produce a complete, comparable surface identity.

#### `mcp-preflight` (inspect)

- **0**: inspection succeeded and `observation.status == "ok"` (a complete surface identity was emitted)
- **1**: inspection was partial or failed (`observation.status != "ok"`) but a snapshot may still be written via `--save` and/or printed via `--json`

Examples of non-`ok` statuses include: `partial`, `timeout`, `auth_gated`, `auth_required`, `startup_error`.

#### `mcp-preflight diff`

- **0**: diff completed successfully (regardless of whether changes were found)
- **2**: user-facing error (for example, invalid JSON or unsupported snapshot format/version)

`mcp-preflight diff` prints a human-readable diff. It does not currently signal “changed” vs “unchanged” via exit code; use the output text (or wait for `diff --json` / `check` workflow commands).

### Legacy JSON reports

`mcp-preflight diff` accepts older, unversioned legacy report JSON. Legacy reports are treated as **partial** and compared with explicit evidence/observability limitations:

- Missing legacy evidence (for example, tool schemas not captured by the legacy format) is not rendered as a proven capability change.
- Digest-based identity comparison is only available when both inputs are complete snapshots.

When legacy/partial inputs are involved, diffs may include:

- `Complete-surface identity comparison: unavailable`
- `Comparison limitations: ...`
- `Newly observable:` / `Newly unobservable:` (for fields that became observable due to improved snapshot evidence capture)

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
