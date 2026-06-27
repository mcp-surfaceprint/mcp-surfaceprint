# mcp-preflight
[![Downloads](https://static.pepy.tech/badge/mcp-preflight)](https://pepy.tech/project/mcp-preflight)
[![PyPI version](https://img.shields.io/pypi/v/mcp-preflight.svg)](https://pypi.org/project/mcp-preflight/)

Inspect, fingerprint, and diff an MCP server’s declared capability surface.

An MCP server can gain tools, parameters, resources, prompts, or new actions beneath an existing tool name. `mcp-preflight` captures that client-visible surface as a deterministic snapshot, computes a stable digest when inspection is complete, and shows structural differences over time.

Use it as:

- an interface compatibility check for MCP server maintainers
- a capability-change review gate for teams consuming third-party MCP servers

If you want the deeper framing and experiments, see [You can’t prove an MCP server hasn’t changed](You%20can%E2%80%99t%20prove%20an%20MCP%20server%20hasn%E2%80%99t%20changed.md).

## Why

You review an MCP server before installing it. Later, a dependency upgrade adds a destructive action beneath an existing tool name. The package version changed, but nothing gives you a durable, structural record of the declared capability surface you previously reviewed.

`mcp-preflight` turns that declaration into a versioned artifact that can be committed, compared, and reviewed.

## Quick start (snapshot + check)

```bash
pipx install mcp-preflight

# Commit a baseline snapshot (one-time)
mcp-preflight --save mcp-surface.json "uv run server.py"
git add mcp-surface.json

# Later, locally or in CI: check the live server against the baseline
mcp-preflight check mcp-surface.json "uv run server.py"
```

A changed surface is not automatically unsafe; `check` turns it into an explicit review event rather than allowing it to pass unnoticed.

> **Safety:** This command starts the server locally. MCP discovery does not invoke its declared tools, but a server can execute arbitrary code while handling any request. Use `--isolate-home` to prevent it from using your normal `HOME` and XDG directories; this is not a sandbox.

## Example change

```text
Surface changed.

Tools:
  ~ manage_items
      inputSchema.properties.action.enum:
        + delete

Previous: sha256:...
Current:  sha256:...
```

Structured output:

```bash
mcp-preflight check --json mcp-surface.json "uv run server.py" > check.json
```

## What it captures and compares

- Tools, descriptions, and full input schemas
- Schema fields, required parameters, and enum values, including changes beneath unchanged tool names
- Resources and resource templates
- Prompts and prompt arguments
- Optional per-tool manifest operations for servers that multiplex actions behind one tool (see [docs/server-manifest.md](docs/server-manifest.md))

## Integrations

The snapshot, surface digest, and structured `check --json` output can be consumed by registries, governance systems, agent runtimes, and security gateways. These systems can anchor approval to a specific observed surface and trigger re-review when that surface changes.

`mcp-preflight` supplies the inspection artifact; the consuming system decides whether to allow, block, sandbox, or require approval.

## Common workflows

```bash
# Inspect (human-readable)
mcp-preflight "uv run server.py"
mcp-preflight "npx my-mcp-server"
mcp-preflight "python3 /path/to/server.py"

# Save a snapshot (JSON)
mcp-preflight --save snapshot.json "uv run server.py"

# Check against a baseline snapshot
mcp-preflight check mcp-surface.json "uv run server.py"

# Diff two saved snapshots
mcp-preflight diff before.json after.json

# JSON output
mcp-preflight --json "uv run server.py"
```

## CI workflow

`check` turns declared-surface changes into an explicit review step, with stable exit codes and optional structured JSON (`--json`).

1. Commit a baseline snapshot (one-time).
2. Run `mcp-preflight check ...` in CI.
3. If the surface changed, review the diff in the PR and intentionally update the baseline snapshot.

Exit codes:

- **0 — unchanged**: inspection was complete and the surface digests match
- **1 — changed**: inspection was complete and the surface digests differ
- **2 — inspection failed**: timeout, auth required, startup error, etc.
- **3 — incomplete inspection**: preflight could not establish a comparable surface digest
- **4 — invalid baseline**: missing/partial baseline, unsupported snapshot version, invalid JSON

Machine-readable output:

```bash
mcp-preflight check --json mcp-surface.json "uv run server.py" > check.json
echo "exit_code=$?"
```

## Snapshots and identity

Snapshots separate observation metadata from the declared surface. Only the normalized surface is hashed.

A digest is emitted only when every supported identity-bearing discovery section completes successfully. An incomplete inspection produces no digest, rather than claiming a comparable identity.

See [Snapshot format and normalization](docs/snapshots.md).

## Interactive inspection

The interactive inspect output is useful for first-time exploration, debugging, and manual review.

<details>
<summary>Example interactive inspection output</summary>

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
```

</details>

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
<summary>Optional heuristic annotations</summary>

Interactive inspection can add heuristic signals, including read/write/destructive annotations, based on tool names and descriptions. These are hints only: they are not enforced and do not participate in the surface digest.

Disable them with:

```bash
mcp-preflight --no-signals "uv run server.py"
```

</details>

## Non-goals

`mcp-preflight` does not provide sandboxing, policy enforcement, or runtime analysis. It describes the interface a server declares; it does not prove that declaration is truthful, exhaustive, or safe.

## Documentation

- Snapshots: see [docs/snapshots.md](docs/snapshots.md)
- Server manifests (optional): see [docs/server-manifest.md](docs/server-manifest.md)
- Design principles: see [PRINCIPLES.md](PRINCIPLES.md)
- Deeper framing/experiments: see [You can’t prove an MCP server hasn’t changed](You%20can%E2%80%99t%20prove%20an%20MCP%20server%20hasn%E2%80%99t%20changed.md)


## Project

- Bugs / feature requests: [GitHub Issues](https://github.com/jordanstarrk/mcp-preflight/issues)
- License: [LICENSE](LICENSE)
