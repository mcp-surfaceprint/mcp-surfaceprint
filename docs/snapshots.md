# Snapshot format and normalization

`mcp-surfaceprint` emits a **versioned snapshot JSON** via `--json` and `--save`.

At a high level:

- **`observation`**: timestamp, command, negotiated protocol version, inspection status/coverage, notes, and errors.
- **`surface`**: the declared tools + schemas, resources/templates, prompts/prompt arguments, and additional declaration sources.

Only `surface` is deterministically normalized and hashed.

## Surface digest (`surfaceDigest`)

If every supported, identity-bearing discovery section completes successfully, the snapshot includes a `surfaceDigest` (`sha256:...`).

If any identity-bearing section is incomplete, the snapshot is marked `surfaceCompleteness: "partial"` and **no digest is emitted**. This avoids claiming a comparable surface identity when inspection was incomplete.

The digest identifies the normalized declaration observed under a defined inspection model. It does not verify that the server’s declaration is truthful, exhaustive, safe, or representative of runtime behavior.

## Normalization rules (high level)

- Lists are sorted by identity keys (tool name, resource URI, template URI template, prompt name).
- In JSON Schemas, `enum` and `required` arrays are treated as sets (order-insensitive).
- In server manifests (`://mcp/manifest`), per-tool `operations` lists are treated as sets (order-insensitive).
- Schema combinators like `oneOf` / `anyOf` / `allOf` preserve order.

## What participates in identity?

Tool, resource, resource-template, and prompt descriptions participate in surface identity.

Preflight-generated heuristic annotations, timestamps, commands, notes, and errors do not.

## Legacy JSON inputs

`mcp-surfaceprint diff` accepts older, unversioned legacy report JSON. Legacy reports are treated as **partial**:

- Missing legacy evidence is not rendered as a proven capability change.
- Digest-based identity comparison is only available when both inputs are complete snapshots.

