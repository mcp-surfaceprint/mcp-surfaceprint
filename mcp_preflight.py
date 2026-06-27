"""
mcp-preflight — See what an MCP server does before you trust it.

Usage:
  mcp-preflight "uv run server.py"
  mcp-preflight "npx my-mcp-server"
  mcp-preflight "python /path/to/server.py"
  mcp-preflight --save report.json "uv run server.py"
  mcp-preflight diff before.json after.json
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shlex
import shutil
import sys
import tempfile
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

__version__ = "0.3.0"

# Exception groups are built-in in Python 3.11+, but on 3.10 they're provided by the
# `exceptiongroup` backport (often installed as a transitive dependency).
try:  # Python 3.11+
    _BaseExceptionGroup = BaseExceptionGroup  # type: ignore[name-defined]
except NameError:  # Python <= 3.10
    try:
        from exceptiongroup import BaseExceptionGroup as _BaseExceptionGroup  # type: ignore
    except Exception:  # pragma: no cover
        _BaseExceptionGroup = None


# ── Risk classification ──────────────────────────────────────
# Best-effort keyword heuristic — output labels it as such. Preflight is a lens, not a judge.

READ_PATTERNS = re.compile(
    r"\b(get|list|search|read|fetch|find|show|view)\b",
    re.IGNORECASE,
)
WRITE_PATTERNS = re.compile(
    r"\b(create|add|update|set|send|write|upload)\b",
    re.IGNORECASE,
)
DESTRUCTIVE_PATTERNS = re.compile(
    r"\b(delete|remove|destroy|drop|purge|clear|reset)\b",
    re.IGNORECASE,
)


def classify_tool(name: str, description: str) -> tuple[str, str]:
    """Classify a tool's risk level from its name and description."""
    # Normalize tool names like `get_file_info` so \bget\b matches:
    # underscores/dashes are "word chars" in regex, so treat them as separators.
    text = f"{name} {description}"
    text = re.sub(r"[_-]+", " ", text)

    if DESTRUCTIVE_PATTERNS.search(text):
        return "🔴", "destructive"
    if WRITE_PATTERNS.search(text):
        return "🟡", "write"
    if READ_PATTERNS.search(text):
        return "🟢", "read"
    # Unknown → 🟡 (assume write until proven otherwise).
    return "🟡", "write"

def _normalize_text(s: object) -> str:
    return " ".join(str(s).split())

def _normalize_declared_text(value: str | None) -> str | None:
    """Normalize declared text without semantic whitespace rewriting."""
    if value is None:
        return None
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _json_safe(v: Any) -> Any:
    """Best-effort conversion of a value into JSON-safe primitives (observation only)."""
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, dict):
        return {str(k): _json_safe(val) for k, val in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    return _normalize_text(v)

def _json_identity(v: Any) -> Any:
    """Strict JSON conversion for identity-bearing surface fields."""
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, dict):
        return {str(k): _json_identity(val) for k, val in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_identity(x) for x in v]
    raise TypeError(f"Non-JSON identity value: {type(v).__name__}")


def _tool_dict(tool: Any) -> dict:
    desc = tool.description or "(no description)"
    icon, risk = classify_tool(tool.name, desc)
    return {"name": tool.name, "description": _normalize_text(desc), "risk": risk, "icon": icon}

def _tool_surface_dict(tool: Any) -> dict:
    """Tool entry for the hashed declared surface."""
    desc = getattr(tool, "description", None)
    schema = getattr(tool, "inputSchema", None)
    return {
        "name": tool.name,
        "description": _normalize_declared_text(desc) if isinstance(desc, str) else None,
        "inputSchema": _json_identity(schema) if schema is not None else None,
    }


def _prompt_dict(prompt: Any) -> dict:
    args = []
    if hasattr(prompt, "arguments") and prompt.arguments:
        args = [a.name for a in prompt.arguments]
    desc = getattr(prompt, "description", None)
    return {
        "name": prompt.name,
        "arguments": args,
        "description": _normalize_text(desc) if desc else None,
    }

def _prompt_surface_dict(prompt: Any) -> dict:
    """Prompt entry for the hashed declared surface."""
    desc = getattr(prompt, "description", None)
    args: list[dict] = []
    raw_args = getattr(prompt, "arguments", None)
    if raw_args:
        for a in raw_args:
            entry: dict[str, Any] = {"name": getattr(a, "name", None)}
            a_desc = getattr(a, "description", None)
            if isinstance(a_desc, str):
                entry["description"] = _normalize_declared_text(a_desc)
            if hasattr(a, "required"):
                req = getattr(a, "required")
                if isinstance(req, bool):
                    entry["required"] = req
            # Some implementations expose a schema-like dict; include only if it's JSON-safe.
            a_schema = getattr(a, "schema", None)
            if isinstance(a_schema, dict):
                entry["schema"] = _json_identity(a_schema)
            args.append(entry)
    args.sort(key=lambda x: x.get("name") or "")
    return {
        "name": prompt.name,
        "arguments": args,
        "description": _normalize_declared_text(desc) if isinstance(desc, str) else None,
    }


def _resource_surface_dict(resource: Any) -> dict:
    ann = getattr(resource, "annotations", None)
    return {
        "uri": str(getattr(resource, "uri", "")),
        "name": getattr(resource, "name", None),
        "title": getattr(resource, "title", None),
        "description": _normalize_declared_text(getattr(resource, "description", None)),
        "mimeType": getattr(resource, "mimeType", None),
        "annotations": _json_identity(ann) if ann is not None else None,
    }


def _resource_template_surface_dict(tpl: Any) -> dict:
    ann = getattr(tpl, "annotations", None)
    return {
        "uriTemplate": str(getattr(tpl, "uriTemplate", "")),
        "name": getattr(tpl, "name", None),
        "title": getattr(tpl, "title", None),
        "description": _normalize_declared_text(getattr(tpl, "description", None)),
        "mimeType": getattr(tpl, "mimeType", None),
        "annotations": _json_identity(ann) if ann is not None else None,
    }


def _parse_capabilities_resource(raw: str) -> dict | None:
    """Parse and validate a capabilities resource JSON string.

    Returns the parsed dict if it has the expected shape (a ``tools`` key whose
    values are dicts), or ``None`` if the data doesn't match.

    If the data is malformed we skip silently rather than guess — never fabricate
    capability info the server didn't declare.
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(data, dict) or "tools" not in data:
        return None

    tools = data["tools"]
    if not isinstance(tools, dict):
        return None

    # Every entry under "tools" must be a dict.
    for _name, info in tools.items():
        if not isinstance(info, dict):
            return None

    return data


def _expand_tool_capabilities(caps_data: dict) -> list[dict]:
    """Return a sorted list of per-tool capability summaries.

    Each entry has ``tool``, ``description``, and optionally ``operations``
    (a list of action names when the tool has a ``dispatch_key``).

    One tool ≠ one capability — operations are only expanded when the server
    explicitly declares a dispatch_key.  We never infer multiplexing.
    """
    items: list[dict] = []
    for name, info in caps_data.get("tools", {}).items():
        entry: dict[str, Any] = {"tool": name}
        if info.get("description"):
            entry["description"] = info["description"]
        ops = info.get("operations")
        if info.get("dispatch_key") and isinstance(ops, list) and ops:
            entry["operations"] = ops
        items.append(entry)
    items.sort(key=lambda e: e["tool"])
    return items


def _find_list_duplicates(values: list[Any]) -> list[Any]:
    """Return a stable list of duplicate values (by JSON identity when possible)."""
    seen: set[str] = set()
    dupes: dict[str, Any] = {}
    for v in values:
        try:
            key = json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except Exception:
            key = _normalize_text(v)
        if key in seen and key not in dupes:
            dupes[key] = v
        else:
            seen.add(key)
    # Stable output order.
    return [dupes[k] for k in sorted(dupes.keys())]


SUSPICIOUS_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("prompt injection phrase", re.compile(r"\b(ignore|disregard)\b.*\b(instructions|system|developer)\b", re.I)),
    ("secret exfiltration", re.compile(r"\b(exfiltrat|steal|leak)\w*\b", re.I)),
    ("do not tell user", re.compile(r"\b(don't|do not)\b.*\b(tell|mention|reveal)\b.*\b(user)\b", re.I)),
    ("system prompt mention", re.compile(r"\b(system prompt|developer message)\b", re.I)),
    # base64 shows up in benign contexts (e.g. image tools), so keep this focused on actual key material.
    ("encoded secret material", re.compile(r"\bBEGIN [A-Z ]+ KEY\b", re.I)),
    ("shell download hint", re.compile(r"\b(curl|wget)\b\s+https?://", re.I)),
]


def collect_signals(
    tools: list[dict], resource_uris: list[str], template_uris: list[str], prompts: list[dict]
) -> list[dict]:
    signals: list[dict] = []

    def scan(kind: str, name: str, text: str):
        for label, pat in SUSPICIOUS_PATTERNS:
            if pat.search(text):
                signals.append(
                    {
                        "kind": kind,
                        "name": name,
                        "rule": label,
                        "snippet": text[:200] + ("..." if len(text) > 200 else ""),
                    }
                )

    for t in tools:
        scan("tool", t["name"], f'{t["name"]} {t["description"]}')
    for uri in resource_uris:
        u = str(uri)
        scan("resource", u, u)
    for uri in template_uris:
        u = str(uri)
        scan("resource_template", u, u)
    for p in prompts:
        text = f'{p["name"]} {" ".join(p.get("arguments") or [])} {p.get("description") or ""}'.strip()
        scan("prompt", p["name"], text)

    # Stable ordering for screenshots/diffs
    signals.sort(key=lambda s: (s.get("kind", ""), s.get("name", ""), s.get("rule", "")))
    return signals


# ── Output formatting ────────────────────────────────────────

def print_header(server_name: str, protocol_version: str) -> None:
    print(f"{server_name} (MCP {protocol_version})\n")


def print_tools(tools: list[dict]) -> None:
    if not tools:
        print("  MCP Tools (client-visible): none\n")
        return

    name_width = min(max(len(t["name"]) for t in tools), 28)
    term_width = shutil.get_terminal_size(fallback=(100, 20)).columns

    print("  MCP Tools (client-visible):")
    for tool in tools:
        icon = tool["icon"]
        desc = tool["description"].replace('"', '\\"')

        prefix = f'    {icon} {tool["name"]:<{name_width}} '
        quote_prefix = prefix + '"'
        cont_prefix = " " * len(quote_prefix)
        available = max(20, term_width - len(quote_prefix) - 1)  # -1 for closing quote

        wrapped = textwrap.wrap(desc, width=available) or [""]
        if len(wrapped) == 1:
            print(f'{quote_prefix}{wrapped[0]}"')
        else:
            print(f"{quote_prefix}{wrapped[0]}")
            for line in wrapped[1:-1]:
                print(f"{cont_prefix}{line}")
            print(f'{cont_prefix}{wrapped[-1]}"')
            print()

    print()


def print_resources(
    resource_uris: list[str], template_uris: list[str], *, supported: bool = True, had_error: bool = False
) -> None:
    has_any = resource_uris or template_uris
    if not has_any:
        if not supported:
            print("  Resources: not supported by server\n")
        elif had_error:
            print("  Resources: unknown\n")
        else:
            print("  Resources: none\n")
        return

    print("  Resources:")
    for uri in sorted(resource_uris):
        print(f"    📄 {uri}")
    for uri in sorted(template_uris):
        print(f"    📄 {uri}")
    print()


def print_tool_capabilities(tool_caps: list[dict]) -> None:
    """Print expanded tool capabilities showing per-tool operations.

    Output labels this data as server-declared and notes that MCP introspection
    alone cannot surface it — visibility without overstating what we know.
    """
    if not tool_caps:
        return

    total_ops = 0
    for entry in tool_caps:
        ops = entry.get("operations")
        total_ops += len(ops) if ops else 1

    ops_word = "operation" if total_ops == 1 else "operations"
    tools_word = "tool" if len(tool_caps) == 1 else "tools"
    print(f"  Additional declared operations (from server manifest, {total_ops} {ops_word} across {len(tool_caps)} {tools_word}):")
    print("    Not represented as separate entries in tools/list.")
    print("    These are server-declared actions multiplexed behind the tools above.")
    for entry in tool_caps:
        name = entry["tool"]
        ops = entry.get("operations")
        if ops:
            print(f"      ↳ {name} ({len(ops)}): {', '.join(ops)}")
        else:
            print(f"      ↳ {name} (single action)")
    print()


def print_prompts(prompts: list[dict], *, supported: bool = True, had_error: bool = False) -> None:
    if not prompts:
        if not supported:
            print("  Prompts: not supported by server\n")
        elif had_error:
            print("  Prompts: unknown\n")
        else:
            print("  Prompts: none\n")
        return

    print("  Prompts:")
    for p in sorted(prompts, key=lambda x: x.get("name", "")):
        args = ""
        if p.get("arguments"):
            raw_args = p["arguments"]
            # Supports both legacy ["a","b"] args and surface [{"name":"a"},...] args.
            if raw_args and isinstance(raw_args[0], dict):
                arg_names = [a.get("name") for a in raw_args if isinstance(a, dict) and a.get("name")]
            else:
                arg_names = raw_args
            args = f" ({', '.join(arg_names)})"
        print(f"    💬 {p['name']}{args}")
    print()


def print_signals(signals: list[dict]):
    if not signals:
        return
    print("  Signals (heuristic):")
    for s in signals:
        name = s.get("name") or ""
        rule = s.get("rule") or "signal"
        print(f"    ⚠️  {rule}: {s['kind']} {name}")
    print("    (may be false positives/negatives)")
    print()

def print_notes(notes: list[dict]) -> None:
    if not notes:
        return
    print("  Notes:")
    for n in notes:
        rule = n.get("rule") or "note"
        name = n.get("name") or ""
        snippet = n.get("snippet") or ""

        label = f"{name} ({rule})" if name else rule

        if snippet:
            # Show the first line, truncated for terminal readability.
            short = snippet.split("\n")[0][:120]
            if len(short) < len(snippet):
                short += "…"
            print(f"    ℹ️  {label}: {short}")
        else:
            print(f"    ℹ️  {label}")
    print()


def print_risk_summary(counts: dict) -> None:
    # Best-effort keyword heuristic — output labels it as such. Preflight is a lens, not a judge.
    w = counts.get("write", 0)
    d = counts.get("destructive", 0)
    r = counts.get("read", 0)

    if not (w or d or r):
        print("  Risk: None\n")
        return

    print("  Risk Summary:")
    if w:
        print(f"    write: {w}")
    if d:
        print(f"    destructive: {d}")
    if r:
        print(f"    read-only: {r}")
    print("    (best-effort heuristic from tool names/descriptions; not enforced)")
    print()


def _print_introspection_coverage(snapshot: dict) -> None:
    """Print a ✓/✗ checklist showing which introspection calls succeeded."""
    obs = snapshot.get("observation") or {}
    cov = obs.get("coverage") or {}

    def fmt_section(name: str, key: str) -> str | None:
        s = cov.get(key) or {}
        if not isinstance(s, dict):
            return None
        attempted = bool(s.get("attempted"))
        completed = bool(s.get("completed"))
        declared = s.get("declaredSupported")
        if declared is False and not attempted:
            return None
        if not attempted:
            return f"    - {name} (not attempted)"
        if completed:
            return f"    ✓ {name}"
        rule = s.get("errorRule") or "error"
        return f"    ✗ {name} ({rule})"

    print("  Introspection coverage:")
    for label, key in (
        ("tools", "tools"),
        ("resources", "resources"),
        ("resource templates", "resourceTemplates"),
        ("prompts", "prompts"),
        ("manifest", "manifest"),
    ):
        line = fmt_section(label, key)
        if line:
            print(line)
    print()


def _manifest_tool_caps_from_surface(surface: dict) -> list[dict]:
    for src in surface.get("declarationSources") or []:
        if isinstance(src, dict) and src.get("name") == "mcp_manifest":
            extracted = src.get("extracted") or {}
            if isinstance(extracted, dict) and isinstance(extracted.get("toolCapabilities"), list):
                return extracted["toolCapabilities"]
    return []


def print_text_report(snapshot: dict) -> None:
    """Render a finalized snapshot dict as human-readable text to stdout."""
    obs = snapshot.get("observation") or {}
    surface = snapshot.get("surface") or {}
    server_name = obs.get("serverName") or "unknown"
    protocol_version = obs.get("protocolVersion") or "unknown"
    status = obs.get("status", "ok")

    print_header(server_name, protocol_version)
    print("  Caution: the server process runs locally without sandboxing.")
    print("  Use --isolate-home to prevent access to your real HOME directory.\n")

    if status == "auth_gated":
        print("  Status: 🔒 auth-gated (server did not enumerate capabilities without credentials)\n")
        return

    if status == "partial":
        print("  Status: ⚠️  partial\n")
        _print_introspection_coverage(snapshot)

    # Surface identity: show the digest when available.
    completeness = str(snapshot.get("surfaceCompleteness") or "partial")
    digest = snapshot.get("surfaceDigest")
    if digest and completeness == "complete":
        print(f"  Surface digest: {digest}\n")
    elif status == "partial":
        print("  Surface digest: unavailable (partial inspection)\n")

    local = obs.get("localAnnotations") or {}
    print_tools(local.get("tools", []))

    capabilities = obs.get("capabilities", {})
    notes = obs.get("notes", [])
    errors = obs.get("errors", [])
    resources_had_error = any(n.get("name") in ("list_resources", "list_resource_templates") for n in notes)
    prompts_had_error = any(n.get("name") == "list_prompts" for n in notes)

    print_resources(
        [r.get("uri") for r in (surface.get("resources") or []) if isinstance(r, dict) and r.get("uri")],
        [t.get("uriTemplate") for t in (surface.get("resourceTemplates") or []) if isinstance(t, dict) and t.get("uriTemplate")],
        supported=capabilities.get("resources", True),
        had_error=resources_had_error,
    )
    print_tool_capabilities(_manifest_tool_caps_from_surface(surface))
    print_prompts(
        surface.get("prompts", []),
        supported=capabilities.get("prompts", True),
        had_error=prompts_had_error,
    )
    print_signals(local.get("signals", []))
    print_notes(notes)
    print_risk_summary(local.get("risk", {}))


# ── Main ─────────────────────────────────────────────────────

RISK_PRIORITY = {"destructive": 0, "write": 1, "read": 2}

AUTH_HINT_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bno (authentication|auth) (token|credentials?)\b", re.I),
    re.compile(r"\b(authenticate|authentication) (required|needed)\b", re.I),
    re.compile(r"\bplease authenticate\b", re.I),
    re.compile(r"\bauth_login\b", re.I),
    re.compile(r"\blogin required\b", re.I),
    re.compile(r"\bunauthorized\b", re.I),
]

STACKTRACE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bReferenceError:\b"),
    re.compile(r"\bTypeError:"),
    re.compile(r"\bUnhandledPromiseRejection\b"),
    re.compile(r"\bunhandled errors? in a TaskGroup\b", re.I),
    re.compile(r"\bFatal error\b", re.I),
]


def _mark_partial(current: str) -> str:
    """Escalate status to 'partial' without downgrading from a worse status."""
    return current if current != "ok" else "partial"


def count_risks(tools: list[dict]) -> dict:
    counts = {"read": 0, "write": 0, "destructive": 0}
    for t in tools:
        counts[t["risk"]] = counts.get(t["risk"], 0) + 1
    return counts


def contains_timeout(exc: BaseException) -> bool:
    """Return True if exc (possibly an ExceptionGroup) contains a timeout."""
    # In practice, timeouts often surface as cancellation inside anyio TaskGroups.
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, asyncio.CancelledError)):
        return True
    # anyio cancellation/stream teardown frequently shows up as BrokenResourceError/ClosedResourceError.
    if type(exc).__name__ in {"BrokenResourceError", "ClosedResourceError"}:
        return True
    # TimeoutError may be wrapped in an ExceptionGroup/BaseExceptionGroup.
    if _BaseExceptionGroup is not None and isinstance(exc, _BaseExceptionGroup):  # type: ignore[arg-type]
        for sub in getattr(exc, "exceptions", ()):
            if contains_timeout(sub):
                return True
    return False


def _stderr_excerpt(server_err: str, *, max_chars: int = 1500) -> str:
    s = server_err.strip()
    if len(s) <= max_chars:
        return s
    # Prefer the end of stderr (often has the final error/stacktrace).
    tail = s[-max_chars:]
    # Avoid cutting in the middle of a line when possible.
    nl = tail.find("\n")
    if 0 <= nl <= 200:
        tail = tail[nl + 1 :]
    return "…\n" + tail


def stderr_notes(server_err: str) -> tuple[list[dict], dict]:
    """
    Return (notes, stderr_signals) derived from raw server stderr.
    stderr_signals is a small dict used for status classification.
    """
    notes: list[dict] = []
    text = _normalize_text(server_err)
    has_auth_hint = any(p.search(text) for p in AUTH_HINT_PATTERNS)
    has_stacktrace = any(p.search(server_err) for p in STACKTRACE_PATTERNS)
    if has_auth_hint:
        notes.append(
            {
                "kind": "server",
                "name": "stderr",
                "rule": "auth_hint",
                "snippet": _stderr_excerpt(server_err, max_chars=600)[:600],
            }
        )
    if has_stacktrace:
        notes.append(
            {
                "kind": "server",
                "name": "stderr",
                "rule": "startup_stacktrace",
                "snippet": _stderr_excerpt(server_err, max_chars=900)[:900],
            }
        )
    notes.sort(key=lambda n: (n.get("kind", ""), n.get("name", ""), n.get("rule", "")))
    return notes, {"has_auth_hint": has_auth_hint, "has_stacktrace": has_stacktrace}


def _relevant_stderr_lines(server_err: str, *, max_lines: int = 3) -> str:
    """
    Extract a small, high-signal subset of stderr for cleaner default output.

    Intended for auth-gated / startup error cases where full stack traces are noisy.
    """
    lines = [ln.rstrip() for ln in (server_err or "").splitlines() if ln.strip()]
    if not lines:
        return ""

    picked: list[str] = []
    for ln in lines:
        # Prefer auth hints and the first "fatal error" / exception line.
        if any(p.search(ln) for p in AUTH_HINT_PATTERNS) or re.search(r"\b(Fatal error|ReferenceError:|TypeError:|Error:)\b", ln):
            if ln not in picked:
                picked.append(ln)
        if len(picked) >= max_lines:
            break

    # Fallback: just show the first line or two.
    if not picked:
        picked = lines[: min(max_lines, 2)]

    return "\n".join(picked).strip()


def _build_report(
    *,
    scanned_command: list[str],
    server_name: str,
    protocol_version: str,
    capabilities: dict[str, bool],
    status: str,
    tools: list[dict],
    resource_uris: list[str],
    template_uris: list[str],
    prompts: list[dict],
    signals: list[dict],
    notes: list[dict],
    risk: dict,
    errors: list[dict] | None = None,
    tool_capabilities: list[dict] | None = None,
) -> dict:
    report = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "scannedCommand": scanned_command,
        "server": {"name": server_name, "protocolVersion": protocol_version},
        "capabilities": capabilities,
        "status": status,
        "tools": tools,
        "resources": resource_uris,
        "resourceTemplates": template_uris,
        "prompts": prompts,
        "risk": risk,
        "signals": signals,
        "notes": notes,
        "errors": errors or [],
    }
    if tool_capabilities is not None:
        report["manifest"] = tool_capabilities
    return report


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    # Deterministic JSON for hashing: no whitespace, UTF-8, stable key ordering (after canonicalization).
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def _canonicalize_schema(schema: Any) -> Any:
    """Normalize JSON Schema-ish objects for stable identity."""
    if isinstance(schema, dict):
        out: dict[str, Any] = {}
        for k in sorted(schema.keys()):
            v = schema[k]
            if k in ("required", "enum") and isinstance(v, list):
                # Treat as sets; sort deterministically.
                try:
                    out[k] = sorted(v)
                except TypeError:
                    out[k] = sorted((_normalize_text(x) for x in v))
                continue
            # Do not reorder oneOf/anyOf/allOf by default; ordering can matter for some tooling.
            out[k] = _canonicalize_schema(v)
        return out
    if isinstance(schema, list):
        return [_canonicalize_schema(x) for x in schema]
    return schema


def _canonicalize_surface(surface: dict) -> dict:
    """Return a deterministically ordered/normalized surface object for hashing."""
    tools = surface.get("tools") or []
    resources = surface.get("resources") or []
    templates = surface.get("resourceTemplates") or []
    prompts = surface.get("prompts") or []
    decl_sources = surface.get("declarationSources") or []

    norm_tools: list[dict] = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        entry = {
            "name": t.get("name"),
            "description": t.get("description"),
            "inputSchema": _canonicalize_schema(t.get("inputSchema")),
        }
        norm_tools.append(entry)
    norm_tools.sort(key=lambda x: x.get("name") or "")

    norm_resources: list[dict] = []
    for r in resources:
        if not isinstance(r, dict):
            norm_resources.append({"uri": r})
            continue
        norm_resources.append(
            {
                "uri": r.get("uri"),
                "name": r.get("name"),
                "title": r.get("title"),
                "description": r.get("description"),
                "mimeType": r.get("mimeType"),
                "annotations": _canonicalize_schema(r.get("annotations")),
            }
        )
    norm_resources.sort(key=lambda x: x.get("uri") or "")

    norm_templates: list[dict] = []
    for t in templates:
        if not isinstance(t, dict):
            norm_templates.append({"uriTemplate": t})
            continue
        norm_templates.append(
            {
                "uriTemplate": t.get("uriTemplate"),
                "name": t.get("name"),
                "title": t.get("title"),
                "description": t.get("description"),
                "mimeType": t.get("mimeType"),
                "annotations": _canonicalize_schema(t.get("annotations")),
            }
        )
    norm_templates.sort(key=lambda x: x.get("uriTemplate") or "")

    norm_prompts: list[dict] = []
    for p in prompts:
        if not isinstance(p, dict):
            continue
        args = p.get("arguments") or []
        norm_args: list[dict] = []
        for a in args:
            if not isinstance(a, dict):
                continue
            arg_entry: dict[str, Any] = {"name": a.get("name")}
            if a.get("description") is not None:
                arg_entry["description"] = a.get("description")
            if a.get("required") is not None:
                arg_entry["required"] = a.get("required")
            if a.get("schema") is not None:
                arg_entry["schema"] = _canonicalize_schema(a.get("schema"))
            norm_args.append(arg_entry)
        norm_args.sort(key=lambda x: x.get("name") or "")
        norm_prompts.append(
            {
                "name": p.get("name"),
                "description": p.get("description"),
                "arguments": norm_args,
            }
        )
    norm_prompts.sort(key=lambda x: x.get("name") or "")

    def _canonicalize_manifest_tool_capabilities(tool_caps: Any) -> Any:
        """
        Canonicalize the extracted mcp_manifest toolCapabilities list for identity.

        Contract:
        - toolCapabilities entries are sorted by `tool`
        - `operations` order is not identity-bearing; values are sorted deterministically.
          Duplicate values are preserved for detection and should cause the observation to be partial.
        """
        if not isinstance(tool_caps, list):
            return _canonicalize_schema(tool_caps)

        norm: list[dict] = []
        for e in tool_caps:
            if not isinstance(e, dict) or not e.get("tool"):
                # Preserve nonconforming entries deterministically; they still participate in identity.
                norm.append(_canonicalize_schema(e) if isinstance(e, (dict, list)) else {"value": e})
                continue

            entry: dict[str, Any] = {"tool": str(e.get("tool"))}
            if "description" in e:
                entry["description"] = e.get("description")

            if "operations" in e and isinstance(e.get("operations"), list):
                ops = e.get("operations") or []
                # Sort for identity without silently deduping.
                try:
                    entry["operations"] = sorted(ops)
                except TypeError:
                    entry["operations"] = sorted(ops, key=_normalize_text)

            # Preserve any additional fields deterministically.
            for k in sorted(set(e.keys()) - {"tool", "description", "operations"}):
                entry[k] = _canonicalize_schema(e.get(k))

            norm.append(entry)

        norm.sort(key=lambda x: x.get("tool") or "")
        return norm

    def _canonicalize_decl_source_extracted(extracted: Any) -> Any:
        if not isinstance(extracted, dict):
            return _canonicalize_schema(extracted)

        out: dict[str, Any] = {}
        for k in sorted(extracted.keys()):
            if k == "toolCapabilities":
                out[k] = _canonicalize_manifest_tool_capabilities(extracted.get(k))
            else:
                out[k] = _canonicalize_schema(extracted.get(k))
        return out

    norm_decl_sources: list[dict] = []
    for s in decl_sources:
        if not isinstance(s, dict):
            continue
        # Keep only identity-bearing facts here; errors/notes should live in observation.
        entry: dict[str, Any] = {}
        for k in ("sourceType", "name", "uri", "extracted"):
            if k in s:
                entry[k] = _canonicalize_decl_source_extracted(s[k]) if k in ("extracted",) else s[k]
        norm_decl_sources.append(entry)
    norm_decl_sources.sort(key=lambda x: (x.get("sourceType") or "", x.get("uri") or "", x.get("name") or ""))

    return {
        "tools": norm_tools,
        "resources": norm_resources,
        "resourceTemplates": norm_templates,
        "prompts": norm_prompts,
        "declarationSources": norm_decl_sources,
    }


def _compute_surface_digest(surface: dict) -> str:
    canonical = _canonicalize_surface(surface)
    return "sha256:" + _sha256_hex(_canonical_json_bytes(canonical))


def _surface_entity_digests(surface: dict) -> dict:
    """Derived per-entity digests (not included in surface hashing)."""
    canonical = _canonicalize_surface(surface)
    tool_d: dict[str, str] = {}
    for t in canonical.get("tools", []):
        name = t.get("name")
        if name:
            tool_d[str(name)] = "sha256:" + _sha256_hex(_canonical_json_bytes(t))
    prompt_d: dict[str, str] = {}
    for p in canonical.get("prompts", []):
        name = p.get("name")
        if name:
            prompt_d[str(name)] = "sha256:" + _sha256_hex(_canonical_json_bytes(p))
    resource_d: dict[str, str] = {}
    for r in canonical.get("resources", []):
        uri = r.get("uri")
        if uri:
            resource_d[str(uri)] = "sha256:" + _sha256_hex(_canonical_json_bytes(r))
    template_d: dict[str, str] = {}
    for t in canonical.get("resourceTemplates", []):
        uri = t.get("uriTemplate")
        if uri:
            template_d[str(uri)] = "sha256:" + _sha256_hex(_canonical_json_bytes(t))
    return {
        "tools": tool_d,
        "prompts": prompt_d,
        "resources": resource_d,
        "resourceTemplates": template_d,
    }


def _surface_completeness_from_coverage(coverage: dict) -> str:
    """Return 'complete' if all identity-bearing sections succeeded or were unsupported."""
    for key in ("tools", "resources", "resourceTemplates", "prompts", "manifest"):
        s = coverage.get(key) or {}
        if not isinstance(s, dict):
            return "partial"
        declared = s.get("declaredSupported")
        attempted = bool(s.get("attempted"))
        completed = bool(s.get("completed"))
        # Completed sections are complete regardless of whether they were attempted
        # (e.g. manifest absent but resources introspection succeeded).
        if completed:
            continue
        # Explicitly unsupported sections count as complete if we did not attempt them.
        if declared is False and not attempted:
            continue
        # For v0.2, 'complete' means we attempted each standard list method (or explicitly
        # marked the section unsupported) and it completed successfully.
        if not attempted and declared is not False:
            return "partial"
        # Anything else means we don't have a complete declared surface.
        return "partial"
    return "complete"


def _build_snapshot(
    *,
    generated_at: str,
    scanned_command: list[str],
    server_name: str,
    protocol_version: str,
    capabilities: dict[str, bool],
    status: str,
    coverage: dict,
    surface: dict,
    tools_for_text: list[dict],
    risk: dict,
    signals: list[dict],
    notes: list[dict],
    errors: list[dict],
) -> dict:
    surface_completeness = _surface_completeness_from_coverage(coverage)
    snapshot: dict[str, Any] = {
        "snapshotFormatVersion": "1",
        "surfaceCompleteness": surface_completeness,
        "observation": {
            "generatedAt": generated_at,
            "protocolVersion": protocol_version,
            "serverName": server_name,
            "command": scanned_command,
            "status": status,
            "capabilities": capabilities,
            "coverage": coverage,
            "notes": notes,
            "errors": errors,
            "localAnnotations": {
                "tools": tools_for_text,
                "risk": risk,
                "signals": signals,
            },
        },
        "surface": surface,
    }
    if surface_completeness == "complete":
        try:
            snapshot["surfaceDigest"] = _compute_surface_digest(surface)
            snapshot["surfaceEntityDigests"] = _surface_entity_digests(surface)
        except Exception as e:
            # Identity must be stable and standards-compliant; fall back to partial if hashing fails.
            snapshot["surfaceCompleteness"] = "partial"
            obs = snapshot.get("observation") or {}
            obs["notes"] = (obs.get("notes") or []) + [
                {"kind": "snapshot", "name": "surfaceDigest", "rule": "hash_error", "snippet": _normalize_text(str(e))}
            ]
            snapshot["observation"] = obs
    return snapshot


async def inspect(
    command: str,
    args: list[str],
    *,
    timeout_s: float = 10.0,
    errlog: TextIO | None = None,
    env: dict[str, str] | None = None,
    cwd: str | Path | None = None,
    include_signals: bool = True,
) -> dict:
    server_params = StdioServerParameters(command=command, args=args, env=env, cwd=cwd)

    async with stdio_client(server_params, errlog=errlog or sys.stderr) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            result = await asyncio.wait_for(session.initialize(), timeout=timeout_s)

            server_name = "unknown"
            if hasattr(result, "serverInfo") and result.serverInfo:
                server_name = result.serverInfo.name
            protocol_version = getattr(result, "protocolVersion", "unknown")

            # Read server-declared capabilities.
            caps = getattr(result, "capabilities", None)
            has_tools = caps is not None and getattr(caps, "tools", None) is not None
            has_resources = caps is not None and getattr(caps, "resources", None) is not None
            has_prompts = caps is not None and getattr(caps, "prompts", None) is not None

            status = "ok"
            errors: list[dict] = []
            notes: list[dict] = []
            coverage: dict[str, Any] = {
                "tools": {
                    "declaredSupported": (True if has_tools else False) if caps is not None else None,
                    "attempted": True,
                    "completed": False,
                },
                "resources": {
                    "declaredSupported": (True if has_resources else False) if caps is not None else None,
                    "attempted": False,
                    "completed": False,
                },
                "resourceTemplates": {
                    "declaredSupported": (True if has_resources else False) if caps is not None else None,
                    "attempted": False,
                    "completed": False,
                },
                "prompts": {
                    "declaredSupported": (True if has_prompts else False) if caps is not None else None,
                    "attempted": False,
                    "completed": False,
                },
                "manifest": {"declaredSupported": None, "attempted": False, "completed": False},
            }

            # Tools — always attempt even if not declared (many servers omit the capability).
            tools: list[dict] = []
            tools_surface: list[dict] = []
            try:
                tools_raw = (await asyncio.wait_for(session.list_tools(), timeout=timeout_s)).tools
                tools = [_tool_dict(t) for t in tools_raw]
                tools.sort(key=lambda t: (RISK_PRIORITY.get(t["risk"], 9), t["name"]))
                tools_surface = [_tool_surface_dict(t) for t in tools_raw]
                tools_surface.sort(key=lambda t: t.get("name") or "")
                coverage["tools"]["completed"] = True
                coverage["tools"]["itemCount"] = len(tools_raw or [])
            except asyncio.TimeoutError:
                status = _mark_partial(status)
                errors.append(
                    {
                        "kind": "mcp",
                        "name": "list_tools",
                        "rule": "timeout",
                        "snippet": f"Timed out after {timeout_s}s",
                    }
                )
                coverage["tools"]["errorRule"] = "timeout"
            except Exception as e:
                status = _mark_partial(status)
                errors.append(
                    {
                        "kind": "mcp",
                        "name": "list_tools",
                        "rule": "error",
                        "snippet": _normalize_text(str(e)),
                    }
                )
                coverage["tools"]["errorRule"] = "error"
            risk = count_risks(tools)

            def _mark_duplicates(items: list[dict], key: str, coverage_key: str) -> None:
                seen: set[str] = set()
                dupes: set[str] = set()
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    v = it.get(key)
                    if v is None:
                        continue
                    s = str(v)
                    if s in seen:
                        dupes.add(s)
                    else:
                        seen.add(s)
                if dupes:
                    nonlocal status
                    status = _mark_partial(status)
                    notes.append(
                        {
                            "kind": "snapshot",
                            "name": coverage_key,
                            "rule": "duplicate_identity",
                            "snippet": ", ".join(sorted(dupes))[:500],
                        }
                    )
                    coverage[coverage_key]["completed"] = False
                    coverage[coverage_key]["errorRule"] = "duplicate_identity"

            # Resources — attempt discovery even if not declared (servers may omit capability flags).
            resources = []
            templates = []
            def _looks_unsupported(err: str) -> bool:
                s = err.lower()
                return "method not found" in s or "not supported" in s or "unknown method" in s

            coverage["resources"]["attempted"] = True
            try:
                resources = (await asyncio.wait_for(session.list_resources(), timeout=timeout_s)).resources
                coverage["resources"]["completed"] = True
                coverage["resources"]["declaredSupported"] = True
                coverage["resources"]["itemCount"] = len(resources or [])
            except asyncio.TimeoutError:
                status = _mark_partial(status)
                notes.append(
                    {"kind": "mcp", "name": "list_resources", "rule": "timeout", "snippet": f"Timed out after {timeout_s}s"}
                )
                coverage["resources"]["errorRule"] = "timeout"
            except Exception as e:
                msg = _normalize_text(str(e))
                if _looks_unsupported(msg):
                    coverage["resources"]["completed"] = True
                    coverage["resources"]["declaredSupported"] = False
                else:
                    status = _mark_partial(status)
                    notes.append({"kind": "mcp", "name": "list_resources", "rule": "error", "snippet": msg})
                    coverage["resources"]["errorRule"] = "error"

            coverage["resourceTemplates"]["attempted"] = True
            try:
                templates = (await asyncio.wait_for(session.list_resource_templates(), timeout=timeout_s)).resourceTemplates
                coverage["resourceTemplates"]["completed"] = True
                coverage["resourceTemplates"]["declaredSupported"] = True
                coverage["resourceTemplates"]["itemCount"] = len(templates or [])
            except asyncio.TimeoutError:
                status = _mark_partial(status)
                notes.append(
                    {
                        "kind": "mcp",
                        "name": "list_resource_templates",
                        "rule": "timeout",
                        "snippet": f"Timed out after {timeout_s}s",
                    }
                )
                coverage["resourceTemplates"]["errorRule"] = "timeout"
            except Exception as e:
                msg = _normalize_text(str(e))
                if _looks_unsupported(msg):
                    coverage["resourceTemplates"]["completed"] = True
                    coverage["resourceTemplates"]["declaredSupported"] = False
                else:
                    status = _mark_partial(status)
                    notes.append({"kind": "mcp", "name": "list_resource_templates", "rule": "error", "snippet": msg})
                    coverage["resourceTemplates"]["errorRule"] = "error"
            resource_uris = sorted([str(r.uri) for r in resources])
            template_uris = sorted([str(t.uriTemplate) for t in templates])
            resources_surface: list[dict] = []
            templates_surface: list[dict] = []
            try:
                resources_surface = [_resource_surface_dict(r) for r in resources]
                templates_surface = [_resource_template_surface_dict(t) for t in templates]
            except TypeError as e:
                status = _mark_partial(status)
                notes.append({"kind": "snapshot", "name": "surface", "rule": "non_json_identity", "snippet": _normalize_text(str(e))})
                coverage["resources"]["completed"] = False
                coverage["resources"]["errorRule"] = "non_json_identity"
                coverage["resourceTemplates"]["completed"] = False
                coverage["resourceTemplates"]["errorRule"] = "non_json_identity"

            # Manifest resource — Preflight does not call tools, but any MCP request may execute arbitrary server code.
            declaration_sources: list[dict] = []
            if resources:
                caps_resource = next(
                    (r for r in resources if str(r.uri).endswith("://mcp/manifest")),
                    None,
                )
                if caps_resource:
                    coverage["manifest"]["attempted"] = True
                    try:
                        read_result = await asyncio.wait_for(
                            session.read_resource(caps_resource.uri), timeout=timeout_s
                        )
                        if read_result.contents:
                            raw_text = getattr(read_result.contents[0], "text", None)
                            if raw_text:
                                raw_hash = "sha256:" + _sha256_hex(raw_text.encode("utf-8"))
                                caps_data = _parse_capabilities_resource(raw_text)
                                if caps_data is not None:
                                    tool_capabilities = _expand_tool_capabilities(caps_data)
                                    # Duplicate operation values are malformed; do not silently repair.
                                    dupes: list[str] = []
                                    for e in tool_capabilities:
                                        ops = e.get("operations")
                                        if isinstance(ops, list) and ops:
                                            d = _find_list_duplicates(ops)
                                            if d:
                                                tool = str(e.get("tool") or "unknown")
                                                try:
                                                    dupes.append(f"{tool}: {', '.join(str(x) for x in d)}")
                                                except Exception:
                                                    dupes.append(tool)
                                    if dupes:
                                        status = _mark_partial(status)
                                        notes.append(
                                            {
                                                "kind": "declaration_source",
                                                "name": "mcp_manifest",
                                                "rule": "duplicate_operations",
                                                "snippet": "; ".join(dupes)[:700],
                                            }
                                        )
                                        coverage["manifest"]["completed"] = False
                                        coverage["manifest"]["errorRule"] = "duplicate_operations"
                                        # Do not claim manifest completeness when malformed.
                                        # (Even though we parsed it, we refuse to produce a stable identity.)

                                    declaration_sources.append(
                                        {
                                            "sourceType": "resource",
                                            "name": "mcp_manifest",
                                            "uri": str(caps_resource.uri),
                                            "extracted": {"toolCapabilities": tool_capabilities},
                                        }
                                    )
                                    # Provenance (non-identity) belongs in observation notes.
                                    notes.append(
                                        {
                                            "kind": "declaration_source",
                                            "name": "mcp_manifest",
                                            "rule": "parsed",
                                            "snippet": raw_hash,
                                        }
                                    )
                                    if not dupes:
                                        coverage["manifest"]["completed"] = True
                                else:
                                    status = _mark_partial(status)
                                    notes.append(
                                        {
                                            "kind": "declaration_source",
                                            "name": "mcp_manifest",
                                            "rule": "invalid",
                                            "snippet": raw_hash,
                                        }
                                    )
                                    coverage["manifest"]["errorRule"] = "invalid"
                    except Exception:
                        status = _mark_partial(status)
                        notes.append(
                            {"kind": "declaration_source", "name": "mcp_manifest", "rule": "error", "snippet": "read_resource failed"}
                        )
                        coverage["manifest"]["errorRule"] = "error"
                else:
                    # Not present; counts as complete (no attempt).
                    coverage["manifest"]["attempted"] = False
                    coverage["manifest"]["completed"] = True
            else:
                # If resources were supported but list_resources failed, manifest completeness is unknown → partial.
                if has_resources and coverage["resources"].get("completed") is not True:
                    coverage["manifest"]["attempted"] = False
                    coverage["manifest"]["completed"] = False
                else:
                    coverage["manifest"]["attempted"] = False
                    coverage["manifest"]["completed"] = True

            # Prompts — attempt discovery even if not declared (servers may omit capability flags).
            prompts = []
            coverage["prompts"]["attempted"] = True
            try:
                prompts = (await asyncio.wait_for(session.list_prompts(), timeout=timeout_s)).prompts
                coverage["prompts"]["completed"] = True
                coverage["prompts"]["declaredSupported"] = True
                coverage["prompts"]["itemCount"] = len(prompts or [])
            except asyncio.TimeoutError:
                status = _mark_partial(status)
                notes.append(
                    {"kind": "mcp", "name": "list_prompts", "rule": "timeout", "snippet": f"Timed out after {timeout_s}s"}
                )
                coverage["prompts"]["errorRule"] = "timeout"
            except Exception as e:
                msg = _normalize_text(str(e))
                if _looks_unsupported(msg):
                    coverage["prompts"]["completed"] = True
                    coverage["prompts"]["declaredSupported"] = False
                else:
                    status = _mark_partial(status)
                    notes.append({"kind": "mcp", "name": "list_prompts", "rule": "error", "snippet": msg})
                    coverage["prompts"]["errorRule"] = "error"
            prompts_info = [_prompt_dict(p) for p in prompts]
            prompts_info.sort(key=lambda p: p.get("name", ""))
            prompts_surface = [_prompt_surface_dict(p) for p in prompts]
            prompts_surface.sort(key=lambda p: p.get("name") or "")

            signals: list[dict] = []
            if include_signals:
                signals = collect_signals(tools, resource_uris, template_uris, prompts_info)

            notes.sort(key=lambda n: (n.get("kind", ""), n.get("name", ""), n.get("rule", "")))

            # Duplicate detection (identity must be unambiguous).
            _mark_duplicates(tools_surface, "name", "tools")
            _mark_duplicates(resources_surface, "uri", "resources")
            _mark_duplicates(templates_surface, "uriTemplate", "resourceTemplates")
            _mark_duplicates(prompts_surface, "name", "prompts")

            generated_at = datetime.now(timezone.utc).isoformat()
            surface = {
                "tools": tools_surface,
                "resources": resources_surface,
                "resourceTemplates": templates_surface,
                "prompts": prompts_surface,
                "declarationSources": declaration_sources,
            }
            return _build_snapshot(
                generated_at=generated_at,
                scanned_command=[command, *args],
                server_name=server_name,
                protocol_version=protocol_version,
                capabilities={"tools": bool(has_tools), "resources": bool(has_resources), "prompts": bool(has_prompts)},
                status=status,
                coverage=coverage,
                surface=surface,
                tools_for_text=tools,
                risk=risk,
                signals=signals,
                notes=notes,
                errors=errors,
            )


def _json_pointer_escape_token(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _manifest_tool_caps_entry_map_from_surface(surface: dict) -> dict[str, dict]:
    """
    Return manifest tool -> capability entry mapping from a (canonical) surface dict.

    Note: this uses canonicalized declarationSources, so toolCapabilities ordering and operations
    ordering should already be normalized by `_canonicalize_surface`.
    """
    caps: dict[str, dict] = {}
    for src in surface.get("declarationSources") or []:
        if not isinstance(src, dict) or src.get("name") != "mcp_manifest":
            continue
        extracted = src.get("extracted") or {}
        if not isinstance(extracted, dict):
            continue
        for e in (extracted.get("toolCapabilities") or []):
            if isinstance(e, dict) and e.get("tool"):
                caps[str(e["tool"])] = e
    return caps


def _compute_surface_changes(before_surface: dict, after_surface: dict) -> list[dict]:
    """
    Compute stable factual change records between two surfaces.

    Important: paths emitted here are stable semantic paths (JSON-Pointer-escaped) and are not
    guaranteed to be literal pointers into the array-based serialized snapshot.
    """
    b = _canonicalize_surface(before_surface or {})
    a = _canonicalize_surface(after_surface or {})

    changes: list[dict] = []

    def add(rec: dict) -> None:
        changes.append(rec)

    def map_by(items: list[dict], key: str) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for it in items or []:
            if isinstance(it, dict) and it.get(key):
                out[str(it[key])] = it
        return out

    # Tools
    bt = map_by(b.get("tools") or [], "name")
    at = map_by(a.get("tools") or [], "name")
    for name in sorted(set(at) - set(bt)):
        add({"type": "tool_added", "entityType": "tool", "entityId": name, "path": ""})
    for name in sorted(set(bt) - set(at)):
        add({"type": "tool_removed", "entityType": "tool", "entityId": name, "path": ""})
    for name in sorted(set(bt) & set(at)):
        btool = bt[name]
        atool = at[name]
        if (btool.get("description") or "") != (atool.get("description") or ""):
            add(
                {
                    "type": "value_changed",
                    "entityType": "tool",
                    "entityId": name,
                    "path": "/description",
                    "before": btool.get("description"),
                    "after": atool.get("description"),
                }
            )
        if btool.get("inputSchema") != atool.get("inputSchema"):
            add(
                {
                    "type": "value_changed",
                    "entityType": "tool",
                    "entityId": name,
                    "path": "/inputSchema",
                    "before": btool.get("inputSchema"),
                    "after": atool.get("inputSchema"),
                }
            )

    # Resources
    br = map_by(b.get("resources") or [], "uri")
    ar = map_by(a.get("resources") or [], "uri")
    for uri in sorted(set(ar) - set(br)):
        add({"type": "resource_added", "entityType": "resource", "entityId": uri, "path": ""})
    for uri in sorted(set(br) - set(ar)):
        add({"type": "resource_removed", "entityType": "resource", "entityId": uri, "path": ""})
    for uri in sorted(set(br) & set(ar)):
        bres = br[uri]
        ares = ar[uri]
        for field in ("name", "title", "description", "mimeType", "annotations"):
            if bres.get(field) != ares.get(field):
                add(
                    {
                        "type": "value_changed",
                        "entityType": "resource",
                        "entityId": uri,
                        "path": f"/{field}",
                        "before": bres.get(field),
                        "after": ares.get(field),
                    }
                )

    # Resource templates
    btpl = map_by(b.get("resourceTemplates") or [], "uriTemplate")
    atpl = map_by(a.get("resourceTemplates") or [], "uriTemplate")
    for uri in sorted(set(atpl) - set(btpl)):
        add({"type": "resource_template_added", "entityType": "resource_template", "entityId": uri, "path": ""})
    for uri in sorted(set(btpl) - set(atpl)):
        add({"type": "resource_template_removed", "entityType": "resource_template", "entityId": uri, "path": ""})
    for uri in sorted(set(btpl) & set(atpl)):
        btmp = btpl[uri]
        atmp = atpl[uri]
        for field in ("name", "title", "description", "mimeType", "annotations"):
            if btmp.get(field) != atmp.get(field):
                add(
                    {
                        "type": "value_changed",
                        "entityType": "resource_template",
                        "entityId": uri,
                        "path": f"/{field}",
                        "before": btmp.get(field),
                        "after": atmp.get(field),
                    }
                )

    # Prompts
    bp = map_by(b.get("prompts") or [], "name")
    ap = map_by(a.get("prompts") or [], "name")
    for name in sorted(set(ap) - set(bp)):
        add({"type": "prompt_added", "entityType": "prompt", "entityId": name, "path": ""})
    for name in sorted(set(bp) - set(ap)):
        add({"type": "prompt_removed", "entityType": "prompt", "entityId": name, "path": ""})
    for name in sorted(set(bp) & set(ap)):
        bpr = bp[name]
        apr = ap[name]
        if bpr.get("description") != apr.get("description"):
            add(
                {
                    "type": "value_changed",
                    "entityType": "prompt",
                    "entityId": name,
                    "path": "/description",
                    "before": bpr.get("description"),
                    "after": apr.get("description"),
                }
            )

        b_args = map_by(bpr.get("arguments") or [], "name")
        a_args = map_by(apr.get("arguments") or [], "name")
        for arg in sorted(set(a_args) - set(b_args)):
            add(
                {
                    "type": "value_added",
                    "entityType": "prompt",
                    "entityId": name,
                    "path": f"/arguments/{_json_pointer_escape_token(arg)}",
                    "value": a_args[arg],
                }
            )
        for arg in sorted(set(b_args) - set(a_args)):
            add(
                {
                    "type": "value_removed",
                    "entityType": "prompt",
                    "entityId": name,
                    "path": f"/arguments/{_json_pointer_escape_token(arg)}",
                    "value": b_args[arg],
                }
            )
        for arg in sorted(set(b_args) & set(a_args)):
            ba = b_args[arg]
            aa = a_args[arg]
            for field in ("description", "required", "schema"):
                if ba.get(field) != aa.get(field):
                    add(
                        {
                            "type": "value_changed",
                            "entityType": "prompt",
                            "entityId": name,
                            "path": f"/arguments/{_json_pointer_escape_token(arg)}/{field}",
                            "before": ba.get(field),
                            "after": aa.get(field),
                        }
                    )

    # Declaration sources (identity: (sourceType, name, uri))
    def src_key(s: dict) -> tuple[str, str, str]:
        return (str(s.get("sourceType") or ""), str(s.get("name") or ""), str(s.get("uri") or ""))

    b_src_map: dict[tuple[str, str, str], dict] = {}
    for s in (b.get("declarationSources") or []):
        if isinstance(s, dict):
            b_src_map[src_key(s)] = s

    a_src_map: dict[tuple[str, str, str], dict] = {}
    for s in (a.get("declarationSources") or []):
        if isinstance(s, dict):
            a_src_map[src_key(s)] = s

    for k in sorted(set(a_src_map) - set(b_src_map)):
        add(
            {
                "type": "declaration_source_added",
                "entityType": "declaration_source",
                "entityId": "|".join(k),
                "path": "",
            }
        )
    for k in sorted(set(b_src_map) - set(a_src_map)):
        add(
            {
                "type": "declaration_source_removed",
                "entityType": "declaration_source",
                "entityId": "|".join(k),
                "path": "",
            }
        )
    for k in sorted(set(b_src_map) & set(a_src_map)):
        bs = b_src_map[k]
        a_s = a_src_map[k]
        if bs.get("extracted") != a_s.get("extracted"):
            add(
                {
                    "type": "value_changed",
                    "entityType": "declaration_source",
                    "entityId": "|".join(k),
                    "path": "/extracted",
                    "before": bs.get("extracted"),
                    "after": a_s.get("extracted"),
                }
            )

    # Manifest / capabilities (declarationSources)
    b_caps = _manifest_tool_caps_entry_map_from_surface(b)
    a_caps = _manifest_tool_caps_entry_map_from_surface(a)
    for tool in sorted(set(a_caps) - set(b_caps)):
        add({"type": "manifest_tool_added", "entityType": "manifest_tool", "entityId": tool, "path": ""})
    for tool in sorted(set(b_caps) - set(a_caps)):
        add({"type": "manifest_tool_removed", "entityType": "manifest_tool", "entityId": tool, "path": ""})
    for tool in sorted(set(b_caps) & set(a_caps)):
        be = b_caps.get(tool) or {}
        ae = a_caps.get(tool) or {}
        if be.get("description") != ae.get("description"):
            add(
                {
                    "type": "value_changed",
                    "entityType": "manifest_tool",
                    "entityId": tool,
                    "path": "/description",
                    "before": be.get("description"),
                    "after": ae.get("description"),
                }
            )

        b_ops = be.get("operations") or []
        a_ops = ae.get("operations") or []
        # Canonical form is sorted list; order changes should not appear here.
        if b_ops != a_ops:
            add(
                {
                    "type": "manifest_tool_changed",
                    "entityType": "manifest_tool",
                    "entityId": tool,
                    "path": "/operations",
                    "beforeCount": len(b_ops),
                    "afterCount": len(a_ops),
                }
            )
            try:
                bset = set(b_ops)
                aset = set(a_ops)
                for op in sorted(aset - bset):
                    add(
                        {
                            "type": "value_added",
                            "entityType": "manifest_tool",
                            "entityId": tool,
                            "path": "/operations",
                            "value": op,
                        }
                    )
                for op in sorted(bset - aset):
                    add(
                        {
                            "type": "value_removed",
                            "entityType": "manifest_tool",
                            "entityId": tool,
                            "path": "/operations",
                            "value": op,
                        }
                    )
            except TypeError:
                # Fall back to whole-list change only (still satisfies parity invariants).
                pass

    changes.sort(key=lambda r: (r.get("entityType", ""), r.get("entityId", ""), r.get("type", ""), r.get("path", "")))
    return changes


def _snapshot_comparison_metadata(snap: dict) -> dict:
    obs = snap.get("observation") if isinstance(snap, dict) else None
    if not isinstance(obs, dict):
        return {}
    cm = obs.get("comparisonMetadata")
    return cm if isinstance(cm, dict) else {}


def _snapshot_is_legacy(snap: dict) -> bool:
    cm = _snapshot_comparison_metadata(snap)
    return bool(cm.get("legacy"))


def _snapshot_has_evidence_gap(snap: dict, *, entity_type: str, path: str) -> bool:
    cm = _snapshot_comparison_metadata(snap)
    gaps = cm.get("evidenceGaps")
    if not isinstance(gaps, list):
        return False
    for g in gaps:
        if not isinstance(g, dict):
            continue
        if g.get("entityType") != entity_type:
            continue

        # Explicit per-path list.
        gpaths = g.get("paths")
        if isinstance(gpaths, list) and all(isinstance(p, str) for p in gpaths):
            if path in gpaths:
                return True

        # Regex-style matcher for semantic paths.
        pat = g.get("pathPattern")
        if isinstance(pat, str) and pat:
            try:
                if re.match(pat, path):
                    return True
            except re.error:
                # Ignore invalid patterns; treat as non-match.
                pass

        gpath = g.get("path")
        if not isinstance(gpath, str) or not gpath:
            continue
        if gpath == "*" or gpath == path:
            return True
        if gpath.endswith("/*") and path.startswith(gpath[:-1]):
            return True
    return False


def _compute_snapshot_comparison(before_snapshot: dict, after_snapshot: dict) -> dict:
    """
    Snapshot-level comparison wrapper.

    For complete-vs-complete, identityComparable is True and changes come straight from
    _compute_surface_changes().

    If either side is legacy or partial, identityComparable is False and we:
    - report limitations
    - suppress changes that are not comparable due to evidence gaps
    - emit evidenceChanges (e.g. newly observable tool schemas)
    """
    b = before_snapshot if isinstance(before_snapshot, dict) else {}
    a = after_snapshot if isinstance(after_snapshot, dict) else {}
    b_surface = b.get("surface") if isinstance(b.get("surface"), dict) else {}
    a_surface = a.get("surface") if isinstance(a.get("surface"), dict) else {}

    b_comp = b.get("surfaceCompleteness", "partial")
    a_comp = a.get("surfaceCompleteness", "partial")
    b_digest = b.get("surfaceDigest")
    a_digest = a.get("surfaceDigest")
    b_legacy = _snapshot_is_legacy(b)
    a_legacy = _snapshot_is_legacy(a)

    identity_comparable = bool(
        (b_comp == "complete")
        and (a_comp == "complete")
        and bool(b_digest)
        and bool(a_digest)
        and not b_legacy
        and not a_legacy
    )

    limitations: list[dict] = []
    if not identity_comparable:
        limitations.append(
            {
                "type": "identity_unavailable",
                "message": "Complete-surface identity comparison is unavailable (legacy and/or partial snapshot involved).",
            }
        )

    if b_legacy:
        limitations.append(
            {
                "type": "legacy_format",
                "side": "before",
                "message": "Before snapshot was converted from a legacy report format; some evidence was not captured.",
            }
        )
    if a_legacy:
        limitations.append(
            {
                "type": "legacy_format",
                "side": "after",
                "message": "After snapshot was converted from a legacy report format; some evidence was not captured.",
            }
        )

    def _coverage_limitations(snap: dict, *, side: str) -> tuple[list[dict], set[str]]:
        obs = snap.get("observation")
        if not isinstance(obs, dict):
            return [], set()
        cov = obs.get("coverage")
        if not isinstance(cov, dict):
            return [], set()
        out: list[dict] = []
        incomplete_sections: set[str] = set()
        for section in sorted(cov.keys()):
            entry = cov.get(section)
            if not isinstance(entry, dict):
                continue
            attempted = entry.get("attempted")
            completed = entry.get("completed")
            if attempted is True and completed is False:
                rule = entry.get("errorRule") or "incomplete"
                incomplete_sections.add(str(section))
                out.append(
                    {
                        "type": "coverage_incomplete",
                        "side": side,
                        "section": section,
                        "errorRule": rule,
                        "reason": rule,
                        "message": f"{side.capitalize()} snapshot did not complete {section} inspection ({rule}).",
                    }
                )
        return out, incomplete_sections

    b_incomplete_sections: set[str] = set()
    a_incomplete_sections: set[str] = set()
    if b_comp != "complete":
        lim, secs = _coverage_limitations(b, side="before")
        limitations.extend(lim)
        b_incomplete_sections |= secs
    if a_comp != "complete":
        lim, secs = _coverage_limitations(a, side="after")
        limitations.extend(lim)
        a_incomplete_sections |= secs

    # Evidence-gap limitations (known legacy format omissions).
    if _snapshot_has_evidence_gap(b, entity_type="tool", path="/inputSchema"):
        limitations.append(
            {
                "type": "evidence_gap",
                "side": "before",
                "entityType": "tool",
                "path": "/inputSchema",
                "message": "Tool input schemas were not captured by the legacy report format (before side).",
            }
        )
    if _snapshot_has_evidence_gap(a, entity_type="tool", path="/inputSchema"):
        limitations.append(
            {
                "type": "evidence_gap",
                "side": "after",
                "entityType": "tool",
                "path": "/inputSchema",
                "message": "Tool input schemas were not captured by the legacy report format (after side).",
            }
        )
    if _snapshot_has_evidence_gap(b, entity_type="resource", path="/description"):
        limitations.append(
            {
                "type": "evidence_gap",
                "side": "before",
                "entityType": "resource",
                "paths": ["/name", "/title", "/description", "/mimeType", "/annotations"],
                "message": "Resource metadata fields were not captured by the legacy report format (before side).",
            }
        )
    if _snapshot_has_evidence_gap(a, entity_type="resource", path="/description"):
        limitations.append(
            {
                "type": "evidence_gap",
                "side": "after",
                "entityType": "resource",
                "paths": ["/name", "/title", "/description", "/mimeType", "/annotations"],
                "message": "Resource metadata fields were not captured by the legacy report format (after side).",
            }
        )
    if _snapshot_has_evidence_gap(b, entity_type="resource_template", path="/description"):
        limitations.append(
            {
                "type": "evidence_gap",
                "side": "before",
                "entityType": "resource_template",
                "paths": ["/name", "/title", "/description", "/mimeType", "/annotations"],
                "message": "Resource-template metadata fields were not captured by the legacy report format (before side).",
            }
        )
    if _snapshot_has_evidence_gap(a, entity_type="resource_template", path="/description"):
        limitations.append(
            {
                "type": "evidence_gap",
                "side": "after",
                "entityType": "resource_template",
                "paths": ["/name", "/title", "/description", "/mimeType", "/annotations"],
                "message": "Resource-template metadata fields were not captured by the legacy report format (after side).",
            }
        )
    if _snapshot_has_evidence_gap(b, entity_type="prompt", path="/arguments/x/required"):
        limitations.append(
            {
                "type": "evidence_gap",
                "side": "before",
                "entityType": "prompt",
                "pathPattern": r"^/arguments/[^/]+/(description|required|schema)$",
                "message": "Prompt argument details were not captured by the legacy report format (before side).",
            }
        )
    if _snapshot_has_evidence_gap(a, entity_type="prompt", path="/arguments/x/required"):
        limitations.append(
            {
                "type": "evidence_gap",
                "side": "after",
                "entityType": "prompt",
                "pathPattern": r"^/arguments/[^/]+/(description|required|schema)$",
                "message": "Prompt argument details were not captured by the legacy report format (after side).",
            }
        )

    changes = _compute_surface_changes(b_surface, a_surface)

    # If either side did not complete inspection for a surface section, suppress changes for
    # entity types owned by that section. This prevents "unknown" from being rendered as
    # add/remove/change.
    section_to_entity_types = {
        "tools": {"tool"},
        "resources": {"resource"},
        "resourceTemplates": {"resource_template"},
        "prompts": {"prompt"},
        "manifest": {"manifest_tool"},
    }
    suppressed_entity_types: set[str] = set()
    for sec in (b_incomplete_sections | a_incomplete_sections):
        suppressed_entity_types |= section_to_entity_types.get(str(sec), set())
    if suppressed_entity_types:
        changes = [c for c in changes if c.get("entityType") not in suppressed_entity_types]

    evidence_changes: list[dict] = []
    tool_schema_gap_before = _snapshot_has_evidence_gap(b, entity_type="tool", path="/inputSchema")
    tool_schema_gap_after = _snapshot_has_evidence_gap(a, entity_type="tool", path="/inputSchema")
    if tool_schema_gap_before or tool_schema_gap_after:
        # Suppress tool inputSchema changes when one side lacks schema evidence.
        filtered: list[dict] = []
        for c in changes:
            if (
                c.get("type") == "value_changed"
                and c.get("entityType") == "tool"
                and c.get("path") == "/inputSchema"
                and (tool_schema_gap_before or tool_schema_gap_after)
            ):
                continue
            filtered.append(c)
        changes = filtered

        # Emit observability changes for tool schemas.
        b_tools = {t.get("name"): t for t in (b_surface.get("tools") or []) if isinstance(t, dict) and t.get("name")}
        a_tools = {t.get("name"): t for t in (a_surface.get("tools") or []) if isinstance(t, dict) and t.get("name")}
        common = sorted(set(b_tools) & set(a_tools))
        for name in common:
            bt = b_tools.get(name) or {}
            at = a_tools.get(name) or {}
            b_schema_present = bt.get("inputSchema") is not None
            a_schema_present = at.get("inputSchema") is not None
            if tool_schema_gap_before and a_schema_present:
                evidence_changes.append(
                    {
                        "type": "field_became_observable",
                        "entityType": "tool",
                        "entityId": str(name),
                        "path": "/inputSchema",
                        "message": "Tool input schema became observable (legacy report did not capture schemas).",
                    }
                )
            if tool_schema_gap_after and b_schema_present:
                evidence_changes.append(
                    {
                        "type": "field_became_unobservable",
                        "entityType": "tool",
                        "entityId": str(name),
                        "path": "/inputSchema",
                        "message": "Tool input schema became unobservable (legacy report did not capture schemas).",
                    }
                )

    # Suppress non-comparable change records for known evidence gaps. (This doesn't affect the current
    # text renderer directly, but keeps the comparison model honest for future machine output.)
    if _snapshot_has_evidence_gap(b, entity_type="resource", path="/description") or _snapshot_has_evidence_gap(a, entity_type="resource", path="/description"):
        changes = [c for c in changes if not (c.get("entityType") == "resource" and c.get("type") == "value_changed")]
    if _snapshot_has_evidence_gap(b, entity_type="resource_template", path="/description") or _snapshot_has_evidence_gap(a, entity_type="resource_template", path="/description"):
        changes = [c for c in changes if not (c.get("entityType") == "resource_template" and c.get("type") == "value_changed")]
    prompt_arg_details_gap = _snapshot_has_evidence_gap(b, entity_type="prompt", path="/arguments/x/required") or _snapshot_has_evidence_gap(
        a, entity_type="prompt", path="/arguments/x/required"
    )
    if prompt_arg_details_gap:
        # Only suppress nested arg-detail fields, not arg-name add/remove.
        # (value_added/value_removed at /arguments/<arg> remain comparable)
        arg_detail_pat = re.compile(r"^/arguments/[^/]+/(description|required|schema)$")
        filtered_changes: list[dict] = []
        for c in changes:
            if c.get("entityType") != "prompt":
                filtered_changes.append(c)
                continue
            p = c.get("path")
            if isinstance(p, str) and arg_detail_pat.match(p):
                continue
            filtered_changes.append(c)
        changes = filtered_changes

    evidence_changes.sort(key=lambda r: (r.get("entityType", ""), r.get("entityId", ""), r.get("type", ""), r.get("path", "")))
    limitations.sort(key=lambda r: (r.get("type", ""), r.get("side", ""), r.get("entityType", ""), r.get("path", "")))

    return {
        "identityComparable": identity_comparable,
        "limitations": limitations,
        "changes": changes,
        "evidenceChanges": evidence_changes,
    }


def diff_reports(before: dict, after: dict) -> str:
    SUPPORTED_SNAPSHOT_FORMATS = {"1"}

    def is_snapshot(d: dict) -> bool:
        return isinstance(d, dict) and "snapshotFormatVersion" in d and "surface" in d and "observation" in d

    def legacy_to_snapshot(r: dict) -> tuple[dict, str]:
        server = r.get("server") or {}
        generated_at = r.get("generatedAt") or datetime.now(timezone.utc).isoformat()
        protocol_version = server.get("protocolVersion") or "unknown"
        server_name = server.get("name") or "unknown"
        scanned = r.get("scannedCommand") or []
        status = r.get("status") or "ok"
        capabilities = r.get("capabilities") or {"tools": False, "resources": False, "prompts": False}
        notes = r.get("notes") or []
        errors = r.get("errors") or []
        local_tools = r.get("tools") or []
        risk = r.get("risk") or {}
        signals = r.get("signals") or []

        # Legacy lacks tool schemas; treat as partial.
        surface_tools = [{"name": t.get("name"), "description": t.get("description"), "inputSchema": None} for t in (local_tools or []) if isinstance(t, dict)]
        surface_resources = [{"uri": u} for u in (r.get("resources") or [])]
        surface_templates = [{"uriTemplate": u} for u in (r.get("resourceTemplates") or [])]
        legacy_prompts = []
        for p in (r.get("prompts") or []):
            if not isinstance(p, dict):
                continue
            arg_objs = []
            for a in (p.get("arguments") or []):
                arg_objs.append({"name": a})
            legacy_prompts.append({"name": p.get("name"), "description": p.get("description"), "arguments": arg_objs})
        decl_sources: list[dict] = []
        if isinstance(r.get("manifest"), list):
            decl_sources.append(
                {
                    "sourceType": "legacy",
                    "name": "mcp_manifest",
                    "uri": None,
                    "status": "parsed",
                    "extracted": {"toolCapabilities": r.get("manifest")},
                }
            )

        coverage = {
            "tools": {"declaredSupported": None, "attempted": False, "completed": False, "errorRule": "legacy"},
            "resources": {"declaredSupported": None, "attempted": False, "completed": False, "errorRule": "legacy"},
            "resourceTemplates": {"declaredSupported": None, "attempted": False, "completed": False, "errorRule": "legacy"},
            "prompts": {"declaredSupported": None, "attempted": False, "completed": False, "errorRule": "legacy"},
            "manifest": {"declaredSupported": None, "attempted": False, "completed": False, "errorRule": "legacy"},
        }
        snap = _build_snapshot(
            generated_at=str(generated_at),
            scanned_command=list(scanned) if isinstance(scanned, list) else [],
            server_name=str(server_name),
            protocol_version=str(protocol_version),
            capabilities=capabilities,
            status=str(status),
            coverage=coverage,
            surface={
                "tools": surface_tools,
                "resources": surface_resources,
                "resourceTemplates": surface_templates,
                "prompts": legacy_prompts,
                "declarationSources": decl_sources,
            },
            tools_for_text=list(local_tools) if isinstance(local_tools, list) else [],
            risk=risk,
            signals=signals,
            notes=notes,
            errors=errors,
        )
        # Add evidence-gap metadata without changing surface semantics.
        snap_obs = snap.get("observation")
        if isinstance(snap_obs, dict):
            snap_obs["comparisonMetadata"] = {
                "legacy": True,
                "evidenceGaps": [
                    {
                        "type": "field_not_captured",
                        "entityType": "tool",
                        "path": "/inputSchema",
                        "reason": "legacy_format_not_captured",
                    },
                    {
                        "type": "fields_not_captured",
                        "entityType": "resource",
                        "paths": ["/name", "/title", "/description", "/mimeType", "/annotations"],
                        "reason": "legacy_format_only_uris",
                    },
                    {
                        "type": "fields_not_captured",
                        "entityType": "resource_template",
                        "paths": ["/name", "/title", "/description", "/mimeType", "/annotations"],
                        "reason": "legacy_format_only_uri_templates",
                    },
                    {
                        "type": "fields_not_captured",
                        "entityType": "prompt",
                        "pathPattern": r"^/arguments/[^/]+/(description|required|schema)$",
                        "reason": "legacy_format_argument_details_not_captured",
                    },
                ],
            }
        # Force legacy conversion to partial regardless of coverage heuristics.
        snap["surfaceCompleteness"] = "partial"
        snap.pop("surfaceDigest", None)
        snap.pop("surfaceEntityDigests", None)
        return snap, "Legacy report: tool schemas were not captured; structural comparison is limited."

    def coerce_snapshot(d: dict) -> tuple[dict, list[str]]:
        if is_snapshot(d):
            ver = str(d.get("snapshotFormatVersion"))
            if ver not in SUPPORTED_SNAPSHOT_FORMATS:
                raise ValueError(f"Unsupported snapshotFormatVersion: {ver}")
            return d, []
        snap, w = legacy_to_snapshot(d)
        return snap, [w]

    b, bw = coerce_snapshot(before)
    a, aw = coerce_snapshot(after)
    warnings = bw + aw

    b_obs = b.get("observation") or {}
    a_obs = a.get("observation") or {}
    b_surface = b.get("surface") or {}
    a_surface = a.get("surface") or {}
    b_can = _canonicalize_surface(b_surface)
    a_can = _canonicalize_surface(a_surface)

    lines: list[str] = []
    lines.append("Diff\n")
    for w in warnings:
        lines.append(f"  WARNING: {w}")
    if warnings:
        lines.append("")

    b_name = b_obs.get("serverName", "unknown")
    a_name = a_obs.get("serverName", "unknown")
    b_comp = b.get("surfaceCompleteness", "partial")
    a_comp = a.get("surfaceCompleteness", "partial")
    lines.append(f"  Before: {b_name} (surface: {b_comp})")
    lines.append(f"  After:  {a_name} (surface: {a_comp})")

    b_digest = b.get("surfaceDigest")
    a_digest = a.get("surfaceDigest")
    if b_digest and a_digest:
        lines.append(f"\n  surfaceDigest:\n    before: {b_digest}\n    after:  {a_digest}\n")
    else:
        lines.append("")
        # No digest comparison shown unless both snapshots are complete; see identityComparable below.
    summary_insert_at = len(lines)

    comparison = _compute_snapshot_comparison(b, a)
    identity_comparable = bool(comparison.get("identityComparable"))
    limitations = comparison.get("limitations") if isinstance(comparison.get("limitations"), list) else []
    evidence_changes = comparison.get("evidenceChanges") if isinstance(comparison.get("evidenceChanges"), list) else []
    tool_schema_incomparable = any(
        isinstance(l, dict) and l.get("type") == "evidence_gap" and l.get("entityType") == "tool" and l.get("path") == "/inputSchema"
        for l in limitations
    )
    resource_meta_incomparable = any(
        isinstance(l, dict)
        and l.get("type") == "evidence_gap"
        and l.get("entityType") == "resource"
        and (l.get("path") == "*" or isinstance(l.get("paths"), list))
        for l in limitations
    )
    template_meta_incomparable = any(
        isinstance(l, dict)
        and l.get("type") == "evidence_gap"
        and l.get("entityType") == "resource_template"
        and (l.get("path") == "*" or isinstance(l.get("paths"), list))
        for l in limitations
    )
    prompt_arg_details_incomparable = any(
        isinstance(l, dict)
        and l.get("type") == "evidence_gap"
        and l.get("entityType") == "prompt"
        and (str(l.get("path")) in ("/arguments/*", "/arguments") or isinstance(l.get("pathPattern"), str))
        for l in limitations
    )
    incomplete_sections: set[str] = set(
        str(l.get("section"))
        for l in limitations
        if isinstance(l, dict) and l.get("type") == "coverage_incomplete" and l.get("section")
    )
    tools_incomparable = "tools" in incomplete_sections
    resources_incomparable = "resources" in incomplete_sections
    templates_incomparable = "resourceTemplates" in incomplete_sections
    prompts_incomparable = "prompts" in incomplete_sections
    manifest_incomparable = "manifest" in incomplete_sections

    if not identity_comparable:
        lines.append("  Complete-surface identity comparison: unavailable")
        lines.append("")

        def _format_limitations(raw: list[object]) -> list[str]:
            # Drop the redundant structured limitation; we already render the identity-unavailable line above.
            lims = [l for l in raw if isinstance(l, dict) and l.get("type") != "identity_unavailable"]
            if not lims:
                return []

            def side_label(side: object) -> str:
                return "Before" if side == "before" else ("After" if side == "after" else "Unknown")

            def base_key(l: dict) -> tuple:
                t = l.get("type")
                if t == "coverage_incomplete":
                    return (t, l.get("section"), l.get("reason"), l.get("side"))
                if t == "legacy_format":
                    return (t,)
                if t == "evidence_gap":
                    return (t, l.get("entityType"), l.get("path"), tuple(l.get("paths") or []), l.get("pathPattern"))
                return (t, json.dumps(l, sort_keys=True, ensure_ascii=False))

            grouped: dict[tuple, list[dict]] = {}
            for l in lims:
                grouped.setdefault(base_key(l), []).append(l)

            out: list[str] = []
            for k in sorted(grouped.keys(), key=lambda x: str(x)):
                items = grouped[k]
                t = items[0].get("type")
                sides = sorted({i.get("side") for i in items if i.get("side") in ("before", "after")})

                def with_sides(msg: str) -> str:
                    if sides == ["before"]:
                        return f"Before snapshot: {msg}"
                    if sides == ["after"]:
                        return f"After snapshot: {msg}"
                    if sides == ["before", "after"]:
                        return f"Both snapshots: {msg}"
                    return msg

                if t == "legacy_format":
                    out.append(with_sides("uses the legacy report format; some evidence was not captured."))
                    continue

                if t == "coverage_incomplete":
                    # Preserve side/section specificity; different failures shouldn't be collapsed.
                    i = items[0]
                    sec = i.get("section")
                    reason = i.get("reason") or i.get("errorRule") or "incomplete"
                    side = i.get("side")
                    out.append(f"{side_label(side)} snapshot did not complete {sec} inspection ({reason}).")
                    continue

                if t == "evidence_gap":
                    i = items[0]
                    et = i.get("entityType")
                    if et == "tool" and i.get("path") == "/inputSchema":
                        out.append(with_sides("tool input schemas were not captured."))
                        continue
                    if et == "resource":
                        out.append(with_sides("resource metadata were not captured."))
                        continue
                    if et == "resource_template":
                        out.append(with_sides("resource-template metadata were not captured."))
                        continue
                    if et == "prompt":
                        out.append(with_sides("prompt argument details beyond argument names were not captured."))
                        continue

                # Fallback to the existing message if present.
                msg = items[0].get("message")
                if isinstance(msg, str) and msg:
                    out.append(msg)
                else:
                    out.append(json.dumps(items[0], ensure_ascii=False))

            return out

        formatted_limitations = _format_limitations(limitations)
        if formatted_limitations:
            lines.append("  Comparison limitations:")
            for msg in formatted_limitations:
                lines.append(f"    - {msg}")
            lines.append("")

    def tool_map(surface: dict) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for t in surface.get("tools") or []:
            if isinstance(t, dict) and t.get("name"):
                out[str(t["name"])] = t
        return out

    def prompt_map(surface: dict) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for p in surface.get("prompts") or []:
            if isinstance(p, dict) and p.get("name"):
                out[str(p["name"])] = p
        return out

    def map_by(items: list[dict], key: str) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for it in items or []:
            if isinstance(it, dict) and it.get(key):
                out[str(it[key])] = it
        return out

    def diff_values(path: str, bv: Any, av: Any, out_lines: list[str], *, limit: int = 60) -> None:
        diffs: list[tuple[str, Any, Any]] = []

        def rec(p: str, x: Any, y: Any) -> None:
            if x == y:
                return
            if type(x) != type(y):
                diffs.append((p, x, y))
                return
            if isinstance(x, dict):
                keys = sorted(set(x.keys()) | set(y.keys()))
                for k in keys:
                    if k not in x:
                        diffs.append((f"{p}.{k}" if p else k, None, y.get(k)))
                    elif k not in y:
                        diffs.append((f"{p}.{k}" if p else k, x.get(k), None))
                    else:
                        rec(f"{p}.{k}" if p else k, x.get(k), y.get(k))
                return
            if isinstance(x, list):
                # Improve readability for common schema list expansions.
                if p.endswith(".enum") or p.endswith(".required"):
                    try:
                        xb = set(x)
                        yb = set(y)
                        added = sorted(yb - xb)
                        removed = sorted(xb - yb)
                        if added:
                            diffs.append((p + " (+)", added, None))
                        if removed:
                            diffs.append((p + " (-)", removed, None))
                        return
                    except TypeError:
                        pass
                diffs.append((p, x, y))
                return
            diffs.append((p, x, y))

        rec(path, bv, av)
        for i, (p, x, y) in enumerate(diffs):
            if i >= limit:
                out_lines.append(f"    … ({len(diffs) - limit} more changes)")
                break
            out_lines.append(f"    ~ {p}: {json.dumps(x, ensure_ascii=False)[:160]} -> {json.dumps(y, ensure_ascii=False)[:160]}")

    # Tools
    if not tools_incomparable:
        b_tools = tool_map(b_can)
        a_tools = tool_map(a_can)
        t_added = sorted(set(a_tools) - set(b_tools))
        t_removed = sorted(set(b_tools) - set(a_tools))
        t_common = sorted(set(b_tools) & set(a_tools))
        tool_changes: list[str] = []
        for name in t_common:
            bt = b_tools[name]
            at = a_tools[name]
            if (bt.get("description") or "") != (at.get("description") or ""):
                tool_changes.append(f"    ~ {name}.description")
            if not tool_schema_incomparable:
                if _canonical_json_bytes(bt.get("inputSchema")) != _canonical_json_bytes(at.get("inputSchema")):
                    tool_changes.append(f"    ~ {name}.inputSchema")

        if t_added or t_removed or tool_changes:
            lines.append("  Tools:")
            for n in t_added:
                lines.append(f"    + {n}")
            for n in t_removed:
                lines.append(f"    - {n}")
            # Expand per-tool structural diffs for changed tools (bounded).
            for name in t_common:
                bt = b_tools[name]
                at = a_tools[name]
                if (bt.get("description") or "") != (at.get("description") or ""):
                    lines.append(f"    ~ {name}.description: {json.dumps(bt.get('description'), ensure_ascii=False)} -> {json.dumps(at.get('description'), ensure_ascii=False)}")
                if not tool_schema_incomparable:
                    b_schema = bt.get("inputSchema")
                    a_schema = at.get("inputSchema")
                    if _canonical_json_bytes(b_schema) != _canonical_json_bytes(a_schema):
                        lines.append(f"    ~ {name}.inputSchema:")
                        diff_values(f"{name}.inputSchema", b_schema, a_schema, lines, limit=25)
            lines.append("")

    # Resources / templates
    if not resources_incomparable and not templates_incomparable:
        b_res = map_by(b_can.get("resources") or [], "uri")
        a_res = map_by(a_can.get("resources") or [], "uri")
        b_tmpl = map_by(b_can.get("resourceTemplates") or [], "uriTemplate")
        a_tmpl = map_by(a_can.get("resourceTemplates") or [], "uriTemplate")
        res_added = sorted(set(a_res) - set(b_res))
        res_removed = sorted(set(b_res) - set(a_res))
        res_common = sorted(set(b_res) & set(a_res))
        if resource_meta_incomparable:
            res_changed = []
        else:
            res_changed = [u for u in res_common if b_res[u] != a_res[u]]
        tmpl_added = sorted(set(a_tmpl) - set(b_tmpl))
        tmpl_removed = sorted(set(b_tmpl) - set(a_tmpl))
        tmpl_common = sorted(set(b_tmpl) & set(a_tmpl))
        if template_meta_incomparable:
            tmpl_changed = []
        else:
            tmpl_changed = [u for u in tmpl_common if b_tmpl[u] != a_tmpl[u]]
        if res_added or res_removed or res_changed or tmpl_added or tmpl_removed or tmpl_changed:
            lines.append("  Resources:")
            for u in res_added:
                lines.append(f"    + {u}")
            for u in res_removed:
                lines.append(f"    - {u}")
            for u in res_changed:
                lines.append(f"    ~ {u}")
            for u in tmpl_added:
                lines.append(f"    + {u}")
            for u in tmpl_removed:
                lines.append(f"    - {u}")
            for u in tmpl_changed:
                lines.append(f"    ~ {u}")
            lines.append("")

    # Prompts
    if not prompts_incomparable:
        b_prompts = prompt_map(b_can)
        a_prompts = prompt_map(a_can)
        p_added = sorted(set(a_prompts) - set(b_prompts))
        p_removed = sorted(set(b_prompts) - set(a_prompts))
        p_common = sorted(set(b_prompts) & set(a_prompts))
        p_changed: list[str] = []
        p_desc_changed: dict[str, tuple[Any, Any]] = {}
        p_args_changed: dict[str, tuple[list[str], list[str]]] = {}
        for name in p_common:
            bp = b_prompts[name]
            ap = a_prompts[name]
            if prompt_arg_details_incomparable:
                b_args = sorted([a.get("name") for a in (bp.get("arguments") or []) if isinstance(a, dict) and a.get("name")])
                a_args = sorted([a.get("name") for a in (ap.get("arguments") or []) if isinstance(a, dict) and a.get("name")])
                if bp.get("description") != ap.get("description"):
                    p_desc_changed[name] = (bp.get("description"), ap.get("description"))
                if b_args != a_args:
                    added = sorted(set(a_args) - set(b_args))
                    removed = sorted(set(b_args) - set(a_args))
                    p_args_changed[name] = (added, removed)
                if (bp.get("description") != ap.get("description")) or (b_args != a_args):
                    p_changed.append(name)
            else:
                if bp != ap:
                    if bp.get("description") != ap.get("description"):
                        p_desc_changed[name] = (bp.get("description"), ap.get("description"))
                    b_args = sorted([a.get("name") for a in (bp.get("arguments") or []) if isinstance(a, dict) and a.get("name")])
                    a_args = sorted([a.get("name") for a in (ap.get("arguments") or []) if isinstance(a, dict) and a.get("name")])
                    if b_args != a_args:
                        added = sorted(set(a_args) - set(b_args))
                        removed = sorted(set(b_args) - set(a_args))
                        p_args_changed[name] = (added, removed)
                    p_changed.append(name)
        if p_added or p_removed or p_changed:
            lines.append("  Prompts:")
            for n in p_added:
                lines.append(f"    + {n}")
            for n in p_removed:
                lines.append(f"    - {n}")
            for n in p_changed:
                rendered_any_detail = False
                if n in p_desc_changed:
                    before_desc, after_desc = p_desc_changed[n]
                    lines.append(f"    ~ {n}.description:")
                    lines.append(
                        f"        {json.dumps(before_desc, ensure_ascii=False)} -> {json.dumps(after_desc, ensure_ascii=False)}"
                    )
                    rendered_any_detail = True
                if n in p_args_changed:
                    added, removed = p_args_changed[n]
                    lines.append(f"    ~ {n}.arguments:")
                    if added:
                        lines.append(f"        added: {', '.join(added)}")
                    if removed:
                        lines.append(f"        removed: {', '.join(removed)}")
                    rendered_any_detail = True
                if not rendered_any_detail:
                    lines.append(f"    ~ {n}")
            lines.append("")

    # Manifest / action-level capability diff (from declarationSources).
    if not manifest_incomparable:
        before_caps = _manifest_tool_caps_entry_map_from_surface(b_can)
        after_caps = _manifest_tool_caps_entry_map_from_surface(a_can)
        caps_added = sorted(set(after_caps) - set(before_caps))
        caps_removed = sorted(set(before_caps) - set(after_caps))
        caps_changed: list[tuple[str, list[str], list[str]]] = []
        for name in sorted(set(before_caps) & set(after_caps)):
            be = before_caps.get(name) or {}
            ae = after_caps.get(name) or {}
            b_ops_raw = be.get("operations") or []
            a_ops_raw = ae.get("operations") or []
            try:
                b_ops = set(b_ops_raw)
                a_ops = set(a_ops_raw)
            except TypeError:
                # If operations aren't hashable, fall back to whole-list comparison.
                if b_ops_raw != a_ops_raw:
                    caps_changed.append((name, [], []))
                continue
            # If any identity-bearing manifest metadata changed, treat as a manifest change.
            if be != ae:
                ops_added = sorted(a_ops - b_ops)
                ops_removed = sorted(b_ops - a_ops)
                caps_changed.append((name, ops_added, ops_removed))

        has_caps_diff = caps_added or caps_removed or caps_changed
        if has_caps_diff:
            lines.append("  Capabilities (manifest-declared):")
            for name in caps_added:
                ops = (after_caps.get(name) or {}).get("operations")
                count = f" ({len(ops)} operations)" if ops else ""
                lines.append(f"    + {name}{count}")
            for name in caps_removed:
                ops = (before_caps.get(name) or {}).get("operations")
                count = f" ({len(ops)} operations)" if ops else ""
                lines.append(f"    - {name}{count}")
            for name, ops_added_list, ops_removed_list in caps_changed:
                b_count = len(((before_caps.get(name) or {}).get("operations") or []))
                a_count = len(((after_caps.get(name) or {}).get("operations") or []))
                parts = []
                if ops_added_list:
                    parts.append(f"added: {', '.join(ops_added_list)}")
                if ops_removed_list:
                    parts.append(f"removed: {', '.join(ops_removed_list)}")
                detail = f" ({'; '.join(parts)})" if parts else ""
                lines.append(f"    ~ {name}: {b_count} operations -> {a_count} operations{detail}")
            lines.append("")

    if evidence_changes:
        newly_obs = [e for e in evidence_changes if isinstance(e, dict) and e.get("type") == "field_became_observable"]
        newly_unobs = [e for e in evidence_changes if isinstance(e, dict) and e.get("type") == "field_became_unobservable"]
        if newly_obs:
            lines.append("  Newly observable:")
            for e in newly_obs:
                ent = e.get("entityId")
                path = e.get("path")
                if isinstance(ent, str) and path == "/inputSchema":
                    lines.append(f"    ? {ent}.inputSchema")
                else:
                    lines.append(f"    ? {json.dumps(e, ensure_ascii=False)}")
            lines.append("")
        if newly_unobs:
            lines.append("  Newly unobservable:")
            for e in newly_unobs:
                ent = e.get("entityId")
                path = e.get("path")
                if isinstance(ent, str) and path == "/inputSchema":
                    lines.append(f"    ? {ent}.inputSchema")
                else:
                    lines.append(f"    ? {json.dumps(e, ensure_ascii=False)}")
            lines.append("")

    if len(lines) <= 5 or lines[-1] != "":
        # Ensure trailing newline and a clean end.
        pass

    # If nothing changed beyond header.
    has_change_sections = any(h in lines for h in ("  Tools:", "  Resources:", "  Prompts:", "  Capabilities (manifest-declared):"))
    if identity_comparable and has_change_sections:
        lines.insert(summary_insert_at, "  Surface changed.")
        lines.insert(summary_insert_at + 1, "")
    if not has_change_sections:
        if identity_comparable:
            lines.append("  No changes detected.\n")
        else:
            lines.append("  No proven changes detected in comparable fields.\n")

    return "\n".join(lines).rstrip() + "\n"


def _report_json(report: dict) -> str:
    """Serialize a snapshot dict to a stable JSON string (for storage/output)."""
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def _build_server_env(ns: argparse.Namespace) -> tuple[dict[str, str], tempfile.TemporaryDirectory[str] | None]:
    """
    Build the environment dict and optional temp-home for the server process.

    Handles --env, --home, and --isolate-home.
    Returns (server_env, temp_home_ctx).  Caller must clean up temp_home_ctx.
    """
    server_env = dict(os.environ)
    for item in ns.env or []:
        if "=" not in item:
            raise SystemExit(f"mcp-preflight: --env must be KEY=VALUE (got {item!r})")
        k, v = item.split("=", 1)
        server_env[k] = v

    temp_home_ctx: tempfile.TemporaryDirectory[str] | None = None
    if ns.isolate_home:
        temp_home_ctx = tempfile.TemporaryDirectory(prefix="mcp-preflight-home-")
        home_dir: Path | None = Path(temp_home_ctx.name)
    elif ns.home:
        home_dir = ns.home
    else:
        home_dir = None

    if home_dir is not None:
        server_env["HOME"] = str(home_dir)
        server_env["XDG_CONFIG_HOME"] = str(home_dir / ".config")
        server_env["XDG_DATA_HOME"] = str(home_dir / ".local" / "share")
        server_env["XDG_CACHE_HOME"] = str(home_dir / ".cache")

    return server_env, temp_home_ctx


def _read_captured_stderr(errbuf: TextIO | None) -> str:
    """Read and return captured stderr content, or empty string if nothing was captured."""
    if errbuf is None:
        return ""
    errbuf.seek(0)
    return errbuf.read().strip()


def _postprocess_success(snapshot: dict, server_err: str, *, verbose: bool) -> None:
    """
    Post-process a successful inspect() snapshot using captured stderr.

    Mutates ``snapshot`` in place: merges stderr-derived notes, sets auth_gated status.
    """
    if server_err:
        notes, signals = stderr_notes(server_err)
        if notes:
            obs = snapshot.get("observation") or {}
            obs["notes"] = sorted(
                (obs.get("notes") or []) + notes,
                key=lambda n: (n.get("kind", ""), n.get("name", ""), n.get("rule", "")),
            )
            snapshot["observation"] = obs

        # Auth-gated heuristic: stderr auth hint + empty declared surface.
        if signals.get("has_auth_hint"):
            surface = snapshot.get("surface") or {}
            if (
                not surface.get("tools")
                and not surface.get("resources")
                and not surface.get("resourceTemplates")
                and not surface.get("prompts")
            ):
                obs = snapshot.get("observation") or {}
                obs["status"] = "auth_gated"
                snapshot["observation"] = obs
                # Auth-gated surfaces are incomplete; do not emit a stable digest.
                snapshot["surfaceCompleteness"] = "partial"
                snapshot.pop("surfaceDigest", None)
                snapshot.pop("surfaceEntityDigests", None)

    if verbose and server_err:
        sys.stderr.write("\n[server stderr]\n" + server_err + "\n")


def _handle_inspect_failure(
    exc: BaseException,
    *,
    server_err: str,
    command: str,
    args: list[str],
    timeout_s: float,
) -> tuple[dict, str]:
    """
    Build a failure report and user-facing error message from a failed inspect().

    Returns (report, error_message).
    """
    is_timeout = contains_timeout(exc)
    stderr_notes_list: list[dict] = []
    stderr_flags: dict = {}

    if server_err:
        stderr_notes_list, stderr_flags = stderr_notes(server_err)

        # If stderr contains a real stacktrace, it's not a timeout even if the
        # underlying I/O exception looks like cancellation/stream teardown.
        if stderr_flags.get("has_stacktrace"):
            is_timeout = False

    if stderr_flags.get("has_auth_hint"):
        status = "auth_required"
    else:
        status = "timeout" if is_timeout else "startup_error"

    stack_note = next((n for n in stderr_notes_list if n.get("rule") == "startup_stacktrace"), None)
    if is_timeout:
        err_snippet = f"Timed out after {timeout_s}s"
    elif stack_note and stack_note.get("snippet"):
        # Prefer the server's own stacktrace over anyio/TaskGroup wrapper errors.
        err_snippet = str(stack_note["snippet"])
    else:
        err_snippet = _normalize_text(str(exc))

    generated_at = datetime.now(timezone.utc).isoformat()
    coverage = {
        "tools": {"declaredSupported": None, "attempted": False, "completed": False},
        "resources": {"declaredSupported": None, "attempted": False, "completed": False},
        "resourceTemplates": {"declaredSupported": None, "attempted": False, "completed": False},
        "prompts": {"declaredSupported": None, "attempted": False, "completed": False},
        "manifest": {"declaredSupported": None, "attempted": False, "completed": False},
    }
    snapshot = _build_snapshot(
        generated_at=generated_at,
        scanned_command=[command, *args],
        server_name="unknown",
        protocol_version="unknown",
        capabilities={"tools": False, "resources": False, "prompts": False},
        status=status,
        coverage=coverage,
        surface={"tools": [], "resources": [], "resourceTemplates": [], "prompts": [], "declarationSources": []},
        tools_for_text=[],
        risk={"read": 0, "write": 0, "destructive": 0},
        signals=[],
        notes=stderr_notes_list,
        errors=[
            {
                "kind": "mcp",
                "name": "initialize",
                "rule": "timeout" if is_timeout else "error",
                "snippet": err_snippet,
            }
        ],
    )

    # Build a concise user-facing error message.
    if is_timeout:
        error_message = f"mcp-preflight: timed out after {timeout_s}s"
    elif stderr_flags.get("has_auth_hint"):
        error_message = (
            "mcp-preflight: 🔒 authentication required (the MCP server did not start without credentials)\n"
            "Hint: re-run with --verbose to see server stderr, or pass credentials via --env/--home."
        )
    elif stack_note:
        error_message = "mcp-preflight: server crashed during startup (see stderr above)"
    else:
        error_message = f"mcp-preflight: error: {_normalize_text(str(exc))}"

    return snapshot, error_message


def _write_failure_stderr(server_err: str, *, verbose: bool, has_auth_hint: bool) -> None:
    """Write appropriate stderr output for a failed inspection."""
    if not server_err:
        sys.stderr.write(
            "Hint: if the server writes logs to stdout, it can break MCP stdio. Ensure server logs go to stderr.\n"
        )
        return

    # By default, keep output clean for auth-required failures:
    # full stderr is available via --verbose.
    # For non-auth failures, print stderr by default to aid debugging.
    if verbose or not has_auth_hint:
        sys.stderr.write("\n[server stderr]\n" + server_err + "\n")


def _emit_report(report: dict, *, save_path: Path | None, as_json: bool) -> None:
    """Save and/or print the JSON snapshot."""
    if save_path:
        save_path.write_text(_report_json(report), encoding="utf-8")
    if as_json:
        sys.stdout.write(_report_json(report))


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: mcp-preflight "uv run server.py"')
        print('  mcp-preflight "npx my-mcp-server"')
        print('  mcp-preflight "python /path/to/server.py"')
        print("  mcp-preflight diff before.json after.json")
        sys.exit(1)

    if sys.argv[1] == "diff":
        parser = argparse.ArgumentParser(prog="mcp-preflight diff", add_help=True)
        parser.add_argument("before", type=Path)
        parser.add_argument("after", type=Path)
        ns = parser.parse_args(sys.argv[2:])

        try:
            before = json.loads(ns.before.read_text(encoding="utf-8"))
            after = json.loads(ns.after.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            sys.stderr.write(f"mcp-preflight diff: error: invalid JSON ({e})\n")
            raise SystemExit(2)

        try:
            sys.stdout.write(diff_reports(before, after))
        except ValueError as e:
            # User-facing failures (unsupported snapshot format/version, etc.) should not print a traceback.
            sys.stderr.write(f"mcp-preflight diff: error: {e}\n")
            raise SystemExit(2)
        return

    if sys.argv[1] == "check":
        parser = argparse.ArgumentParser(prog="mcp-preflight check", add_help=True)
        parser.add_argument("--json", action="store_true", dest="as_json", help="Print the check result as JSON")
        parser.add_argument("--save", type=Path, help="Save the live snapshot (current) to a file")
        parser.add_argument("--timeout", type=float, default=10.0, help="Timeout (seconds) for MCP calls (default: 10)")
        parser.add_argument("--no-signals", action="store_true", help="Disable heuristic signal scanning/output")
        parser.add_argument(
            "--env",
            action="append",
            default=[],
            help="Add/override an environment variable for the server (repeatable, KEY=VALUE)",
        )
        parser.add_argument("--cwd", type=Path, help="Working directory for the server process")
        parser.add_argument(
            "--home",
            type=Path,
            help="Set HOME for the server (also sets XDG_* dirs); equivalent to --env HOME=... with extras",
        )
        parser.add_argument(
            "--isolate-home",
            action="store_true",
            help="Run server with HOME (and XDG_* dirs) set to a temporary directory",
        )
        vgroup = parser.add_mutually_exclusive_group()
        vgroup.add_argument("--quiet", action="store_true", help="Suppress server stderr (even on failure)")
        vgroup.add_argument("--verbose", action="store_true", help="Print server stderr (even on success)")
        parser.add_argument("baseline", type=Path, help="Baseline snapshot JSON (must be a complete versioned snapshot)")
        parser.add_argument("command", nargs=argparse.REMAINDER, help="Server command (quoted or split)")
        ns = parser.parse_args(sys.argv[2:])

        # Load and validate baseline.
        try:
            baseline_text = ns.baseline.read_text(encoding="utf-8")
        except OSError as e:
            sys.stderr.write(f"mcp-preflight check: error: could not read baseline ({e})\n")
            raise SystemExit(4)

        try:
            baseline_raw = json.loads(baseline_text)
        except json.JSONDecodeError as e:
            sys.stderr.write(f"mcp-preflight check: error: invalid baseline JSON ({e})\n")
            raise SystemExit(4)

        if not (isinstance(baseline_raw, dict) and baseline_raw.get("snapshotFormatVersion")):
            sys.stderr.write("mcp-preflight check: error: baseline must be a versioned snapshot (legacy reports are not supported)\n")
            raise SystemExit(4)
        ver = str(baseline_raw.get("snapshotFormatVersion"))
        if ver != "1":
            sys.stderr.write(f"mcp-preflight check: error: Unsupported snapshotFormatVersion: {ver}\n")
            raise SystemExit(4)
        if str(baseline_raw.get("surfaceCompleteness")) != "complete" or not baseline_raw.get("surfaceDigest"):
            sys.stderr.write("mcp-preflight check: error: baseline must be a complete snapshot with surfaceDigest\n")
            raise SystemExit(4)

        if not ns.command:
            sys.stderr.write("mcp-preflight check: error: missing server command\n")
            raise SystemExit(2)

        # Accept a single quoted command string or split args.
        if len(ns.command) == 1:
            parts = shlex.split(ns.command[0])
        else:
            parts = ns.command
        if not parts:
            sys.stderr.write("mcp-preflight check: error: missing server command\n")
            raise SystemExit(2)

        command = parts[0]
        args = parts[1:]

        server_env, temp_home_ctx = _build_server_env(ns)

        errlog: TextIO
        errbuf: TextIO | None = None
        if ns.quiet:
            errlog = open(os.devnull, "w")
        else:
            errbuf = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
            errlog = errbuf

        current: dict | None = None
        try:
            current = asyncio.run(
                inspect(
                    command,
                    args,
                    timeout_s=ns.timeout,
                    errlog=errlog,
                    env=server_env,
                    cwd=ns.cwd,
                    include_signals=not ns.no_signals,
                )
            )

            server_err = _read_captured_stderr(errbuf)
            _postprocess_success(current, server_err, verbose=ns.verbose)
        except BaseException as e:
            server_err = _read_captured_stderr(errbuf)
            _, stderr_flags = stderr_notes(server_err) if server_err else ([], {})
            _write_failure_stderr(
                server_err, verbose=ns.verbose, has_auth_hint=stderr_flags.get("has_auth_hint", False)
            )
            current, error_message = _handle_inspect_failure(
                e, server_err=server_err, command=command, args=args, timeout_s=ns.timeout
            )
            sys.stderr.write(error_message + "\n")
        finally:
            try:
                errlog.close()
            except Exception:
                pass
            try:
                if temp_home_ctx is not None:
                    temp_home_ctx.cleanup()
            except Exception:
                pass

        assert isinstance(current, dict)
        if ns.save:
            ns.save.write_text(_report_json(current), encoding="utf-8")

        baseline_digest = str(baseline_raw.get("surfaceDigest"))
        current_obs = current.get("observation") if isinstance(current.get("observation"), dict) else {}
        current_status = str((current_obs or {}).get("status") or "")
        current_digest = current.get("surfaceDigest")
        current_complete = (str(current.get("surfaceCompleteness")) == "complete") and bool(current_digest)

        identity_comparable = current_complete and current_status == "ok"
        changed = False
        exit_code = 0
        if identity_comparable:
            changed = (str(current_digest) != baseline_digest)
            exit_code = 1 if changed else 0
        else:
            # Non-ok statuses are inspection failures (2), while "partial" is incomparable (3).
            if current_status == "partial":
                exit_code = 3
            else:
                exit_code = 2

        if ns.as_json:
            result = {
                "baseline": {"path": str(ns.baseline), "surfaceDigest": baseline_digest},
                "current": {
                    "surfaceDigest": current_digest,
                    "surfaceCompleteness": current.get("surfaceCompleteness"),
                    "status": (current_obs or {}).get("status"),
                },
                "identityComparable": identity_comparable,
                "changed": changed if identity_comparable else None,
                "exitCode": exit_code,
            }
            if identity_comparable:
                result["changes"] = _compute_surface_changes(baseline_raw.get("surface") or {}, current.get("surface") or {})
            else:
                result["comparison"] = _compute_snapshot_comparison(baseline_raw, current)
            sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(diff_reports(baseline_raw, current))

        raise SystemExit(exit_code)

    parser = argparse.ArgumentParser(
        prog="mcp-preflight",
        add_help=True,
        description="Inspect, fingerprint, and diff an MCP server’s exposed capabilities.",
        epilog=(
            "Note: this starts the server process locally and does not sandbox it. "
            "Preflight does not invoke declared tools."
        ),
    )
    parser.add_argument("--version", action="version", version=f"mcp-preflight {__version__}")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Print the versioned snapshot as JSON")
    parser.add_argument("--save", type=Path, help="Save the versioned snapshot to a file")
    parser.add_argument("--timeout", type=float, default=10.0, help="Timeout (seconds) for MCP calls (default: 10)")
    parser.add_argument("--no-signals", action="store_true", help="Disable heuristic signal scanning/output")
    parser.add_argument(
        "--env",
        action="append",
        default=[],
        help="Add/override an environment variable for the server (repeatable, KEY=VALUE)",
    )
    parser.add_argument("--cwd", type=Path, help="Working directory for the server process")
    parser.add_argument(
        "--home",
        type=Path,
        help="Set HOME for the server (also sets XDG_* dirs); equivalent to --env HOME=... with extras",
    )
    parser.add_argument(
        "--isolate-home",
        action="store_true",
        help="Run server with HOME (and XDG_* dirs) set to a temporary directory",
    )
    vgroup = parser.add_mutually_exclusive_group()
    vgroup.add_argument("--quiet", action="store_true", help="Suppress server stderr (even on failure)")
    vgroup.add_argument("--verbose", action="store_true", help="Print server stderr (even on success)")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Server command (quoted or split)")
    ns = parser.parse_args(sys.argv[1:])

    if not ns.command:
        print('Usage: mcp-preflight "uv run server.py"')
        sys.exit(1)

    # Accept a single quoted command string (e.g. "uv run server.py") or split args (e.g. uv run server.py).
    if len(ns.command) == 1:
        parts = shlex.split(ns.command[0])
    else:
        parts = ns.command

    if not parts:
        print('Usage: mcp-preflight "uv run server.py"')
        sys.exit(1)

    command = parts[0]
    args = parts[1:]

    server_env, temp_home_ctx = _build_server_env(ns)

    errlog: TextIO
    errbuf: TextIO | None = None
    if ns.quiet:
        errlog = open(os.devnull, "w")
    else:
        errbuf = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
        errlog = errbuf

    try:
        report = asyncio.run(
            inspect(
                command,
                args,
                timeout_s=ns.timeout,
                errlog=errlog,
                env=server_env,
                cwd=ns.cwd,
                include_signals=not ns.no_signals,
            )
        )

        server_err = _read_captured_stderr(errbuf)
        _postprocess_success(report, server_err, verbose=ns.verbose)

        if not ns.as_json:
            print_text_report(report)
    except BaseException as e:
        server_err = _read_captured_stderr(errbuf)
        _, stderr_flags = stderr_notes(server_err) if server_err else ([], {})
        _write_failure_stderr(
            server_err, verbose=ns.verbose, has_auth_hint=stderr_flags.get("has_auth_hint", False)
        )

        report, error_message = _handle_inspect_failure(
            e, server_err=server_err, command=command, args=args, timeout_s=ns.timeout
        )
        _emit_report(report, save_path=ns.save, as_json=ns.as_json)
        sys.stderr.write(error_message + "\n")
        raise SystemExit(1)
    finally:
        try:
            errlog.close()
        except Exception:
            pass
        try:
            if temp_home_ctx is not None:
                temp_home_ctx.cleanup()
        except Exception:
            pass

    _emit_report(report, save_path=ns.save, as_json=ns.as_json)
    # For workflow/CI usage: emit a nonzero exit code for non-ok observations, while still
    # producing a snapshot JSON on stdout/--save.
    obs_status = None
    if isinstance(report, dict):
        obs = report.get("observation")
        if isinstance(obs, dict):
            obs_status = obs.get("status")
    if str(obs_status or "") != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()