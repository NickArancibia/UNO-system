# UnoArena - Missing Requirements Plan

This document defines a concrete plan to close the remaining requirement gaps in the DDD assignment package.
It focuses on what is still missing, why it matters, and how to complete it in a controlled sequence.

Date baseline: 2026-04-01

---

## 1) Current Coverage Snapshot

Current repository coverage is strong on game and policy rules:
- `specs/RULESET.md` covers detailed in-game behavior.
- `specs/CONSTRAINTS.md` covers platform constraints and policies.
- `specs/TOURNAMENT_RULES.md` covers tournament behavior, including Bo3.
- `specs/ASSUMPTIONS.md` covers assumptions and open decisions.

Current repository coverage is weak on required DDD deliverables:
- No root `README.md` or `index.md` linking all submission artifacts.
- No explicit EventStorming outputs.
- No formal bounded-context map artifact.
- No formal aggregate/entity/value object model artifact.
- No command-to-event catalog with causality and idempotency.
- No explicit end-to-end event narratives per required flow.
- No dedicated failure-path matrix covering all mandatory categories.

---

## 2) Requirement Gap Matrix (Assignment Traceability)

| Required deliverable | Current status | Gap level | Missing requirement detail |
|---|---|---|---|
| Root `README.md` or `index.md` with links | Missing | Critical | No submission entrypoint and no artifact navigation |
| Domain glossary + ubiquitous language | Partial | High | Terms exist informally, but no authoritative glossary with strict definitions and aliases |
| Bounded contexts + context map | Missing | Critical | Context boundaries, ownership, and relationships are not explicitly modeled |
| Spectator View boundary treatment | Partial | High | Visibility rules exist, but crossing events/contracts are not formally documented |
| Aggregates, entities, value objects | Missing | Critical | No explicit consistency boundaries or invariant ownership map |
| Commands and domain events catalog | Partial | Critical | Some events appear in prose, but no full command-event matrix with causality and idempotency |
| Event flow narratives (3 mandatory sequences) | Missing | Critical | End-to-end cross-context flow is not specified as deterministic narratives |
| Edge cases and failure paths (all categories) | Partial | Critical | Several categories exist in prose, but no complete structured matrix and expected emitted events |
| Consistency and recovery strategy | Partial | High | Principles exist (idempotency/versioning), but no full retry/dedup/compensation strategy by context |
| Open questions and assumptions separation | Partial | Medium | Assumptions exist, but validated requirements vs assumptions are not fully partitioned per artifact |
| EventStorming as methodology output | Missing | High | No documented EventStorming artifact summaries (commands, events, policies, invariants) |

---

## 3) Bo3-Related Requirement Gaps to Close Explicitly

After introducing tournament Bo3 with early end at 2 wins, these requirements must be formalized across domain artifacts:

1. Match ranking data contract:
- Required fields: `match_wins`, `cumulative_card_point_burden`, `cumulative_cards_remaining`, `forfeit_status`, `forfeit_timestamp`.
- Requirement: ranking and advancement must be reproducible from persisted values.

2. Tie-break scope precision:
- Requirement: define whether tie-break aggregates include all played games in the match for tied players (recommended), and state this consistently.

3. Tie-break terminal behavior:
- Requirement: define deterministic fallback if players remain tied after the two configured tie-breakers, especially when the tie intersects the top-3 cutoff.

4. Timeout interaction with Bo3:
- Requirement: define exact transition rules for `match_timeout_reached`, current-game resolution, and final ranking freeze.

5. Event model updates:
- Requirement: include Bo3-specific events, for example `MatchWinAwarded`, `MatchEndedEarly`, `MatchEndedAfterGame3`, `AdvancementResolved`.

6. Read model and auditability:
- Requirement: match-level projection must expose both win-based and tie-break metrics for dispute resolution.

---

## 4) Execution Plan (Priority Order)

### Phase P0 - Submission Structure and Language Baseline
Goal: establish shared vocabulary and artifact navigation.

Deliverables:
1. `design/README.md` (or `index.md`) as the submission hub.
2. `design/GLOSSARY.md` with authoritative terms and non-ambiguous definitions.

Acceptance criteria:
- Every spec document is linked from root.
- Terms `game`, `match`, `round`, `tournament`, `forfeit`, `timeout`, `active player`, `placement`, `advancement` have explicit definitions.
- Synonyms and prohibited ambiguous terms are listed.

Dependencies:
- None.

---

### Phase P1 - Structural DDD Model
Goal: define domain boundaries and consistency ownership.

Deliverables:
1. `design/CONTEXT_MAP.md`
2. `design/DOMAIN_MODEL.md`

Required content:
- Bounded contexts: at minimum Room Gameplay, Tournament Orchestration, Ranking, Identity/Session, Spectator View, Moderation/Admin.
- Relationship type per pair (upstream/downstream, published language, anti-corruption layer where needed).
- Aggregate list with command ownership and invariants.
- Entity and value object inventories.

Acceptance criteria:
- Each invariant is owned by exactly one aggregate.
- Each cross-context interaction identifies source event and consuming policy.
- Spectator View section explicitly states what is withheld and why.

Dependencies:
- P0 glossary finalized.

---

### Phase P2 - Behavior and Event Contract Completion
Goal: make behavior executable at domain level through command-event definitions.

Deliverables:
1. `design/COMMANDS_EVENTS.md`
2. `design/EVENT_FLOWS.md`

Required content:
- Command catalog with preconditions, rejected reasons, idempotency key behavior.
- Domain event catalog with producer aggregate, payload summary, and downstream consumers.
- Mandatory narratives:
  - Room creation to completion.
  - Tournament round advancement.
  - Elo/ranking updates after game completion.

Acceptance criteria:
- Every command maps to at least one success event or one explicit rejection outcome.
- Stale command behavior is defined for all write commands.
- Bo3 events and transitions are covered end-to-end.

Dependencies:
- P1 context map and aggregate boundaries.

---

### Phase P3 - Failure, Consistency, and Recovery Hardening
Goal: close assignment-critical reliability and edge-case requirements.

Deliverables:
1. `design/FAILURE_PATHS.md`
2. `design/CONSISTENCY_RECOVERY.md`
3. update `specs/ASSUMPTIONS.md` (only unresolved questions remain).

Required content:
- Required edge-case categories from assignment:
  - concurrent conflicting actions
  - disconnections and late rejoin
  - stale and replayed commands
  - partial failures between contexts
  - security and abuse scenarios
  - spectator privacy violations
- For each case: expected domain behavior, emitted events, recovery policy, and invariant protection.
- Retry/dedup/compensation policies by context and failure type.

Acceptance criteria:
- Every failure case has an observable terminal state.
- No case leaves ranking/advancement ambiguous.
- Assumptions are clearly separated from validated requirements.

Dependencies:
- P2 command/event definitions.

---

### Phase P4 - Final Review and Traceability Closure
Goal: prove completeness against assignment rubric.

Deliverables:
1. `design/REQUIREMENTS_TRACEABILITY.md`
2. final quality pass across all docs.

Required content:
- One-to-one mapping from assignment deliverables to files and sections.
- Explicit list of resolved vs unresolved decisions.
- Cross-reference validation links between rules, constraints, tournaments, and event model.

Acceptance criteria:
- Every assignment bullet has a corresponding section reference.
- No contradictory rule text remains between files.

Dependencies:
- P0 to P3 complete.

---

## 5) Detailed Work Packages

### WP-01: Submission Hub
- Create root `README.md`.
- Include: purpose, doc map, reading order, and "how to validate completeness".

### WP-02: Ubiquitous Language
- Extract terms from all current specs.
- Normalize to one definition each.
- Add anti-ambiguity notes (for example "score" vs "card-point burden").

### WP-03: Context Map
- Model ownership boundaries and event interfaces.
- Include spectator boundary contract as first-class section.

### WP-04: Domain Model
- Define aggregates and invariants:
  - `GameSession`
  - `Room`
  - `Tournament`
  - `TournamentRoomMatch`
  - `PlayerProfile`
  - `Session`
- Define value objects (examples): `Card`, `HandSnapshot`, `Placement`, `TimerWindow`, `StateVersion`, `IdempotencyKey`.

### WP-05: Command/Event Catalog
- Build command list per aggregate.
- Build emitted-event list with downstream consumers.
- Include idempotency and conflict semantics for each command.

### WP-06: Event Narratives
- Write deterministic sequences for the 3 mandatory flows.
- Include sync decision points vs async propagation points.

### WP-07: Failure Matrix
- Build scenario matrix with invariant checks and emitted events.
- Include abuse and security scenarios with escalation outcomes.

### WP-08: Consistency and Recovery
- Define retry and dedup strategy per message type.
- Define compensation for cross-context failures where needed.
- Define reconciliation procedure for projection lag and replay.

### WP-09: Assumptions Closure
- Keep only truly unresolved decisions in `ASSUMPTIONS.md`.
- Move validated decisions into authoritative rule/model artifacts.

---

## 6) Decision Log Needed Before Completion

These decisions are likely blockers for complete consistency and should be resolved explicitly:

1. Final fallback when Bo3 tie-breakers still tie at advancement cutoff.
2. Formal scope of Bo3 tie-break accumulation (all played match games for tied players recommended).
3. Whether tournament timeout always ends the match immediately (current rule says yes).
4. Deterministic ordering among multiple forfeited players across different games.
5. Event payload minimums required for replay-safe dispute audits.
6. Projection consistency guarantees for leaderboard reads during heavy tournament progression.

---

## 7) Suggested File Layout After Plan Completion

```text
design/
  README.md
  GLOSSARY.md
  CONTEXT_MAP.md
  DOMAIN_MODEL.md
  COMMANDS_EVENTS.md
  EVENT_FLOWS.md
  ASCII_FLOW.md
  FAILURE_PATHS.md
  CONSISTENCY_RECOVERY.md
  REQUIREMENTS_TRACEABILITY.md
  MISSING_REQUIREMENTS_PLAN.md
specs/
  RULESET.md
  CONSTRAINTS.md
  TOURNAMENT_RULES.md
  ASSUMPTIONS.md
```

---

## 8) Definition of Done

The assignment is considered complete only when:

1. All mandatory deliverables exist as markdown artifacts and are linked from root.
2. Every required edge-case category has explicit behavior and emitted events.
3. Bounded contexts, aggregates, commands, and events form one coherent, non-contradictory model.
4. Bo3 tournament behavior is reflected consistently across rules, commands/events, and narratives.
5. Assumptions are clearly separated from validated requirements.
6. A traceability matrix proves full coverage of assignment requirements.
