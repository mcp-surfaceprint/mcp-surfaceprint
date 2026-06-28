from __future__ import annotations

import asyncio

from mcp_surfaceprint import contains_timeout, stderr_notes


def test_stderr_notes_auth_hint_detection() -> None:
    notes, flags = stderr_notes("Unauthorized: authentication required. Please authenticate.\n")
    assert flags["has_auth_hint"] is True
    assert any(n.get("rule") == "auth_hint" for n in notes)


def test_stderr_notes_stacktrace_detection() -> None:
    notes, flags = stderr_notes("TypeError: boom\n")
    assert flags["has_stacktrace"] is True
    assert any(n.get("rule") == "startup_stacktrace" for n in notes)


def test_contains_timeout_simple_timeout() -> None:
    assert contains_timeout(asyncio.TimeoutError())
    assert contains_timeout(asyncio.CancelledError())

