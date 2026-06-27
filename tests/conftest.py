from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOY_DIR = ROOT / "tests" / "toy_servers"


def run_preflight_json(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run mcp-preflight with --json flag and return the CompletedProcess."""
    return subprocess.run(
        [sys.executable, "-m", "mcp_preflight", "--json", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=check,
    )


def parse_preflight_json(args: list[str]) -> dict:
    """Run mcp-preflight with --json, parse stdout, and return the snapshot dict."""
    proc = run_preflight_json(args)
    return json.loads(proc.stdout)
