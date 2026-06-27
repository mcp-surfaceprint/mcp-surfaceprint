"""Tests for the ://mcp/manifest resource reading and display feature."""

from __future__ import annotations

import json
import subprocess
import sys

from conftest import TOY_DIR, parse_preflight_json
from mcp_preflight import (
    _expand_tool_capabilities,
    _parse_capabilities_resource,
    print_tool_capabilities,
)


# ── _parse_capabilities_resource ─────────────────────────────


def test_parse_valid_capabilities_resource() -> None:
    raw = json.dumps({
        "version": "1.0.0",
        "tools": {
            "invoice": {
                "description": "Invoice management",
                "dispatch_key": "action",
                "operations": ["list", "get"],
            },
            "auth_login": {
                "description": "Start login",
            },
        },
    })
    result = _parse_capabilities_resource(raw)
    assert result is not None
    assert "tools" in result
    assert "invoice" in result["tools"]
    assert "auth_login" in result["tools"]


def test_parse_returns_none_for_invalid_json() -> None:
    assert _parse_capabilities_resource("not json") is None


def test_parse_returns_none_for_non_dict() -> None:
    assert _parse_capabilities_resource(json.dumps([1, 2, 3])) is None


def test_parse_returns_none_for_missing_tools_key() -> None:
    assert _parse_capabilities_resource(json.dumps({"version": "1.0"})) is None


def test_parse_returns_none_when_tools_is_not_dict() -> None:
    assert _parse_capabilities_resource(json.dumps({"tools": "string"})) is None


def test_parse_returns_none_when_tool_entry_is_not_dict() -> None:
    assert _parse_capabilities_resource(json.dumps({"tools": {"bad": "string"}})) is None


def test_parse_returns_none_for_none_input() -> None:
    assert _parse_capabilities_resource(None) is None  # type: ignore[arg-type]


def test_parse_accepts_empty_tools_dict() -> None:
    result = _parse_capabilities_resource(json.dumps({"tools": {}}))
    assert result is not None
    assert result["tools"] == {}


# ── _expand_tool_capabilities ────────────────────────────────


def test_expand_includes_operations_for_dispatched_tools() -> None:
    caps = {
        "tools": {
            "invoice": {
                "description": "Invoice management",
                "dispatch_key": "action",
                "operations": ["list", "get", "create"],
            },
        },
    }
    result = _expand_tool_capabilities(caps)
    assert len(result) == 1
    assert result[0]["tool"] == "invoice"
    assert result[0]["operations"] == ["list", "get", "create"]
    assert result[0]["description"] == "Invoice management"


def test_expand_omits_operations_for_single_purpose_tools() -> None:
    caps = {
        "tools": {
            "auth_login": {
                "description": "Start login",
            },
        },
    }
    result = _expand_tool_capabilities(caps)
    assert len(result) == 1
    assert result[0]["tool"] == "auth_login"
    assert "operations" not in result[0]


def test_expand_sorts_by_tool_name() -> None:
    caps = {
        "tools": {
            "zebra": {"description": "Z tool", "dispatch_key": "a", "operations": ["z"]},
            "alpha": {"description": "A tool", "dispatch_key": "a", "operations": ["a"]},
        },
    }
    result = _expand_tool_capabilities(caps)
    assert [e["tool"] for e in result] == ["alpha", "zebra"]


def test_expand_requires_dispatch_key_for_operations() -> None:
    """Tools with operations but no dispatch_key are treated as single-purpose."""
    caps = {
        "tools": {
            "tool_a": {
                "description": "Has ops but no dispatch_key",
                "operations": ["list", "get"],
            },
        },
    }
    result = _expand_tool_capabilities(caps)
    assert len(result) == 1
    assert "operations" not in result[0]


def test_expand_empty_tools_returns_empty_list() -> None:
    assert _expand_tool_capabilities({"tools": {}}) == []


def test_expand_dispatch_key_with_empty_operations_is_single_action() -> None:
    """dispatch_key present but operations: [] should not expand."""
    caps = {"tools": {"t": {"description": "x", "dispatch_key": "action", "operations": []}}}
    result = _expand_tool_capabilities(caps)
    assert "operations" not in result[0]


def test_expand_non_list_operations_is_single_action() -> None:
    """operations that isn't a list should not expand."""
    caps = {"tools": {"t": {"description": "x", "dispatch_key": "action", "operations": "list"}}}
    result = _expand_tool_capabilities(caps)
    assert "operations" not in result[0]


def test_expand_missing_description_still_creates_entry() -> None:
    caps = {"tools": {"bare": {}}}
    result = _expand_tool_capabilities(caps)
    assert len(result) == 1
    assert result[0]["tool"] == "bare"
    assert "description" not in result[0]


def test_expand_handles_report_dispatch_key() -> None:
    """Tools dispatched via 'report' instead of 'action' should still expand."""
    caps = {
        "tools": {
            "analytics": {
                "description": "Analytics dashboard",
                "dispatch_key": "report",
                "operations": ["pulse", "risks", "overview"],
            },
        },
    }
    result = _expand_tool_capabilities(caps)
    assert len(result) == 1
    assert result[0]["operations"] == ["pulse", "risks", "overview"]


# ── print_tool_capabilities ─────────────────────────────────


def test_print_tool_capabilities_shows_operations(capsys) -> None:
    tool_caps = [
        {"tool": "invoice", "description": "Invoice management", "operations": ["list", "get", "create"]},
        {"tool": "auth_login", "description": "Start login"},
    ]
    print_tool_capabilities(tool_caps)
    out = capsys.readouterr().out
    assert "Additional declared operations (from server manifest" in out
    assert "4 operations across 2 tools" in out
    assert "Not represented as separate entries in tools/list" in out
    assert "server-declared actions multiplexed behind the tools above" in out
    assert "invoice (3): list, get, create" in out
    assert "auth_login (single action)" in out


def test_print_tool_capabilities_empty_list_prints_nothing(capsys) -> None:
    print_tool_capabilities([])
    out = capsys.readouterr().out
    assert out == ""


def test_print_tool_capabilities_singular_wording(capsys) -> None:
    """Single tool with single action should use singular nouns."""
    print_tool_capabilities([{"tool": "auth_login"}])
    out = capsys.readouterr().out
    assert "1 operation across 1 tool" in out


def test_print_tool_capabilities_all_single_action(capsys) -> None:
    tool_caps = [{"tool": "auth_login"}, {"tool": "auth_logout"}, {"tool": "search"}]
    print_tool_capabilities(tool_caps)
    out = capsys.readouterr().out
    assert "3 operations across 3 tools" in out
    # Every line should say (single action)
    assert "(single action)" in out
    assert out.count("(single action)") == 3


def test_print_tool_capabilities_at_scale(capsys) -> None:
    """Validate output format with many tools and operations."""
    tool_caps = [
        {"tool": "task", "operations": ["my", "today", "get", "create", "update", "complete"]},
        {"tool": "sprint", "operations": ["list", "get", "create", "stats", "reports"]},
        {"tool": "invoice", "operations": ["list", "get", "create", "send", "mark_paid"]},
        {"tool": "analytics", "operations": ["pulse", "risks", "overview"]},
        {"tool": "auth_login"},
        {"tool": "auth_status"},
        {"tool": "search"},
    ]
    print_tool_capabilities(tool_caps)
    out = capsys.readouterr().out
    # 6 + 5 + 5 + 3 dispatched + 3 single-purpose = 22
    assert "22 operations across 7 tools" in out
    assert "Not represented as separate entries in tools/list" in out
    assert "task (6)" in out
    assert "↳ search" in out


# ── Integration: toy-capabilities server (GitScrum-scale) ────


def test_toy_capabilities_json_has_manifest_key() -> None:
    snap = parse_preflight_json([sys.executable, str(TOY_DIR / "toy_capabilities.py")])
    assert snap["observation"]["serverName"] == "toy-capabilities"
    assert snap["observation"]["status"] == "ok"
    sources = snap["surface"]["declarationSources"]
    assert any(s.get("name") == "mcp_manifest" for s in sources)


def test_toy_capabilities_has_29_tools_in_manifest() -> None:
    snap = parse_preflight_json([sys.executable, str(TOY_DIR / "toy_capabilities.py")])
    src = next(s for s in snap["surface"]["declarationSources"] if s.get("name") == "mcp_manifest")
    tc = src["extracted"]["toolCapabilities"]
    assert len(tc) == 29


def test_toy_capabilities_dispatch_tools_have_operations() -> None:
    snap = parse_preflight_json([sys.executable, str(TOY_DIR / "toy_capabilities.py")])
    src = next(s for s in snap["surface"]["declarationSources"] if s.get("name") == "mcp_manifest")
    tc = src["extracted"]["toolCapabilities"]

    by_name = {e["tool"]: e for e in tc}

    # task has 12 operations
    assert "operations" in by_name["task"]
    assert len(by_name["task"]["operations"]) == 12
    assert "my" in by_name["task"]["operations"]
    assert "move" in by_name["task"]["operations"]

    # sprint has 10 operations
    assert len(by_name["sprint"]["operations"]) == 10

    # invoice has 8 operations
    assert len(by_name["invoice"]["operations"]) == 8
    assert "mark_paid" in by_name["invoice"]["operations"]

    # project has 9 operations
    assert len(by_name["project"]["operations"]) == 9


def test_toy_capabilities_report_dispatch_tools_expand() -> None:
    """Tools using 'report' as dispatch_key should also expand."""
    snap = parse_preflight_json([sys.executable, str(TOY_DIR / "toy_capabilities.py")])
    src = next(s for s in snap["surface"]["declarationSources"] if s.get("name") == "mcp_manifest")
    by_name = {e["tool"]: e for e in src["extracted"]["toolCapabilities"]}

    assert "operations" in by_name["analytics"]
    assert len(by_name["analytics"]["operations"]) == 10
    assert "pulse" in by_name["analytics"]["operations"]

    assert "operations" in by_name["clientflow_dashboard"]
    assert len(by_name["clientflow_dashboard"]["operations"]) == 8


def test_toy_capabilities_single_purpose_tools_have_no_operations() -> None:
    snap = parse_preflight_json([sys.executable, str(TOY_DIR / "toy_capabilities.py")])
    src = next(s for s in snap["surface"]["declarationSources"] if s.get("name") == "mcp_manifest")
    by_name = {e["tool"]: e for e in src["extracted"]["toolCapabilities"]}

    for name in ("auth_login", "auth_complete", "auth_status", "auth_logout", "search"):
        assert "operations" not in by_name[name], f"{name} should not have operations"


def test_toy_capabilities_total_operation_count() -> None:
    """The manifest should reflect 150+ dispatched operations."""
    snap = parse_preflight_json([sys.executable, str(TOY_DIR / "toy_capabilities.py")])
    src = next(s for s in snap["surface"]["declarationSources"] if s.get("name") == "mcp_manifest")
    tc = src["extracted"]["toolCapabilities"]

    total_dispatched = sum(len(e["operations"]) for e in tc if "operations" in e)
    assert total_dispatched >= 150
    single_purpose = sum(1 for e in tc if "operations" not in e)
    assert single_purpose == 5


def test_toy_capabilities_text_output_shows_scale() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "mcp_preflight", sys.executable, str(TOY_DIR / "toy_capabilities.py")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    assert "Additional declared operations (from server manifest" in proc.stdout
    # Should show "156 operations across 29 tools" (151 dispatched + 5 single)
    assert "29 tools" in proc.stdout
    assert "156 operations" in proc.stdout
    # Spot-check a few entries
    assert "task (12)" in proc.stdout
    assert "invoice (8)" in proc.stdout
    assert "↳ auth_login (single action)" in proc.stdout


def test_toy_capabilities_list_tools_returns_29_tools() -> None:
    """The MCP server itself should register all 29 tools."""
    snap = parse_preflight_json([sys.executable, str(TOY_DIR / "toy_capabilities.py")])
    assert len(snap["surface"]["tools"]) == 29


def test_toy_open_has_no_manifest_key() -> None:
    """Servers without a ://mcp/manifest resource should not have the key."""
    snap = parse_preflight_json([sys.executable, str(TOY_DIR / "toy_open.py")])
    assert snap["surface"]["declarationSources"] == []
