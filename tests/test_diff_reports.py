from __future__ import annotations

import json
from pathlib import Path

from mcp_surfaceprint import _compute_snapshot_comparison, diff_reports


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


def _legacy_report(
    *,
    server_name: str = "toy-open",
    protocol_version: str = "2025-11-25",
    tools: list[dict] | None = None,
    resources: list[str] | None = None,
    templates: list[str] | None = None,
    prompts: list[dict] | None = None,
) -> dict:
    return {
        "generatedAt": "2026-01-01T00:00:00Z",
        "scannedCommand": ["python", "tests/toy_servers/toy_open.py"],
        "server": {"name": server_name, "protocolVersion": protocol_version},
        "capabilities": {"tools": True, "resources": True, "prompts": True},
        "status": "ok",
        "tools": tools or [],
        "resources": resources or [],
        "resourceTemplates": templates or [],
        "prompts": prompts or [],
        "risk": {"read": 0, "write": 0, "destructive": 0},
        "signals": [],
        "notes": [],
        "errors": [],
    }


def test_legacy_schema_gap_is_rendered_as_evidence_change_not_null_to_schema() -> None:
    legacy = _legacy_report(
        tools=[
            {"name": "t1", "description": "one"},
            {"name": "t2", "description": "two"},
        ],
        resources=["toy://items"],
        templates=["toy://items/{item_id}"],
        prompts=[{"name": "analyze_items", "description": "Analyze items", "arguments": ["project_name"]}],
    )
    current = _snapshot(
        server_name="toy-open",
        tools=[
            {"name": "t1", "description": "one", "inputSchema": {"type": "object", "properties": {"a": {"type": "string"}}}},
            {"name": "t2", "description": "two", "inputSchema": {"type": "object"}},
        ],
        resources=[{"uri": "toy://items"}],
        templates=[{"uriTemplate": "toy://items/{item_id}"}],
        prompts=[{"name": "analyze_items", "description": "Analyze items", "arguments": [{"name": "project_name"}]}],
        surface_digest="sha256:" + "a" * 64,
    )

    text = diff_reports(legacy, current)
    assert "WARNING: Legacy report:" in text
    assert "Complete-surface identity comparison: unavailable" in text
    assert "Comparison limitations:" in text
    assert "Newly observable:" in text
    assert "? t1.inputSchema" in text
    assert "? t2.inputSchema" in text
    assert "null ->" not in text
    assert "~ t1.inputSchema" not in text
    assert "~ t2.inputSchema" not in text
    assert "Resources:" not in text
    assert "Prompts:" not in text
    assert "No changes detected." not in text
    assert "No proven changes detected in comparable fields." in text
    # No redundant "identity unavailable" limitation.
    assert "Complete-surface identity comparison is unavailable" not in text
    # No outdated digest note wording.
    assert "surfaceDigest is omitted unless both surfaces are complete" not in text


def test_legacy_comparable_fields_still_diff_normally() -> None:
    legacy = _legacy_report(
        tools=[
            {"name": "t1", "description": "one"},
        ],
        resources=[],
        templates=[],
        prompts=[],
    )
    current = _snapshot(
        server_name="toy-open",
        tools=[
            {"name": "t1", "description": "ONE", "inputSchema": {"type": "object"}},
        ],
        resources=[],
        templates=[],
        prompts=[],
        surface_digest="sha256:" + "a" * 64,
    )

    text = diff_reports(legacy, current)
    assert "Tools:" in text
    assert "~ t1.description:" in text
    assert "~ t1.inputSchema" not in text
    assert "Newly observable:" in text


def test_compute_snapshot_comparison_emits_field_became_observable_for_legacy_schema_gap() -> None:
    before = _snapshot(
        tools=[
            {"name": "t1", "description": "one", "inputSchema": None},
            {"name": "t2", "description": "two", "inputSchema": None},
        ],
        resources=[],
        templates=[],
        prompts=[],
        surface_digest="sha256:" + "0" * 64,
    )
    before["surfaceCompleteness"] = "partial"
    before.pop("surfaceDigest", None)
    before_obs = before.get("observation")
    assert isinstance(before_obs, dict)
    before_obs["comparisonMetadata"] = {
        "legacy": True,
        "evidenceGaps": [{"type": "field_not_captured", "entityType": "tool", "path": "/inputSchema", "reason": "legacy_format_not_captured"}],
    }

    after = _snapshot(
        tools=[
            {"name": "t1", "description": "one", "inputSchema": {"type": "object"}},
            {"name": "t2", "description": "two", "inputSchema": {"type": "object"}},
        ],
        resources=[],
        templates=[],
        prompts=[],
        surface_digest="sha256:" + "a" * 64,
    )

    comp = _compute_snapshot_comparison(before, after)
    assert comp["identityComparable"] is False
    ev = comp["evidenceChanges"]
    assert any(e.get("type") == "field_became_observable" and e.get("entityId") == "t1" and e.get("path") == "/inputSchema" for e in ev)
    assert any(e.get("type") == "field_became_observable" and e.get("entityId") == "t2" and e.get("path") == "/inputSchema" for e in ev)


def test_generic_partial_resources_does_not_render_resource_add_remove() -> None:
    # Before: partial due to resources timeout (resources are unknown, not empty).
    before = _snapshot(
        tools=[{"name": "t1", "description": "one", "inputSchema": {"type": "object"}}],
        resources=[],
        templates=[],
        prompts=[],
        surface_digest="sha256:" + "0" * 64,
    )
    before["surfaceCompleteness"] = "partial"
    before.pop("surfaceDigest", None)
    before_obs = before["observation"]
    before_obs["coverage"] = {
        "tools": {"attempted": True, "completed": True, "declaredSupported": True, "itemCount": 1},
        "resources": {"attempted": True, "completed": False, "declaredSupported": True, "errorRule": "timeout"},
        "resourceTemplates": {"attempted": True, "completed": True, "declaredSupported": True, "itemCount": 0},
        "prompts": {"attempted": True, "completed": True, "declaredSupported": True, "itemCount": 0},
        "manifest": {"attempted": False, "completed": False, "declaredSupported": None},
    }

    after = _snapshot(
        tools=[{"name": "t1", "description": "one", "inputSchema": {"type": "object"}}],
        resources=[{"uri": "toy://items"}],
        templates=[{"uriTemplate": "toy://items/{id}"}],
        prompts=[],
        surface_digest="sha256:" + "a" * 64,
    )

    text = diff_reports(before, after)
    assert "Comparison limitations:" in text
    assert "did not complete resources inspection (timeout)" in text
    assert "Resources:" not in text
    assert "+ toy://items" not in text
    assert "- toy://items" not in text
    assert "Newly observable:" not in text


def test_legacy_resource_uri_addition_is_still_proven() -> None:
    legacy = _legacy_report(
        tools=[{"name": "t1", "description": "one"}],
        resources=["toy://a"],
        templates=[],
        prompts=[],
    )
    current = _snapshot(
        tools=[{"name": "t1", "description": "one", "inputSchema": {"type": "object"}}],
        resources=[{"uri": "toy://a", "description": "desc"}, {"uri": "toy://b", "description": "desc"}],
        templates=[],
        prompts=[],
        surface_digest="sha256:" + "a" * 64,
    )
    text = diff_reports(legacy, current)
    assert "Resources:" in text
    assert "+ toy://b" in text
    assert "~ toy://a" not in text


def test_legacy_prompt_argument_name_addition_is_still_proven_prompt_change() -> None:
    legacy = _legacy_report(
        tools=[],
        resources=[],
        templates=[],
        prompts=[{"name": "p", "description": "D", "arguments": ["a"]}],
    )
    current = _snapshot(
        tools=[],
        resources=[],
        templates=[],
        prompts=[
            {
                "name": "p",
                "description": "D",
                "arguments": [{"name": "a", "required": True}, {"name": "b", "required": True}],
            }
        ],
        surface_digest="sha256:" + "a" * 64,
    )
    text = diff_reports(legacy, current)
    assert "Prompts:" in text
    assert "~ p.arguments:" in text
    assert "added: b" in text


def test_prompt_description_change_renders_detail() -> None:
    before = _snapshot(
        tools=[],
        resources=[],
        templates=[],
        prompts=[{"name": "p", "description": "Analyze items", "arguments": [{"name": "project_name"}]}],
        surface_digest="sha256:" + "a" * 64,
    )
    after = _snapshot(
        tools=[],
        resources=[],
        templates=[],
        prompts=[{"name": "p", "description": "Analyze items for a project", "arguments": [{"name": "project_name"}]}],
        surface_digest="sha256:" + "b" * 64,
    )
    text = diff_reports(before, after)
    assert "Prompts:" in text
    assert "~ p.description:" in text
    assert "\"Analyze items\" -> \"Analyze items for a project\"" in text


def test_prompt_argument_name_added_and_removed_renders_detail() -> None:
    before = _snapshot(
        tools=[],
        resources=[],
        templates=[],
        prompts=[{"name": "p", "description": "D", "arguments": [{"name": "project_name"}]}],
        surface_digest="sha256:" + "a" * 64,
    )
    after = _snapshot(
        tools=[],
        resources=[],
        templates=[],
        prompts=[{"name": "p", "description": "D", "arguments": [{"name": "language"}]}],
        surface_digest="sha256:" + "b" * 64,
    )
    text = diff_reports(before, after)
    assert "Prompts:" in text
    assert "~ p.arguments:" in text
    assert "added: language" in text
    assert "removed: project_name" in text


def test_snapshot_comparison_filters_only_prompt_argument_details_not_argument_names() -> None:
    # Before has legacy evidence gap for prompt arg details.
    before = _snapshot(
        tools=[],
        resources=[],
        templates=[],
        prompts=[{"name": "p", "description": "D", "arguments": [{"name": "a"}]}],
        surface_digest="sha256:" + "0" * 64,
    )
    before["surfaceCompleteness"] = "partial"
    before.pop("surfaceDigest", None)
    before["observation"]["comparisonMetadata"] = {
        "legacy": True,
        "evidenceGaps": [
            {
                "type": "fields_not_captured",
                "entityType": "prompt",
                "pathPattern": r"^/arguments/[^/]+/(description|required|schema)$",
                "reason": "legacy_format_argument_details_not_captured",
            }
        ],
    }

    after = _snapshot(
        tools=[],
        resources=[],
        templates=[],
        prompts=[
            {
                "name": "p",
                "description": "D",
                "arguments": [{"name": "a", "required": True}, {"name": "b", "required": True}],
            }
        ],
        surface_digest="sha256:" + "a" * 64,
    )

    comp = _compute_snapshot_comparison(before, after)
    paths = [c.get("path") for c in comp["changes"] if c.get("entityType") == "prompt"]
    # Arg-name addition should remain (value_added at /arguments/b).
    assert "/arguments/b" in paths
    # Nested details should be filtered (no /arguments/<arg>/required, etc.)
    assert not any(isinstance(p, str) and p.endswith("/required") for p in paths)

