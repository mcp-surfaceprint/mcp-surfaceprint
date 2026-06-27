# mcp-preflight — Principles

`mcp-preflight` provides **pre-trust visibility** into MCP servers.

It is a small inspection tool, not a safety system, policy engine, or governance layer.  
These principles describe what the tool is for, where it stops, and how scope decisions are made.

---
## TLDR Principles

- Preflight provides pre-trust visibility, not enforcement or guarantees
- Declared surfaces are preferred over inferred behavior
- Preflight avoids tool execution; introspection still runs server code
- Incomplete but honest is better than complete but misleading
- Change visibility matters more than static completeness


## Core Intent

- Reduce accidental trust in MCP servers by making capability surfaces visible **before an LLM connects**.
- Show **what could happen**, not what will happen.
- Optimize for **clarity, honesty, and diffability**, not completeness or guarantees.
- Stay useful as servers grow and compress more behavior behind abstractions.

---

## Hard Boundaries (Non-Goals)

`mcp-preflight` does **not** aim to be:

- A security scanner or vulnerability detector
- A sandbox, VM, or execution environment
- A runtime guardrail or approval system
- A policy or intent interpreter
- A trust badge, certification, or safety authority

If a feature request points in any of these directions, it is out of scope by default.

---

## Inspection Philosophy

### Visibility over enforcement
Preflight shows what is exposed; it does not restrict or approve behavior.  
Any feature that blocks, permits, or decides what actions are allowed is out of scope.

### No side effects by default
Preflight should not execute tools or change state.

Inspection must be possible without affecting:
- server state
- external systems
- user data

Anything that requires execution belongs in a different class of tool.

### Prefer observable over inferred
Prefer:
- explicit MCP introspection
- server-declared metadata
- static artifacts

Rather than relying on:
- heuristics
- pattern matching
- “best guess” logic

If inference is used, it should be clearly labeled as **best-effort and incomplete**.

### Incomplete but honest > complete but misleading
Preflight should not imply full coverage when blind spots exist.

Examples include:
- tools that hide many actions behind parameters
- unbounded or free-form inputs
- behavior hidden behind runtime logic

These limits should be surfaced, not smoothed over.

### One tool ≠ one capability
MCP tool boundaries do not necessarily map to real capability boundaries.

At scale, servers will:
- group many actions behind domain tools
- expose different actions via parameters
- change behavior without changing tool counts

Preflight is built with this mismatch in mind.

---

## Capability Model

Preflight focuses on **capabilities**, not behavior or intent.

A capability answers one question:

> *What actions become possible if an LLM can call this server?*

Policy, permissions, intent, and enforcement are intentionally out of scope.

---

## Change Awareness

Seeing how capabilities **change over time** matters as much as listing them.

New, removed, or expanded capabilities are often more important than static snapshots.  

---

## How to Treat Preflight Output

- Server-declared metadata may be shown, but should not be treated as trusted or verified.
- Preflight does not claim correctness, safety, or completeness.
- The tool does not speak with authority about server behavior.

Preflight is a **lens**, not a judge.

---

## Simple Check

Before adding a feature, ask:

> **Does this help someone see or track capabilities without executing code or deciding what should happen?**

If not, it probably does not belong in `mcp-preflight`.

---

## Long Term

Preflight should stay:
- boring
- predictable
- honest
- composable
