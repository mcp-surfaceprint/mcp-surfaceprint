Date: Feb 26, 2026

## Why this doc exists

This document exists to help me map the MCP inspection space and clarify where [mcp-surfaceprint](https://github.com/mcp-surfaceprint/mcp-surfaceprint) should (and should not) evolve.

MCP makes it easy to connect agents to tools, but it does not provide a durable way to reason about how a server’s declared capabilities change over time. While exploring this, I ran a set of small, controlled experiments to understand what the protocol exposes today, what declaration frameworks improve, and what remains missing.

The goal here is not to propose policy, enforcement, or runtime controls.

It’s to identify whether there is a missing inspection primitive in the MCP ecosystem, and if so, what shape it should have.

### 1\. The problem

MCP exposes a server’s current declared surface, but does not itself define durable history, stable snapshot identity, or structural comparison across points in time. It tells you what a server *declares* it can do at the time of inspection, but it has no memory of what it could do yesterday, last week, or last month.

As a result, today’s ecosystem answers questions about current state and execution, but leaves a set of inspection questions unanswered:

* What did the server declare last time?  
* What does it declare now?  
* What specifically changed?  
* Can I produce durable evidence of what changed between two declared surfaces?

This is not about safety or enforcement; it’s about losing memory. 

While individuals can try to track this manually, there’s no shared or protocol-native way to treat a *declared capability surface* as a stable, versioned object over time.

### 2\. The landscape: 5 dimensions of MCP systems

To articulate this gap, we have to distinguish between different questions. Solving one does not solve the others.

| Layer | Questions it answers | Current tooling | Notes |
| :---- | :---- | :---- | :---- |
| **Declaration** | What capabilities exist? How are actions structured?What’s behind a tool’s name?  | MCP protocol, Declaration frameworks (mcp-fusion) | Declaration frameworks significantly improve the clarity and structure of declared surface, but do not provide durability or   continuity over time.  |
| **Inspection** | What changed since last time?Is the surface durable over time? | **\[THE GAP\]** | No protocol-native snapshot, diff, or stable surface identity. |
| **Governance** | Is this surface approved? | Registries, approval workflows | Approval is typically one-time or version-based, not tied to a stable declared surface snapshot.  |
| **Runtime** | Is this specific call allowed? | Gateways, Mcp-use, Cursor, other clients/execution controls? | Controls execution at call time; consumes current state but does not reason about past vs present surfaces. |
| **Observability**  | What happened / why? | Logs, traces, audit events | Describes executed behavior after the fact, not declared capability surfaces. |

Each layer answers a different question.

### 3\. What the experiments imply about inspection

Across vanilla MCP and MCP Fusion, the experiments show the same pattern:

| Mutation type | MCP Core Protocol | Declaration Frameworks (mcp-fusion) | Still missing |
| ----- | ----- | ----- | ----- |
| Add tool at runtime | ❌ | ✅ (manifest) | Durable snapshot / diff |
| Expand schema under same tool | ❌ | ✅ (manifest) | Continuity proof |
| Expand consolidated action enum | ❌ | ✅ (manifest) | Reviewer-visible diff |
| Behavior drift (no declaration change) | ❌ | ❌ | Out of scope |
| Restart / context change | ❌ | ❌ | Surface identity |

**Evidence (reproducible experiments)** https://github.com/jordanstarrk/mcp-visibility-gap-demo

MCP Fusion makes declared capability surfaces more explicit and machine-readable, but does not make them durable over time.

### 4\. Who cares?

This gap does not matter for every use case. It becomes critical in environments where trust but verify is the standard:

* **Dependency installation** You didn’t write the server, you upgraded a package. Did capabilities quietly expand?

* **Shared agent setups** One server powers multiple agents or teams. A change declaration affects everyone simultaneously.

* **Regulated or audited environments (e.g. EU AI Act)** When systems require traceability of capabilities and change control over time, one-time approval of a live-declared surface is insufficient.

* **Teams using richer declaration frameworks** (e.g. MCP Fusion). As capability surfaces become more expressive and legible, it becomes more important to know whether that surface has changed since it was last reviewed. 


### 5\. Definitions: ‘declared surface’

### 

### **Declared surface**

### Anything MCP introspection exposes that describes what a server says it can do: tool names, descriptions, schemas, actions, resources, prompts.

In practice, this surface may be exposed via:

* tools/list  
* resources/read (e.g. dynamic manifests)  
* framework-specific introspection

**Declared surface fingerprint (proposed)**  
A hash or signed snapshot of the surface at a point in time. This is informational, not authoritative. A way to reference and compare surfaces, not to enforce trust. 

**Clarifications:**

* This is not runtime behavior  
* This is not what actually executed  
* This is what the server declares it can do

###  6\. Inspection requirements (minimal)

From these experiments, an inspection layer must be able to:

1. **Snapshot declared surfaces.** Capture what a server declares at time T, not just query live state.  
2. **Diff surfaces structurally.** Detect tool additions, schema expansion, and action-level changes — even under the same tool name.  
3. **Reference declaration sources.** Treat tools/list, resources/read (manifests), and framework introspection as a single surface.  
4. **Record inspection context.** Auth state, startup configuration, and environment affect what is declared.  
5. **Detect surface mutability.** Distinguish stable surfaces from runtime-mutating ones.

These are inspection properties, not enforcement, policy, or runtime control. 

### 7\. The gap → governance tools are missing an MCP primitive

The gap is declared surface identity, history, and change visibility

Even with rich, protocol-native manifests, governance systems lack a stable object they can reference over time. Once time has passed, they cannot reliably determine whether a previously reviewed declared surface is still the same.

Inspection is the mechanism that turns declaration into something governance can reason about. Without a durable notion of “declared surface at time T”, governance systems have nothing stable to anchor approval or re-review decisions.

Current MCP governance efforts help, but do not close this gap:

* inventory ≠ capability diff  
* runtime ≠ declared surface history  
* version pinning ≠ schema-level expansion  
* CI scans ≠ protocol-native declaration tracking