# Future Distributed Compute and Storage Design Principles

## Purpose

This project is currently designed to run well on a single machine with a local SEC mirror, local derived artifacts, and local runtime orchestration. That is the right level of complexity today.

This document exists to guide development so that future adoption of distributed compute, remote storage, archival tiering, or multi-worker execution is easier and less painful. It is intentionally forward-looking, but it is **not** a commitment to implement distributed infrastructure now.

The goal is:

- keep the current local-first design simple,
- preserve strong operator ergonomics,
- and avoid decisions that make later scaling unnecessarily difficult.

---

## Current posture

The project should remain:

- **local-first**
- **filesystem-native**
- **operator-friendly**
- **single-node by default**

Future distributed adoption should be treated as an **evolution of the same contracts**, not a rewrite of the system.

---

## Core design principles

### 1. Stable canonical storage contracts

Canonical filing paths, derived artifact paths, and normalized refdata paths should remain explicit and predictable.

Examples of why this matters:

- local files can later map to object-store keys,
- local mirrors can later become worker-local caches,
- archival/compression tiers can later be added without changing higher-level semantics.

Preferred pattern:

- treat canonical paths as durable identifiers,
- avoid scattering ad hoc path derivation logic,
- keep path construction centralized and deterministic.

---

### 2. Separate durable state from derived state

The project should distinguish clearly between:

#### Durable state
- downloaded filings
- normalized reference inputs
- event logs / append-oriented activity records
- operator-visible runtime state where appropriate

#### Derived state
- lookup artifacts
- query-optimized indexes
- summaries
- caches that can be recomputed

Why this matters:

- derived state can be rebuilt locally or on another machine,
- durable state forms the system-of-record substrate,
- recovery and migration become much easier.

Rule of thumb:

- if something can be deterministically recomputed, prefer to treat it as derived.

---

### 3. Idempotent pipeline stages

Major operations should remain safe to rerun.

Important examples:

- index refresh
- lookup refresh
- monitor poll
- monitor loop iteration
- reconciliation run
- extraction steps
- filing-party persistence steps

Why this matters:

- idempotent steps are easier to retry,
- retryable work is easier to distribute,
- resumability becomes practical without complicated coordination.

Preferred behavior:

- rerunning a stage should converge toward the same result,
- repeated runs should not create uncontrolled duplication,
- partial completion should be recoverable.

---

### 4. Explicit step boundaries

Each major workflow should have clear input/output boundaries.

Examples:

- **monitor poll**
  - inputs: feed state, config, local mirror state
  - outputs: warmed filings, monitor events, seen-state updates, optional lookup updates

- **lookup refresh**
  - inputs: merged index, local mirror, extracted artifacts, filing-party records
  - outputs: lookup parquet artifacts

- **reconciliation**
  - inputs: feed candidates, merged index, local presence
  - outputs: discrepancy artifacts, reconciliation events, optional catch-up side effects

This matters because explicit boundaries make it easier later to:
- queue work,
- shard work,
- run work on another host,
- or reason about failures.

---

### 5. Append-oriented event recording

Where practical, operational activity should be represented as events first and summarized second.

Examples:
- monitor activity events
- reconciliation events
- warm attempts / outcomes
- skip reasons
- fallback decisions

Why this matters:

- events are durable and auditable,
- summaries can be recomputed,
- distributed systems work better when state evolution is observable and append-oriented.

This does **not** mean everything must become event-sourced. It means event logging should remain a first-class diagnostic and reconstruction tool.

---

### 6. Local cache as a tier, not a permanent assumption

The current local SEC mirror is valuable and should remain the default hot path.

But conceptually, it should be treated as a **cache/storage tier**, not as the only possible future storage location.

Future-compatible interpretation:

- today: local mirror under `.sec_cache/Archives/...`
- later: local hot cache backed by compressed cold storage
- later: local hot cache backed by object storage
- later: worker-local cache backed by shared remote durable storage

Development implication:

- business logic should depend on stable filing identity and presence semantics,
- not on the assumption that one specific local directory is the only storage model forever.

---

### 7. Compression and archival should be tiering concerns

Compression is likely useful later, but should be treated as a storage-tier policy, not as a fundamental identity change.

Preferred future pattern:

- canonical filing identity stays the same,
- hot working copy can remain plain/raw when operationally useful,
- colder tiers may use compression such as Zstandard,
- rehydration or direct compressed reads can be added later.

This helps avoid mixing:
- operator semantics,
- file identity,
- and archival policy.

---

### 8. Narrow coordination semantics

Single-instance locking and runtime coordination should remain narrow and operational.

Examples:
- monitor loop lock files
- service-runtime process coordination
- per-run execution guards

Avoid spreading coordination assumptions deep into domain logic.

Why this matters:

- single-node operation remains simple,
- later migration to distributed schedulers or queue-based workers is easier,
- lock semantics can evolve independently of business rules.

---

### 9. Prefer interfaces over hidden locality

Core logic should remain capable of being expressed in terms of simple interfaces such as:

- fetch filing
- persist filing
- check local presence
- enumerate extracted artifacts
- build lookup from observable local state

The current implementation can absolutely stay filesystem-backed, but preserving conceptual interface boundaries reduces future migration pain.

This does **not** require premature abstraction everywhere. It means avoiding unnecessary hard-coding of hidden assumptions.

---

### 10. Operator clarity remains a first-class requirement

Any future distributed/storage evolution must preserve the project’s operator-friendly nature.

That includes:

- clear progress reporting
- explicit skip/fallback reasons
- readable runtime artifacts
- deterministic file and artifact placement
- clean local debugging paths

Scaling should not come at the cost of losing debuggability.

---

## What this means in practice today

These principles suggest the following current development preferences:

### Prefer
- canonical path construction in one place
- resumable and idempotent job design
- explicit input/output artifacts
- append-style event records with rebuildable summaries
- local-first implementation with future tiering awareness
- derived lookup/index artifacts that can be regenerated

### Avoid
- hidden reliance on mutable in-memory global state
- tightly coupling business logic to one machine’s exact directory assumptions
- irreversible storage choices in hot paths without clear contracts
- mixing archival policy with filing identity
- deep entanglement between orchestration concerns and domain logic

---

## Non-goals

This document does **not** mean the project should immediately add:

- distributed schedulers
- queues
- object storage
- multi-node locks
- cluster orchestration
- database-first redesign
- microservices decomposition

The project should continue optimizing for the current single-node, operator-friendly workflow unless and until scale or operational needs justify more.

---

## Near-term implications

The most useful near-term application of these principles is:

1. preserve canonical storage contracts,
2. keep lookup/reconciliation/monitor steps idempotent,
3. treat lookup artifacts as rebuildable derived state,
4. keep telemetry explicit and operator-readable,
5. design compression/archival as future storage-tier policy,
6. avoid introducing new hidden local assumptions.

---

## Future trigger points

A stronger distributed or tiered-storage design becomes worth pursuing when one or more of these becomes true:

- local disk pressure becomes persistent and material,
- lookup refresh or reconciliation becomes too slow for a single node,
- monitor cadence requires parallel workers,
- extraction throughput becomes a bottleneck,
- operators need shared access across machines,
- backup/transfer/replication needs become operationally significant.

Until then, the right strategy is to remain simple while preserving clean evolution paths.

---

## Guiding statement

Build for today’s local-first workflow, but preserve the contracts that make tomorrow’s distributed storage and compute adoption straightforward.