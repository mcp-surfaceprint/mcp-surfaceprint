#!/usr/bin/env python3
"""
Run mcp-preflight against each toy server and display the results.

Usage:
  uv run python tests/show_outputs.py          # text output (default)
  uv run python tests/show_outputs.py --json   # JSON output
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOY_DIR = ROOT / "tests" / "toy_servers"

# Each entry: (label, server script, extra mcp-preflight args, extra env)
SCENARIOS: list[tuple[str, str, list[str], dict[str, str]]] = [
    (
        "Open server (tools + resources + prompts)",
        "toy_open.py",
        [],
        {},
    ),
    (
        "Tools-only server (no resources/prompts capability)",
        "toy_tools_only.py",
        [],
        {},
    ),
    (
        "Auth-gated server (no token → auth_gated)",
        "toy_auth_gated.py",
        [],
        {},
    ),
    (
        "Auth-gated server (with token → ok)",
        "toy_auth_gated.py",
        ["--env", "TOY_TOKEN=ok"],
        {},
    ),
    (
        "Auth crash server (startup failure)",
        "toy_auth_crash.py",
        [],
        {},
    ),
    (
        "Partial resources (list_resources times out)",
        "toy_partial_resources.py",
        ["--timeout", "1.2"],
        {},
    ),
    (
        "Stderr-chatty server (default — stderr suppressed)",
        "toy_stderr_chatty.py",
        [],
        {},
    ),
    (
        "Stderr-chatty server (--verbose — stderr shown)",
        "toy_stderr_chatty.py",
        ["--verbose"],
        {},
    ),
    (
        "CWD-aware server (default cwd)",
        "toy_cwd_aware.py",
        [],
        {},
    ),
    (
        "CWD-aware server (--cwd /tmp)",
        "toy_cwd_aware.py",
        ["--cwd", "/tmp"],
        {},
    ),
    (
        "Env-aware server (no TOY_ENV_VAL → unset)",
        "toy_env_aware.py",
        [],
        {},
    ),
    (
        "Env-aware server (--env TOY_ENV_VAL=hello)",
        "toy_env_aware.py",
        ["--env", "TOY_ENV_VAL=hello"],
        {},
    ),
    (
        "Home-aware server (default HOME)",
        "toy_home_aware.py",
        [],
        {},
    ),
    (
        "Home-aware server (--isolate-home)",
        "toy_home_aware.py",
        ["--isolate-home"],
        {},
    ),
    (
        "Capabilities overview (29 tools, 156 operations, manifest resource)",
        "toy_capabilities.py",
        [],
        {},
    ),
]


def _check_coverage() -> None:
    """Ensure every toy_*.py server has at least one scenario entry."""
    covered = {script for _, script, _, _ in SCENARIOS}
    all_toys = {p.name for p in TOY_DIR.glob("toy_*.py")}
    missing = sorted(all_toys - covered)
    if missing:
        print(f"ERROR: {len(missing)} toy server(s) not in SCENARIOS list:")
        for name in missing:
            print(f"  - {name}")
        print("Add a scenario entry for each, then re-run.")
        sys.exit(1)


def main() -> None:
    _check_coverage()

    use_json = "--json" in sys.argv[1:]
    extra_flags = ["--json"] if use_json else []
    separator = "─" * 72

    for label, script, args, env in SCENARIOS:
        server_path = str(TOY_DIR / script)
        cmd = [
            sys.executable, "-m", "mcp_preflight",
            *extra_flags,
            *args,
            sys.executable, server_path,
        ]

        print(f"\n{separator}")
        print(f"  {label}")
        print(f"  cmd: mcp-preflight {' '.join(extra_flags + args)} python {script}")
        print(separator)

        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**dict(__import__("os").environ), **env} if env else None,
        )

        has_stdout = bool(result.stdout.strip())
        has_stderr = bool(result.stderr.strip())

        if has_stdout:
            # Primary output — show as-is.
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")

        if has_stderr and has_stdout:
            # Stderr alongside normal output — label it so it's distinguishable.
            for line in result.stderr.strip().splitlines():
                print(f"  [stderr] {line}")
            print()
        elif has_stderr:
            # Stderr is the *only* output (e.g. crash) — show it directly, no prefix.
            for line in result.stderr.strip().splitlines():
                print(f"  {line}")
            print()

        if result.returncode != 0:
            print(f"  exit code {result.returncode}\n")

    print(separator)
    print(f"  {len(SCENARIOS)} server scenarios complete.")
    print(separator)

    # ── Diff scenarios (in-memory, no server needed) ─────────
    _run_diff_scenarios(separator)


# Each entry: (label, before_report, after_report)
DIFF_SCENARIOS: list[tuple[str, dict, dict]] = [
    (
        "Tool added + removed + risk changed",
        {
            "server": {"name": "acme-server"},
            "risk": {"write": 1, "destructive": 0, "read": 1},
            "tools": [
                {"name": "get_users", "risk": "read"},
                {"name": "create_user", "risk": "write"},
                {"name": "legacy_export", "risk": "write"},
            ],
            "resources": ["acme://items"],
            "resourceTemplates": [],
            "prompts": [{"name": "summarize"}],
        },
        {
            "server": {"name": "acme-server"},
            "risk": {"write": 1, "destructive": 1, "read": 1},
            "tools": [
                {"name": "get_users", "risk": "read"},
                {"name": "create_user", "risk": "destructive"},
                {"name": "delete_user", "risk": "destructive"},
            ],
            "resources": ["acme://items", "acme://mcp/manifest"],
            "resourceTemplates": [],
            "prompts": [{"name": "summarize"}, {"name": "audit_log"}],
        },
    ),
    (
        "Manifest: operations expanded (invoice 5 → 8, budget added)",
        {
            "server": {"name": "acme"},
            "risk": {"write": 5, "destructive": 0, "read": 2},
            "tools": [{"name": "invoice", "risk": "write"}, {"name": "task", "risk": "write"}],
            "resources": ["acme://mcp/manifest"],
            "resourceTemplates": [],
            "prompts": [],
            "manifest": [
                {"tool": "invoice", "operations": ["list", "get", "create", "update", "stats"]},
                {"tool": "task", "operations": ["list", "get", "create"]},
                {"tool": "auth_login"},
            ],
        },
        {
            "server": {"name": "acme"},
            "risk": {"write": 6, "destructive": 0, "read": 2},
            "tools": [
                {"name": "invoice", "risk": "write"},
                {"name": "task", "risk": "write"},
                {"name": "budget", "risk": "write"},
            ],
            "resources": ["acme://mcp/manifest"],
            "resourceTemplates": [],
            "prompts": [],
            "manifest": [
                {"tool": "invoice", "operations": ["list", "get", "create", "update", "stats", "issue", "send", "mark_paid"]},
                {"tool": "task", "operations": ["list", "get", "create"]},
                {"tool": "budget", "operations": ["overview", "alerts", "burn_down", "consumption"]},
                {"tool": "auth_login"},
            ],
        },
    ),
    (
        "Server adds manifest for the first time",
        {
            "server": {"name": "myserver"},
            "risk": {"write": 2, "destructive": 0, "read": 1},
            "tools": [
                {"name": "task", "risk": "write"},
                {"name": "search", "risk": "read"},
            ],
            "resources": [],
            "resourceTemplates": [],
            "prompts": [],
        },
        {
            "server": {"name": "myserver"},
            "risk": {"write": 2, "destructive": 0, "read": 1},
            "tools": [
                {"name": "task", "risk": "write"},
                {"name": "search", "risk": "read"},
            ],
            "resources": ["my://mcp/manifest"],
            "resourceTemplates": [],
            "prompts": [],
            "manifest": [
                {"tool": "task", "operations": ["list", "get", "create", "update", "delete"]},
                {"tool": "search"},
            ],
        },
    ),
    (
        "No changes detected",
        {
            "server": {"name": "stable-server"},
            "risk": {"write": 1, "destructive": 0, "read": 1},
            "tools": [{"name": "ping", "risk": "read"}, {"name": "update", "risk": "write"}],
            "resources": [],
            "resourceTemplates": [],
            "prompts": [],
        },
        {
            "server": {"name": "stable-server"},
            "risk": {"write": 1, "destructive": 0, "read": 1},
            "tools": [{"name": "ping", "risk": "read"}, {"name": "update", "risk": "write"}],
            "resources": [],
            "resourceTemplates": [],
            "prompts": [],
        },
    ),
]


def _run_diff_scenarios(separator: str) -> None:
    from mcp_preflight import diff_reports

    print(f"\n{separator}")
    print("  Diff report scenarios")
    print(separator)

    for label, before, after in DIFF_SCENARIOS:
        print(f"\n{separator}")
        print(f"  {label}")
        print(f"  cmd: mcp-preflight diff before.json after.json")
        print(separator)
        print(diff_reports(before, after))

    print(separator)
    print(f"  {len(DIFF_SCENARIOS)} diff scenarios complete.")
    print(separator)


if __name__ == "__main__":
    main()
