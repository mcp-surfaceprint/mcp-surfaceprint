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

