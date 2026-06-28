"""
Toy "server" process that mimics an auth-gated Node server that then crashes.

This isn't a real MCP server: it writes auth + fatal error lines to stderr and exits.
Used to test mcp-surfaceprint's clean failure messaging.
"""

from __future__ import annotations

import sys


def main() -> None:
    sys.stderr.write("Warning: No authentication token found. Use auth_login tool to authenticate.\n")
    sys.stderr.write("Fatal error: ReferenceError: Cannot access 'server' before initialization\n")
    sys.stderr.write("    at main (file:///tmp/fake/dist/index.js:240:5)\n")
    sys.stderr.flush()
    raise SystemExit(1)


if __name__ == "__main__":
    main()

