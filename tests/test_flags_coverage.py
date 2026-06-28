from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from conftest import TOY_DIR, run_preflight_json


def test_flag_json_default_text_mode_without_json() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "mcp_surfaceprint", sys.executable, str(TOY_DIR / "toy_open.py")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    # Should produce human-readable output with server name.
    assert "toy-open (MCP" in proc.stdout


def test_flag_command_single_string_is_shlex_split() -> None:
    # Pass the entire server command as one argument to ensure shlex splitting path works.
    cmd = f"{sys.executable} {TOY_DIR / 'toy_open.py'}"
    proc = run_preflight_json([cmd])
    snap = json.loads(proc.stdout)
    assert snap["observation"]["serverName"] == "toy-open"
    assert snap["observation"]["status"] == "ok"


def test_flag_timeout_triggers_timeout_status_for_non_mcp_process() -> None:
    # A non-MCP process that sleeps should cause initialize() to time out.
    proc = run_preflight_json(["--timeout", "0.3", sys.executable, "-c", "import time; time.sleep(5)"], check=False)
    assert proc.returncode != 0
    snap = json.loads(proc.stdout)
    assert snap["observation"]["status"] == "timeout"
    assert any(e.get("rule") == "timeout" for e in snap["observation"].get("errors", []))


def test_auth_hint_on_startup_failure_prints_clean_auth_required_message() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "mcp_surfaceprint", "--json", sys.executable, str(TOY_DIR / "toy_auth_crash.py")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.returncode != 0
    snap = json.loads(proc.stdout)
    assert snap["observation"]["status"] == "auth_required"
    assert "authentication required" in proc.stderr
    # Default output should be clean: stderr is hidden unless --verbose.
    assert "[server stderr]" not in proc.stderr
    assert "Fatal error:" not in proc.stderr


def test_auth_hint_startup_failure_verbose_includes_full_stderr() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "mcp_surfaceprint",
            "--verbose",
            "--json",
            sys.executable,
            str(TOY_DIR / "toy_auth_crash.py"),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.returncode != 0
    snap = json.loads(proc.stdout)
    assert snap["observation"]["status"] == "auth_required"
    assert "authentication required" in proc.stderr
    assert "[server stderr]" in proc.stderr
    assert "at main (" in proc.stderr

def test_flag_cwd_changes_server_working_directory() -> None:
    with tempfile.TemporaryDirectory() as td:
        cwd_dir = Path(td) / "cwd-target"
        cwd_dir.mkdir(parents=True, exist_ok=True)
        proc = run_preflight_json(["--cwd", str(cwd_dir), sys.executable, str(TOY_DIR / "toy_cwd_aware.py")])
        snap = json.loads(proc.stdout)
        tool_names = [t["name"] for t in snap["surface"]["tools"]]
        assert "cwd_cwd-target" in tool_names


def test_flag_env_repeatable_and_overrides_previous_value() -> None:
    proc = run_preflight_json(
        [
            "--env",
            "TOY_ENV_VAL=first",
            "--env",
            "TOY_ENV_VAL=second",
            sys.executable,
            str(TOY_DIR / "toy_env_aware.py"),
        ]
    )
    snap = json.loads(proc.stdout)
    tool_names = [t["name"] for t in snap["surface"]["tools"]]
    assert "env_val_second" in tool_names
    assert "env_val_first" not in tool_names


def test_flag_verbose_prints_server_stderr_block() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "mcp_surfaceprint", "--verbose", "--json", sys.executable, str(TOY_DIR / "toy_stderr_chatty.py")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    # mcp-surfaceprint adds a labeled block when --verbose is on.
    assert "[server stderr]" in proc.stderr


def test_flag_default_does_not_print_server_stderr_on_success() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "mcp_surfaceprint", "--json", sys.executable, str(TOY_DIR / "toy_stderr_chatty.py")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    assert "[server stderr]" not in proc.stderr


def test_flag_quiet_suppresses_server_stderr_capture_and_output() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "mcp_surfaceprint", "--quiet", "--json", sys.executable, str(TOY_DIR / "toy_stderr_chatty.py")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    assert proc.stderr.strip() == ""


def test_flags_quiet_and_verbose_are_mutually_exclusive() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "mcp_surfaceprint",
            "--quiet",
            "--verbose",
            "--json",
            sys.executable,
            str(TOY_DIR / "toy_open.py"),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.returncode != 0
    assert "not allowed with argument" in (proc.stderr + proc.stdout)


def test_no_command_prints_usage_and_exits_nonzero() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "mcp_surfaceprint"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.returncode != 0
    assert "Usage:" in (proc.stdout + proc.stderr)

