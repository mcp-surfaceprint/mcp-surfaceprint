from __future__ import annotations

import json
from pathlib import Path

from mcp_preflight import diff_reports


def _snapshot(
    *,
    server_name: str = "s",
    tools: list[dict] | None = None,
    resources: list[object] | None = None,
    templates: list[object] | None = None,
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
            "resources": [
                (r if isinstance(r, dict) else {"uri": r})
                for r in (resources or [])
            ],
            "resourceTemplates": [
                (t if isinstance(t, dict) else {"uriTemplate": t})
                for t in (templates or [])
            ],
            "prompts": prompts or [],
            "declarationSources": decl_sources,
        },
    }


def _wrap_surface_as_snapshot(surface: dict, *, server_name: str = "s") -> dict:
    """Build a minimal complete snapshot object for diff_reports() tests."""
    return {
        "snapshotFormatVersion": "1",
        "surfaceCompleteness": "complete",
        "surface": surface,
        # Placeholder surfaceDigest; tests that care about equality/inequality should supply real values.
        "surfaceDigest": "sha256:" + "0" * 64,
        "surfaceEntityDigests": {"tools": {}, "prompts": {}, "resources": {}, "resourceTemplates": {}},
        "observation": {
            "generatedAt": "x",
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


def test_diff_reports_shows_resource_metadata_changes_as_tilde_lines() -> None:
    before = _snapshot(
        resources=[{"uri": "toy://r", "description": "desc"}],
        surface_digest="sha256:" + "a" * 64,
    )
    after = _snapshot(
        resources=[{"uri": "toy://r", "description": "desc2"}],
        surface_digest="sha256:" + "b" * 64,
    )
    diff = diff_reports(before, after)
    assert "Resources:" in diff
    assert "~ toy://r" in diff


def test_diff_reports_shows_template_metadata_changes_as_tilde_lines() -> None:
    before = _snapshot(
        templates=[{"uriTemplate": "toy://t/{id}", "mimeType": "text/plain"}],
        surface_digest="sha256:" + "a" * 64,
    )
    after = _snapshot(
        templates=[{"uriTemplate": "toy://t/{id}", "mimeType": "application/json"}],
        surface_digest="sha256:" + "b" * 64,
    )
    diff = diff_reports(before, after)
    assert "Resources:" in diff
    assert "~ toy://t/{id}" in diff


def test_diff_reports_never_claims_no_changes_when_digests_differ() -> None:
    """
    CLI-layer parity: if complete snapshots have different digests, the human diff must
    not say \"No changes detected.\".
    """
    fixtures = Path(__file__).resolve().parent / "fixtures" / "conformance"
    for path in sorted((fixtures / "changes").glob("*.json")):
        fx = json.loads(path.read_text(encoding="utf-8"))
        before_surface = fx["before"]
        after_surface = fx["after"]

        before = _wrap_surface_as_snapshot(before_surface)
        after = _wrap_surface_as_snapshot(after_surface)
        before["surfaceDigest"] = "sha256:" + "a" * 64
        after["surfaceDigest"] = "sha256:" + "b" * 64

        text = diff_reports(before, after)
        assert "No changes detected" not in text, f"false negative for fixture {path.name}"


def test_diff_reports_claims_no_changes_for_equivalence_fixtures() -> None:
    fixtures = Path(__file__).resolve().parent / "fixtures" / "conformance"
    for path in sorted((fixtures / "equivalence").glob("*.json")):
        fx = json.loads(path.read_text(encoding="utf-8"))
        a_surface = fx["a"]
        b_surface = fx["b"]

        before = _wrap_surface_as_snapshot(a_surface)
        after = _wrap_surface_as_snapshot(b_surface)
        before["surfaceDigest"] = "sha256:" + "a" * 64
        after["surfaceDigest"] = "sha256:" + "a" * 64

        text = diff_reports(before, after)
        assert "No changes detected." in text, f"expected no-changes for fixture {path.name}"


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

