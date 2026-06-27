from __future__ import annotations

from mcp_preflight import _build_snapshot, _compute_surface_digest, diff_reports


def _complete_coverage() -> dict:
    return {
        "tools": {"declaredSupported": True, "attempted": True, "completed": True},
        "resources": {"declaredSupported": False, "attempted": False, "completed": False},
        "resourceTemplates": {"declaredSupported": False, "attempted": False, "completed": False},
        "prompts": {"declaredSupported": False, "attempted": False, "completed": False},
        "manifest": {"declaredSupported": None, "attempted": False, "completed": True},
    }


def test_surface_digest_ignores_tool_order_and_schema_property_order() -> None:
    surface_a = {
        "tools": [
            {
                "name": "a",
                "description": "x",
                "inputSchema": {"type": "object", "properties": {"b": {"type": "string"}, "a": {"type": "string"}}},
            },
            {"name": "b", "description": "y", "inputSchema": {"type": "object"}},
        ],
        "resources": [],
        "resourceTemplates": [],
        "prompts": [],
        "declarationSources": [],
    }
    surface_b = {
        "tools": [
            {"name": "b", "description": "y", "inputSchema": {"type": "object"}},
            {
                "name": "a",
                "description": "x",
                "inputSchema": {"properties": {"a": {"type": "string"}, "b": {"type": "string"}}, "type": "object"},
            },
        ],
        "resources": [],
        "resourceTemplates": [],
        "prompts": [],
        "declarationSources": [],
    }
    assert _compute_surface_digest(surface_a) == _compute_surface_digest(surface_b)


def test_surface_digest_excludes_protocol_version_and_timestamps() -> None:
    surface = {
        "tools": [{"name": "t", "description": "d", "inputSchema": {"type": "object"}}],
        "resources": [],
        "resourceTemplates": [],
        "prompts": [],
        "declarationSources": [],
    }
    s1 = _build_snapshot(
        generated_at="2026-01-01T00:00:00Z",
        scanned_command=["x"],
        server_name="s",
        protocol_version="2025-03-26",
        capabilities={"tools": True, "resources": False, "prompts": False},
        status="ok",
        coverage=_complete_coverage(),
        surface=surface,
        tools_for_text=[],
        risk={"read": 0, "write": 0, "destructive": 0},
        signals=[],
        notes=[],
        errors=[],
    )
    s2 = _build_snapshot(
        generated_at="2027-01-01T00:00:00Z",
        scanned_command=["y"],
        server_name="s",
        protocol_version="2026-12-01",
        capabilities={"tools": True, "resources": False, "prompts": False},
        status="ok",
        coverage=_complete_coverage(),
        surface=surface,
        tools_for_text=[],
        risk={"read": 99, "write": 99, "destructive": 99},
        signals=[{"kind": "tool", "name": "t", "rule": "x"}],
        notes=[{"kind": "mcp", "name": "list_tools", "rule": "note", "snippet": "x"}],
        errors=[],
    )
    assert s1["surfaceDigest"] == s2["surfaceDigest"]


def test_description_change_changes_digest_and_diff_mentions_description() -> None:
    before = {
        "snapshotFormatVersion": "1",
        "surfaceCompleteness": "complete",
        "surface": {
            "tools": [{"name": "t", "description": "Search messages", "inputSchema": {"type": "object"}}],
            "resources": [],
            "resourceTemplates": [],
            "prompts": [],
            "declarationSources": [],
        },
        "surfaceDigest": "sha256:" + "a" * 64,
        "surfaceEntityDigests": {"tools": {}, "prompts": {}, "resources": {}, "resourceTemplates": {}},
        "observation": {
            "generatedAt": "x",
            "protocolVersion": "x",
            "serverName": "s",
            "command": [],
            "status": "ok",
            "capabilities": {"tools": True, "resources": False, "prompts": False},
            "coverage": {},
            "notes": [],
            "errors": [],
            "localAnnotations": {"tools": [], "risk": {}, "signals": []},
        },
    }
    after = {
        **before,
        "surface": {
            **before["surface"],
            "tools": [{"name": "t", "description": "Search messages and permanently delete matching messages", "inputSchema": {"type": "object"}}],
        },
        "surfaceDigest": "sha256:" + "b" * 64,
    }

    # Digest function should differ even if the placeholders above don't match real hashes.
    assert _compute_surface_digest(before["surface"]) != _compute_surface_digest(after["surface"])
    diff = diff_reports(before, after)
    assert "~ t.description" in diff or "~ t.description:" in diff


def test_schema_enum_expansion_changes_digest_and_diff_mentions_input_schema() -> None:
    before_surface = {
        "tools": [
            {
                "name": "task",
                "description": "Task",
                "inputSchema": {"type": "object", "properties": {"action": {"enum": ["list", "get"]}}},
            }
        ],
        "resources": [],
        "resourceTemplates": [],
        "prompts": [],
        "declarationSources": [],
    }
    after_surface = {
        "tools": [
            {
                "name": "task",
                "description": "Task",
                "inputSchema": {"type": "object", "properties": {"action": {"enum": ["get", "list", "delete"]}}},
            }
        ],
        "resources": [],
        "resourceTemplates": [],
        "prompts": [],
        "declarationSources": [],
    }
    assert _compute_surface_digest(before_surface) != _compute_surface_digest(after_surface)

    before = _build_snapshot(
        generated_at="x",
        scanned_command=[],
        server_name="s",
        protocol_version="x",
        capabilities={"tools": True, "resources": False, "prompts": False},
        status="ok",
        coverage=_complete_coverage(),
        surface=before_surface,
        tools_for_text=[],
        risk={"read": 0, "write": 0, "destructive": 0},
        signals=[],
        notes=[],
        errors=[],
    )
    after = _build_snapshot(
        generated_at="y",
        scanned_command=[],
        server_name="s",
        protocol_version="x",
        capabilities={"tools": True, "resources": False, "prompts": False},
        status="ok",
        coverage=_complete_coverage(),
        surface=after_surface,
        tools_for_text=[],
        risk={"read": 0, "write": 0, "destructive": 0},
        signals=[],
        notes=[],
        errors=[],
    )
    diff = diff_reports(before, after)
    assert "~ task.inputSchema" in diff

