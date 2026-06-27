from __future__ import annotations

from mcp_preflight import diff_reports


def _snapshot(
    *,
    server_name: str = "s",
    tools: list[dict] | None = None,
    resources: list[str] | None = None,
    templates: list[str] | None = None,
    prompts: list[dict] | None = None,
    manifest_caps: list[dict] | None = None,
    surface_digest: str = "sha256:" + "0" * 64,
) -> dict:
    decl_sources: list[dict] = []
    if manifest_caps is not None:
        decl_sources.append(
            {
                "sourceType": "resource",
                "name": "mcp_manifest",
                "uri": f"{server_name}://mcp/manifest",
                "status": "parsed",
                "rawHash": "sha256:" + "f" * 64,
                "extracted": {"toolCapabilities": manifest_caps},
            }
        )
    return {
        "snapshotFormatVersion": "1",
        "surfaceCompleteness": "complete",
        "surfaceDigest": surface_digest,
        "surfaceEntityDigests": {"tools": {}, "prompts": {}, "resources": {}, "resourceTemplates": {}},
        "observation": {
            "generatedAt": "2026-01-01T00:00:00Z",
            "protocolVersion": "x",
            "serverName": server_name,
            "command": [],
            "status": "ok",
            "capabilities": {"tools": True, "resources": True, "prompts": True},
            "coverage": {},
            "notes": [],
            "errors": [],
            "localAnnotations": {"tools": [], "risk": {}, "signals": []},
        },
        "surface": {
            "tools": tools or [],
            "resources": [{"uri": u} for u in (resources or [])],
            "resourceTemplates": [{"uriTemplate": u} for u in (templates or [])],
            "prompts": prompts or [],
            "declarationSources": decl_sources,
        },
    }


def test_diff_reports_detects_added_removed_and_metadata_changes() -> None:
    before = _snapshot(
        tools=[
            {"name": "t1", "description": "one", "inputSchema": {"type": "object", "properties": {"a": {"type": "string"}}}},
            {"name": "t2", "description": "two", "inputSchema": {"type": "object"}},
        ],
        resources=["toy://a"],
        templates=["toy://t/{id}"],
        prompts=[{"name": "p1", "description": None, "arguments": []}],
        surface_digest="sha256:" + "a" * 64,
    )
    after = _snapshot(
        tools=[
            {"name": "t1", "description": "ONE", "inputSchema": {"type": "object", "properties": {"a": {"type": "string"}, "b": {"enum": ["x", "y"]}}}},
            {"name": "t3", "description": "three", "inputSchema": {"type": "object"}},
        ],
        resources=["toy://b"],
        templates=["toy://t/{id}", "toy://u/{id}"],
        prompts=[{"name": "p2", "description": None, "arguments": []}],
        surface_digest="sha256:" + "b" * 64,
    )

    diff = diff_reports(before, after)
    assert "surfaceDigest" in diff
    assert "Tools:" in diff
    assert "+ t3" in diff
    assert "- t2" in diff
    assert "~ t1.description" in diff or "~ t1.description:" in diff
    assert "~ t1.inputSchema" in diff
    assert "Resources:" in diff
    assert "+ toy://b" in diff
    assert "- toy://a" in diff
    assert "+ toy://u/{id}" in diff
    assert "Prompts:" in diff
    assert "+ p2" in diff
    assert "- p1" in diff


# ── Manifest / capabilities diffing ─────────────────────────


def test_diff_detects_added_manifest_tool() -> None:
    before = _snapshot(manifest_caps=[{"tool": "task", "operations": ["list", "get"]}])
    after = _snapshot(
        manifest_caps=[
            {"tool": "task", "operations": ["list", "get"]},
            {"tool": "budget", "operations": ["overview", "alerts", "burn_down"]},
        ]
    )
    diff = diff_reports(before, after)
    assert "Capabilities (manifest-declared):" in diff
    assert "+ budget (3 operations)" in diff


def test_diff_detects_removed_manifest_tool() -> None:
    before = _snapshot(
        manifest_caps=[
            {"tool": "task", "operations": ["list", "get"]},
            {"tool": "legacy", "operations": ["run"]},
        ]
    )
    after = _snapshot(manifest_caps=[{"tool": "task", "operations": ["list", "get"]}])
    diff = diff_reports(before, after)
    assert "Capabilities (manifest-declared):" in diff
    assert "- legacy (1 operations)" in diff


def test_diff_detects_changed_operations() -> None:
    before = _snapshot(manifest_caps=[{"tool": "invoice", "operations": ["list", "get", "create", "update", "stats"]}])
    after = _snapshot(
        manifest_caps=[
            {"tool": "invoice", "operations": ["list", "get", "create", "update", "stats", "issue", "send", "mark_paid"]}
        ]
    )
    diff = diff_reports(before, after)
    assert "Capabilities (manifest-declared):" in diff
    assert "~ invoice: 5 operations -> 8 operations" in diff
    assert "added: issue, mark_paid, send" in diff


def test_diff_detects_removed_operations() -> None:
    before = _snapshot(manifest_caps=[{"tool": "task", "operations": ["list", "get", "create", "delete"]}])
    after = _snapshot(manifest_caps=[{"tool": "task", "operations": ["list", "get", "create"]}])
    diff = diff_reports(before, after)
    assert "~ task: 4 operations -> 3 operations" in diff
    assert "removed: delete" in diff


def test_diff_no_manifest_in_either_report_shows_no_capabilities_section() -> None:
    before = _snapshot()
    after = _snapshot()
    diff = diff_reports(before, after)
    assert "Capabilities (manifest-declared):" not in diff
    assert "No changes detected." in diff


def test_diff_unchanged_manifest_shows_no_capabilities_section() -> None:
    manifest = [
        {"tool": "task", "operations": ["list", "get"]},
        {"tool": "auth_login"},
    ]
    before = _snapshot(manifest_caps=manifest)
    after = _snapshot(manifest_caps=manifest)
    diff = diff_reports(before, after)
    assert "Capabilities (manifest-declared):" not in diff

