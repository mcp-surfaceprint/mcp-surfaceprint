from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from conftest import TOY_DIR


def test_cli_save_writes_json_report() -> None:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "report.json"
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "mcp_preflight",
                "--json",
                "--save",
                str(out),
                sys.executable,
                str(TOY_DIR / "toy_open.py"),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        assert proc.stdout.strip()
        assert out.exists()
        snap = json.loads(out.read_text(encoding="utf-8"))
        assert snap["observation"]["serverName"] == "toy-open"


def test_cli_no_signals_disables_signal_output_in_json() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "mcp_preflight",
            "--json",
            "--no-signals",
            sys.executable,
            str(TOY_DIR / "toy_open.py"),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    snap = json.loads(proc.stdout)
    assert snap["observation"]["localAnnotations"]["signals"] == []


def test_cli_env_requires_key_value() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "mcp_preflight", "--env", "NOT_KEY_VALUE", sys.executable, str(TOY_DIR / "toy_open.py")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.returncode != 0
    assert "--env must be KEY=VALUE" in (proc.stderr + proc.stdout)


def test_cli_diff_subcommand_prints_diff() -> None:
    before = {
        "snapshotFormatVersion": "1",
        "surfaceCompleteness": "complete",
        "surface": {"tools": [], "resources": [], "resourceTemplates": [], "prompts": [], "declarationSources": []},
        "surfaceDigest": "sha256:" + "0" * 64,
        "surfaceEntityDigests": {"tools": {}, "prompts": {}, "resources": {}, "resourceTemplates": {}},
        "observation": {
            "generatedAt": "2026-01-01T00:00:00Z",
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
        "snapshotFormatVersion": "1",
        "surfaceCompleteness": "complete",
        "surface": {"tools": [{"name": "t", "description": "", "inputSchema": {"type": "object"}}], "resources": [], "resourceTemplates": [], "prompts": [], "declarationSources": []},
        "surfaceDigest": "sha256:" + "1" * 64,
        "surfaceEntityDigests": {"tools": {"t": "sha256:" + "2" * 64}, "prompts": {}, "resources": {}, "resourceTemplates": {}},
        "observation": {
            "generatedAt": "2026-01-01T00:00:00Z",
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

    with tempfile.TemporaryDirectory() as td:
        b = Path(td) / "before.json"
        a = Path(td) / "after.json"
        b.write_text(json.dumps(before), encoding="utf-8")
        a.write_text(json.dumps(after), encoding="utf-8")

        proc = subprocess.run(
            [sys.executable, "-m", "mcp_preflight", "diff", str(b), str(a)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        assert "Diff" in proc.stdout
        assert "+ t" in proc.stdout


def test_cli_version_flag_prints_version() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "mcp_preflight", "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    assert proc.stdout.strip().startswith("mcp-preflight ")


def test_cli_diff_rejects_unsupported_snapshot_version_without_traceback() -> None:
    before = {
        "snapshotFormatVersion": "999",
        "surfaceCompleteness": "complete",
        "surface": {"tools": [], "resources": [], "resourceTemplates": [], "prompts": [], "declarationSources": []},
        "surfaceDigest": "sha256:" + "0" * 64,
        "surfaceEntityDigests": {"tools": {}, "prompts": {}, "resources": {}, "resourceTemplates": {}},
        "observation": {
            "generatedAt": "2026-01-01T00:00:00Z",
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
        "snapshotFormatVersion": "1",
        "surfaceCompleteness": "complete",
        "surface": {"tools": [], "resources": [], "resourceTemplates": [], "prompts": [], "declarationSources": []},
        "surfaceDigest": "sha256:" + "0" * 64,
        "surfaceEntityDigests": {"tools": {}, "prompts": {}, "resources": {}, "resourceTemplates": {}},
        "observation": {
            "generatedAt": "2026-01-01T00:00:00Z",
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
    with tempfile.TemporaryDirectory() as td:
        b = Path(td) / "before.json"
        a = Path(td) / "after.json"
        b.write_text(json.dumps(before), encoding="utf-8")
        a.write_text(json.dumps(after), encoding="utf-8")

        proc = subprocess.run(
            [sys.executable, "-m", "mcp_preflight", "diff", str(b), str(a)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert proc.returncode != 0
        combined = proc.stdout + proc.stderr
        assert "Unsupported snapshotFormatVersion: 999" in combined
        assert "Traceback" not in combined


def test_cli_check_exit_codes_and_json_output() -> None:
    # Build a baseline snapshot by inspecting toy_open.
    proc = subprocess.run(
        [sys.executable, "-m", "mcp_preflight", "--json", sys.executable, str(TOY_DIR / "toy_open.py")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    baseline_snap = json.loads(proc.stdout)
    assert baseline_snap.get("surfaceDigest")

    with tempfile.TemporaryDirectory() as td:
        baseline = Path(td) / "baseline.json"
        baseline.write_text(json.dumps(baseline_snap), encoding="utf-8")

        # Unchanged: check against same server.
        proc2 = subprocess.run(
            [sys.executable, "-m", "mcp_preflight", "check", str(baseline), sys.executable, str(TOY_DIR / "toy_open.py")],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert proc2.returncode == 0
        assert "No changes detected." in proc2.stdout

        # Changed: check against a different server surface.
        proc3 = subprocess.run(
            [sys.executable, "-m", "mcp_preflight", "check", str(baseline), sys.executable, str(TOY_DIR / "toy_tools_only.py")],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert proc3.returncode == 1
        assert "Tools:" in proc3.stdout

        # Machine-readable output.
        proc4 = subprocess.run(
            [
                sys.executable,
                "-m",
                "mcp_preflight",
                "check",
                "--json",
                str(baseline),
                sys.executable,
                str(TOY_DIR / "toy_open.py"),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert proc4.returncode == 0
        result = json.loads(proc4.stdout)
        assert result["identityComparable"] is True
        assert result["changed"] is False
        assert result["exitCode"] == 0
        assert isinstance(result.get("changes"), list)

        # Partial/incomparable: should be 3, never 1.
        proc5 = subprocess.run(
            [
                sys.executable,
                "-m",
                "mcp_preflight",
                "check",
                "--timeout",
                "1.0",
                str(baseline),
                sys.executable,
                str(TOY_DIR / "toy_partial_resources.py"),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert proc5.returncode == 3


def test_cli_check_rejects_invalid_baseline() -> None:
    with tempfile.TemporaryDirectory() as td:
        baseline = Path(td) / "baseline.json"
        baseline.write_text(json.dumps({"snapshotFormatVersion": "999"}), encoding="utf-8")

        proc = subprocess.run(
            [sys.executable, "-m", "mcp_preflight", "check", str(baseline), sys.executable, str(TOY_DIR / "toy_open.py")],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert proc.returncode == 4
        assert "Unsupported snapshotFormatVersion: 999" in (proc.stdout + proc.stderr)

