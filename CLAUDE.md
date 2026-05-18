
## Current Task: Architecture Checkpoint

This project now focuses on translating the completed DDD design into a concrete microservices-oriented architecture.

--- Start task description

# Architecture Checkpoint Assignment Instructions

## 1) Context (must be included in your analysis)

### UnoArena: Global Real-Time Uno Platform & Massive Tournaments

**Summary (for orientation):** Build the backend for a highly competitive Uno platform that supports ad-hoc rooms (2–10 players) and massive elimination tournaments (**up to 1,000,000 players**). A **core engineering challenge** is the **first-round surge of over 100,000 simultaneous matches**—a coordinated **round kickoff** where on the order of **100k rooms can transition to in-progress within seconds**, not merely "large tournament" load spread over time or slow bracket eventual consistency. Design explicitly for that spike (see §6.5). The same document covers server-authoritative RNG and game logs, strict concurrency on room actions, real-time updates with spectator privacy, disconnection and forfeit policies, tournament round progression, security and rate limiting, analytics/read models, and ranking semantics consistent with the prior design work.

The architecture must be **traceable** to the bounded contexts, commands, events, and consistency decisions produced in the Design Checkpoint (concrete expectations in §2).

## 2) Assignment objective

Translate the **domain design** into a **concrete microservices-oriented architecture** for UnoArena: for each bounded context, specify deployable services, their responsibilities, **public interfaces** (APIs and/or messaging contracts), **inter-service communication patterns**, and **persistence** choices.

This checkpoint is about **solution architecture** (services, boundaries, integration, data ownership), not full implementation. Justify how the architecture preserves domain invariants, scales under the stated load assumptions, and handles failure modes already analyzed at the domain level.

**Traceability** to the Design Checkpoint is **not** a vibe check: public async contracts (topic/queue names, event types, payload ownership) must **match** documented **domain events**—or **state the delta** (rename, split, merge) and record it in CHANGELOG-design.md (§6.2). Synchronous APIs (resources, RPCs, main operations) must **map** to the **command** (and query) catalog, or document the delta. A reviewer should be able to trace each integration row (§6.3) to a named command or event in the design package.

**Invariants that must have an explicit architectural home:**
- **Sequence-number enforcement** — where stale or replayed commands/events are rejected (service and layer).
- **Log-before-broadcast atomicity** — authoritative writes persisted before clients see updates (e.g., outbox, transactional boundary).
- **5-second Uno! challenge window** — timer ownership, expiry handling, and failure behavior.
- **60-second reconnection window** — how the window is tracked, persisted, and honored across process or node failure.
- **Single-active-session** — how **live** SSE/WebSocket connections for the old session are **terminated or forced to re-auth** via a **push-invalidation path** (Identity/Session → gateway/BFF/control channel), not only a database flag the client never reads.
- **Spectator projection** — spectators **never** receive hand data; where projection, APIs, or transport enforce the filter.
- **Match series coordination** — which component **persists tournament match state across individual games** (Bo3 scoreline, starting the next game, early termination at two wins, series winner); how room/game completion events flow from Room Gameplay into match outcome tracking and what starts the subsequent game.
- **Abandoned-game vs. completed-game outcomes (Elo and tournaments)** — which component **detects** abandonment vs. normal completion; how tournament forfeits are recorded as losses; how abandoned casual games exclude Elo updates; and how that distinction is carried in events into the Ranking context.

**Also align with the Design Checkpoint non-negotiable rubric** for Elo scope (no tournament or abandoned casual games), tournament advancement (top three, series, tie-break), and consistent match vs. game terminology in interfaces and events.

## 3) Relationship to the Design Checkpoint

- The submission must include the **latest version of the design** (glossary, contexts, aggregates, commands/events, flows, edge cases, consistency strategy, open questions) as it exists after any updates made to align with the architecture.
- If bounded context boundaries, aggregates, or events change to fit the architecture, design documents must be **updated** accordingly with a brief **delta explanation** (what changed and why).
- If the design and architecture diverge without documented rationale, the submission is incomplete.

## 4) Scope and constraints

- **In scope:** Service decomposition per context, interface definitions, sync/async integration, data stores per context, cross-cutting concerns at an architectural level (auth boundaries, idempotency, observability hooks), and diagrams that explain runtime behavior.
- **Out of scope:** Exact cloud SKUs, instance-family shopping lists, full CI/CD pipelines, line-by-line framework configuration, or production runbooks. **In scope:** naming representative technologies (e.g. PostgreSQL, Kafka, Redis) whenever they clarify persistence, messaging, or caching.
- **Client protocol:** Must name and justify the **client connection model** (e.g. REST + SSE, WebSocket, hybrid) and how it lands on a **gateway or BFF**. Hand-wavy "clients use HTTP" with no realtime story is insufficient.

## 5) Mandatory methodology

Use **clear architectural views**:

- **Context view:** Context map aligned to services (which logical context maps to which deployable components).
- **Container view:** Major runnable components (services, gateways, workers, brokers) and trust boundaries.
- **Integration view:** For each pair of components that communicate, state the pattern.

EventStorming or domain narratives from the design checkpoint should be **referenced** when explaining critical flows.

## 6) Required deliverables

### 6.1 Architecture of every bounded context

For **each** bounded context:

1. **Purpose and scope** — What this context owns; what it does not own.
2. **Services (containers)** — Name each and state its primary responsibility.
3. **Public interfaces**
   - **Synchronous:** REST/GraphQL/gRPC — list main resources or RPCs, auth expectations, versioning.
   - **Asynchronous:** topics/queues, event names, payload ownership, idempotency keys/correlation identifiers.
   - **Internal-only** interfaces — clearly marked.
4. **Dependencies on other contexts** — Upstream/downstream relationships, anti-corruption layers.

**Room Gameplay** must spell out how **log-before-broadcast** is satisfied (every authoritative state change durably appended to the immutable game log before any broadcast). Name the mechanism (transactional outbox, event-sourced command handling, etc.). Include a **mandatory intra-context sequence diagram** for a hot path (play card, draw, or shuffle) showing log-before-broadcast end-to-end.

**Domain timers** (5-second Uno! challenge window, 60-second reconnection window) must document: which component schedules and owns the timeout, what happens if that node dies mid-window, and how timeout side effects are idempotent.

**Single-active-session** must document what happens beyond revoking the token in storage: **how the system reaches the gateway/BFF/realtime edge** holding previous session's long-lived connections so those streams are closed, errored, or unsubscribed promptly.

**Tournament Orchestration** must architect the **round kickoff for the first-round surge**: what component fans out room creation or match assignment for ~100k rooms; how partial failures are handled (retry, compensate, dead-letter, idempotent room creation); thundering-herd controls (sharded workers, rate-limited enqueue, staged rollout, backpressure).

**Analytics/read models** must address the **game.completed spike at round end**: how fan-out is ingested (partitioning, consumer groups, dedicated projection workers); how the projection pipeline absorbs the burst without pushing backpressure into Room Gameplay writers; how bracket/standings views remain coherent.

**Spectator View** must give the same privacy treatment as in the Design Checkpoint: what information crosses the boundary, what is withheld, which domain events drive materialization, the projection model (CQRS, event-carried state transfer, etc.), and how privacy is enforced in the projection/query path.

**Diagrams:**

1. **Intra-context sequence** — Room Gameplay hot path showing log-before-broadcast end-to-end.
2. **Cross-context sequence** — Spanning at least two bounded contexts, e.g. game completion → match/series outcome → tournament/round advancement, or casual game completion → Elo update.

### 6.2 Latest design package (aligned with the architecture)

Include current design artifacts so a reader can verify: ubiquitous language and context map still match the architecture; commands/events still match integration contracts; edge cases and failure paths are still addressed.

Provide a **CHANGELOG-design.md** summarizing updates. Minimum bar:

1. **Enumerate by name** every design artifact changed (file path or doc section), citing the **deliverable number and title** from the Design Checkpoint §5 where applicable.
2. For each change, state **why** — specifically the **architecture or integration constraint** that required it.
3. For each change, **confirm explicitly** that no Design Checkpoint non-negotiable domain guarantee was weakened or dropped.

### 6.3 Communication patterns

**Client connection model (mandatory):** Declare which pattern clients use for realtime play and spectating; which deployable terminates long-lived connections; how per-room ordering is preserved; how this composes with session invalidation and spectator privacy.

**Rate limiting (mandatory):** Map each layer (per IP, per user, per room/tournament action) to **concrete deployables**. Explain how the limiter gets principal identity and scope.

**Integration table** for each significant integration:

| From → To | Pattern | Rationale | Failure semantics (timeout, retry, DLQ, saga step, etc.) |
|-----------|---------|-----------|----------------------------------------------------------|

Must include at least one row for time-bounded domain windows (Uno! challenge and/or reconnection timer) and at least one row for session invalidation → live connection termination.

### 6.4 Persistence layer per context

For each context/service:

- **Primary store** and what data it owns.
- **Consistency model** — strong vs. eventual; transactional boundaries.
- **Read models** — materialized views, caches; how built and how stale they may be.
- **Retention and audit** — game log immutability, tournament audit needs, PII boundaries.

For Room Gameplay: show how the primary store and transaction boundaries implement log-before-broadcast (same commit as log append + outbox row, or single event-store append before relay).

Show the **read path for the immutable game log** (dispute resolution and audit): who may query or export it, for what purpose, and how access is authorized.

Avoid a single shared database across contexts unless explicitly justified.

### 6.5 Capacity sketch (mandatory)

Order-of-magnitude reasoning at minimum:

- Peak concurrent matches in the first tournament round (100,000+ simultaneous matches).
- Approximate concurrent rooms/players/spectators at that moment.
- Event or command rates that matter for brokers and gameplay services.
- Which components scale horizontally vs. intentionally singleton or partitioned.
- Spectators as a multiplier on realtime load (10:1 ratio plausible); if fan-out or regional edges are capped, say so.

## 7) Suggested additional deliverables (strongly recommended)

1. **NFR matrix** — Latency budgets, throughput targets, availability, and how each major flow meets them.
2. **Threat model (lightweight)** — STRIDE or similar for public APIs, session takeover, event tampering, rate-limit bypass.
3. **Observability architecture** — Logging, metrics, tracing; correlation IDs across async flows; dashboards for tournament round health.
4. **Decision log (ADRs)** — Short Architecture Decision Records for the top 5–10 choices (broker vs. none, outbox, BFF vs. direct, client connection model, etc.).

## 8) Evaluation criteria

- **Coherence** — Services and interfaces match bounded contexts and domain events.
- **Interface quality** — Clear ownership of commands, queries, and events; contracts usable by another team.
- **Integration appropriateness** — Communication patterns fit the problem (consistency vs. latency vs. scale).
- **Security enforcement placement** — Multi-layer rate limiting mapped to deployables; authentication architecturally grounded.
- **Data architecture** — Per-context persistence aligns with consistency needs; read/write separation where needed.
- **Alignment** — Design package and architecture tell one story; changelog explains intentional changes.
- **Traceability** — Event names and command/API surfaces line up with design catalogs, or deltas are explicit.
- **Operational realism** — Failure handling, idempotency, and observability are credible for real-time, high-concurrency gameplay.
- **Timer durability** — 5-second Uno! and 60-second reconnection timers have explicit architectural owner, survive process crashes, expiry side effects are idempotent.
- **Scale credibility** — Capacity sketch (§6.5) supports claims about 1,000,000-player tournament and 100,000+ first-round simultaneous matches.

--- End task description

## Design artifacts

The completed DDD design lives in the `/design` directory and the domain rules live in `/specs`. Both must remain consistent with the architecture:

- **`design/GLOSSARY.md`** — Authoritative ubiquitous language.
- **`design/CONTEXT_MAP.md`** — 7 bounded contexts and their relationships (Analytics extracted as a separate context during architecture work; see CHANGELOG-design.md §2).
- **`design/DOMAIN_MODEL.md`** — 9 aggregates, entities, value objects, and invariants.
- **`design/COMMANDS_EVENTS.md`** — Full command and event catalog with preconditions, payloads, causality, and idempotency.
- **`design/EVENT_FLOWS.md`** — End-to-end event flow narratives (room lifecycle, tournament round, Elo, disconnection).
- **`design/FAILURE_PATHS.md`** — Edge cases and failure path analysis (30+ scenarios).
- **`design/CONSISTENCY_RECOVERY.md`** — Sagas, deduplication, compensation strategies.
- **`design/ASCII_FLOW.md`** — EventStorming boards (CMD/EVT/POL notation).
- **`specs/RULESET.md`** — Complete UNO game rules (authoritative source for in-game logic).
- **`specs/CONSTRAINTS.md`** — Platform-wide business rules (rooms, sessions, Elo, game log).
- **`specs/TOURNAMENT_RULES.md`** — Tournament-specific rules (Bo3, advancement, tie-breaks, timeouts).
- **`specs/ASSUMPTIONS.md`** — Open questions and explicit assumptions.
