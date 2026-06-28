from __future__ import annotations

from mcp_surfaceprint import (
    _mark_partial,
    _print_introspection_coverage,
    print_notes,
    print_prompts,
    print_resources,
    print_risk_summary,
)


# ── _mark_partial ────────────────────────────────────────────


def test_mark_partial_escalates_ok_to_partial() -> None:
    assert _mark_partial("ok") == "partial"


def test_mark_partial_does_not_downgrade_partial() -> None:
    assert _mark_partial("partial") == "partial"


def test_mark_partial_does_not_downgrade_other_statuses() -> None:
    for status in ("auth_gated", "auth_required", "startup_error", "timeout"):
        assert _mark_partial(status) == status


# ── print_risk_summary ───────────────────────────────────────


def test_print_risk_summary_all_zero_prints_none(capsys) -> None:
    print_risk_summary({"read": 0, "write": 0, "destructive": 0})
    out = capsys.readouterr().out
    assert "Risk: None" in out


def test_print_risk_summary_mixed_counts(capsys) -> None:
    print_risk_summary({"read": 3, "write": 1, "destructive": 2})
    out = capsys.readouterr().out
    assert "Risk Summary:" in out
    assert "write: 1" in out
    assert "destructive: 2" in out
    assert "read-only: 3" in out
    assert "best-effort heuristic" in out


# ── print_notes ──────────────────────────────────────────────


def test_print_notes_shows_snippet(capsys) -> None:
    notes = [
        {"kind": "mcp", "name": "list_resources", "rule": "error", "snippet": "Method not found"},
    ]
    print_notes(notes)
    out = capsys.readouterr().out
    assert "list_resources (error)" in out
    assert "Method not found" in out


def test_print_notes_truncates_long_snippet(capsys) -> None:
    notes = [
        {"kind": "mcp", "name": "list_prompts", "rule": "error", "snippet": "x" * 200},
    ]
    print_notes(notes)
    out = capsys.readouterr().out
    assert "…" in out


def test_print_notes_empty_prints_nothing(capsys) -> None:
    print_notes([])
    out = capsys.readouterr().out
    assert out == ""


def test_print_notes_multiline_snippet_only_shows_first_line(capsys) -> None:
    notes = [
        {"kind": "server", "name": "stderr", "rule": "startup_stacktrace", "snippet": "TypeError: boom\n  at foo.js:1"},
    ]
    print_notes(notes)
    out = capsys.readouterr().out
    assert "TypeError: boom" in out
    assert "at foo.js:1" not in out


# ── print_resources ──────────────────────────────────────────


def test_print_resources_not_supported(capsys) -> None:
    print_resources([], [], supported=False)
    out = capsys.readouterr().out
    assert "not supported by server" in out


def test_print_resources_supported_but_errored(capsys) -> None:
    print_resources([], [], supported=True, had_error=True)
    out = capsys.readouterr().out
    assert "Resources: unknown" in out


def test_print_resources_supported_and_empty(capsys) -> None:
    print_resources([], [], supported=True, had_error=False)
    out = capsys.readouterr().out
    assert "Resources: none" in out


# ── print_prompts ────────────────────────────────────────────


def test_print_prompts_not_supported(capsys) -> None:
    print_prompts([], supported=False)
    out = capsys.readouterr().out
    assert "not supported by server" in out


def test_print_prompts_supported_but_errored(capsys) -> None:
    print_prompts([], supported=True, had_error=True)
    out = capsys.readouterr().out
    assert "Prompts: unknown" in out


def test_print_prompts_supported_and_empty(capsys) -> None:
    print_prompts([], supported=True, had_error=False)
    out = capsys.readouterr().out
    assert "Prompts: none" in out


# ── _print_introspection_coverage ────────────────────────────


def test_introspection_coverage_all_ok(capsys) -> None:
    snap = {
        "observation": {
            "coverage": {
                "tools": {"declaredSupported": True, "attempted": True, "completed": True},
                "resources": {"declaredSupported": True, "attempted": True, "completed": True},
                "resourceTemplates": {"declaredSupported": True, "attempted": True, "completed": True},
                "prompts": {"declaredSupported": True, "attempted": True, "completed": True},
                "manifest": {"declaredSupported": None, "attempted": False, "completed": True},
            }
        }
    }
    _print_introspection_coverage(snap)
    out = capsys.readouterr().out
    assert "Introspection coverage:" in out
    assert "✓ tools" in out
    assert "✓ resources" in out
    assert "✓ prompts" in out


def test_introspection_coverage_resources_timeout(capsys) -> None:
    snap = {
        "observation": {
            "coverage": {
                "tools": {"declaredSupported": True, "attempted": True, "completed": True},
                "resources": {"declaredSupported": True, "attempted": True, "completed": False, "errorRule": "timeout"},
                "resourceTemplates": {"declaredSupported": True, "attempted": True, "completed": True},
                "prompts": {"declaredSupported": True, "attempted": True, "completed": True},
                "manifest": {"declaredSupported": None, "attempted": False, "completed": False},
            }
        }
    }
    _print_introspection_coverage(snap)
    out = capsys.readouterr().out
    assert "✓ tools" in out
    assert "✗ resources (timeout)" in out
    assert "✓ prompts" in out


def test_introspection_coverage_tools_error(capsys) -> None:
    snap = {
        "observation": {
            "coverage": {
                "tools": {"declaredSupported": True, "attempted": True, "completed": False, "errorRule": "error"},
                "resources": {"declaredSupported": True, "attempted": True, "completed": True},
                "resourceTemplates": {"declaredSupported": True, "attempted": True, "completed": True},
                "prompts": {"declaredSupported": True, "attempted": True, "completed": True},
                "manifest": {"declaredSupported": None, "attempted": False, "completed": True},
            }
        }
    }
    _print_introspection_coverage(snap)
    out = capsys.readouterr().out
    assert "✗ tools (error)" in out
    assert "✓ resources" in out


def test_introspection_coverage_omits_undeclared_capabilities(capsys) -> None:
    """Resources/prompts not declared by server should not appear in coverage."""
    snap = {
        "observation": {
            "coverage": {
                "tools": {"declaredSupported": True, "attempted": True, "completed": True},
                "resources": {"declaredSupported": False, "attempted": False, "completed": False},
                "resourceTemplates": {"declaredSupported": False, "attempted": False, "completed": False},
                "prompts": {"declaredSupported": False, "attempted": False, "completed": False},
                "manifest": {"declaredSupported": None, "attempted": False, "completed": True},
            }
        }
    }
    _print_introspection_coverage(snap)
    out = capsys.readouterr().out
    assert "✓ tools" in out
    assert "resources" not in out
    assert "prompts" not in out


def test_introspection_coverage_prompts_timeout(capsys) -> None:
    snap = {
        "observation": {
            "coverage": {
                "tools": {"declaredSupported": True, "attempted": True, "completed": True},
                "resources": {"declaredSupported": False, "attempted": False, "completed": False},
                "resourceTemplates": {"declaredSupported": False, "attempted": False, "completed": False},
                "prompts": {"declaredSupported": True, "attempted": True, "completed": False, "errorRule": "timeout"},
                "manifest": {"declaredSupported": None, "attempted": False, "completed": True},
            }
        }
    }
    _print_introspection_coverage(snap)
    out = capsys.readouterr().out
    assert "✓ tools" in out
    assert "resources" not in out
    assert "✗ prompts (timeout)" in out
