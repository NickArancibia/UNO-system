# CHANGELOG-design.md — Design Artifact Changes for Architecture

This document enumerates every design artifact changed to support the architecture, citing the original Design Checkpoint deliverable, the reason for change, and confirmation that no domain guarantee was weakened.

---

## 1. Post-Grading Fixes (Design Checkpoint feedback)

| # | Artifact | Deliverable ref | Change | Reason | Domain guarantee unchanged? |
|---|---|---|---|---|---|
| 1 | `design/COMMANDS_EVENTS.md` | Del. 4: Commands & events catalog | Added `reason: SkipCard\|StackEffect\|Disconnect` field to `PlayerSkipped` event payload | Evaluator noted the distinction between skip causes was only inferrable from context; explicit field removes ambiguity for downstream consumers | Yes — field was always implicit in domain logic |
| 2 | `design/EVENT_FLOWS.md` | Del. 5: Event flow narratives | Added explicit privacy statement to Flow 4 Phase B reconnection snapshot | Evaluator flagged that privacy boundary during reconnection was implicit; architecture requires explicit filter on the distinct resync code path | Yes — privacy rule already enforced; now explicit |
| 3 | `design/EVENT_FLOWS.md` | Del. 5: Event flow narratives | Added blockquote to Flow 3 Phase B explicitly separating casual and tournament Elo | Evaluator awarded partial credit for separation clarity; architecture requires unambiguous routing to separate Elo paths | Yes — separation already a non-negotiable |
| 4 | `design/DOMAIN_MODEL.md` | Del. 3: Aggregates, entities, value objects | Reworded PlayerSession invariant 2 to make session creation ordering explicit (new JWT first, then `valid_sessions_from` update) | Push-invalidation path depends on new session being valid before old one is revoked | Yes — single-active-session invariant strengthened |

---

## 2. Architecture Checkpoint Design Changes

| # | Artifact | Deliverable ref | Change | Reason | Domain guarantee unchanged? |
|---|---|---|---|---|---|
| 5 | `design/CONTEXT_MAP.md` | Del. 2: Bounded contexts & context map | Fixed incorrect tie-break criterion (was "cumulative cards remaining"; corrected to "cumulative finish time") | Copy error; already correct in `specs/TOURNAMENT_RULES.md` Section 4 and all other docs | Yes — documentation inconsistency, not a model change |
| 6 | `design/CONTEXT_MAP.md` | Del. 2: Bounded contexts & context map | Extracted Analytics / Read Models as a new bounded context (section 2.6; Moderation/Admin renumbered to 2.7); updated diagram, relationships, and event contracts | Architecture Checkpoint requires dedicated treatment of `game.completed` burst at round end — partitioning, consumer groups, dedicated projection workers, backpressure isolation | Yes — Analytics is a pure downstream projection; all invariants remain in original owning aggregates |

---

## 3. Architecture-Only Additions (No Design Delta)

These are new architecture documents describing implementation choices for existing domain concepts. None require changes to the design package.

| Artifact | What was added | Design reference | Domain guarantee unchanged? |
|---|---|---|---|
| `architecture/services/room-gameplay.md` | Internal HTTP commands: `CreateRoom`, `AssignPlayersToRoom`, `ForceCompleteGame`, `StartNextGameInRoom` | Match aggregate's Bo3 sequencing (DOMAIN_MODEL.md) | Yes — internal RPCs, not new domain commands |
| `architecture/services/room-gameplay.md` §6 | Challenge-window reconciliation sweep (every 2s) | 5-second challenge window timer durability (ADR-004, RULESET.md) | Yes — crash-recovery safety net |
| `architecture/services/room-gameplay.md` §10 | Gameplay PostgreSQL sharding by `game_id % 16` | Infrastructure decision for GameSession persistence | Yes — per-game serialization preserved via row-level locks |
| `architecture/services/room-gameplay.md` §10 | `POST /internal/push/{player_id}` on API Gateway | Single-active-session push-invalidation path (ADR-005) | Yes — invariant strengthened |
| `architecture/adr/ADR-004-timer-durability.md` | Challenge-window reconciliation sweep in Consequences | Extends existing reconciliation to 5s challenge window | Yes — extends crash recovery |
| `architecture/adr/ADR-005-session-invalidation-push.md` | Passive-connection heartbeat validation in Consequences | Closes passive-player window from 45s to 30s | Yes — strengthens single-active-session |
| `architecture/CONTAINER_VIEW.md` | Redis deployment model: separate instances instead of logical DBs | Redis key namespacing unchanged; deployment topology clarified | Yes — no key names or patterns changed |
| `architecture/services/tournament.md` §5.2.1 | Pre-commit HTTP call failure recovery path | Documents recovery when `GameStarted` arrives with no matching `match_games` row | Yes — operational safety net |
| `architecture/CAPACITY_SKETCH.md` | New document (mandatory §6.5) | Numbers from existing architecture specs | N/A — new document |
| `architecture/INTEGRATION_VIEW.md` | New document (mandatory §6.3) | Integrates existing specs | N/A — new document |
| `architecture/services/ranking.md` | New service spec for Ranking context | Events match COMMANDS_EVENTS.md exactly | Yes — no new events |
| `architecture/services/ranking.md` §4.4 | `moderation-events` topic consumption for `GameResultVoided` | Corrected routing from `identity-events` to `moderation-events` | Yes — event semantics unchanged; topic routing corrected |
| `architecture/services/ranking.md` §5 | Elo formula aligned with CONSTRAINTS.md §5.2 | Constraints already authoritative; architecture had simplified approximation | Yes — domain invariant preserved |
| `architecture/services/moderation.md` | New service spec for Moderation/Admin | Matches COMMANDS_EVENTS.md and FAILURE_PATHS.md | Yes — no new events |
| `architecture/services/moderation.md` §5.2 | Write-before-effect invariant documented | Audit row in same transaction as corrective command | Yes — strengthens ordering guarantee |
| `architecture/services/moderation.md` §7 | Rate limiting map aligned with CONSTRAINTS.md §10 | Escalation thresholds now match spec | Yes — implements documented policy |
| `architecture/services/moderation.md` §4.1 | `moderation-events` Kafka topic for `GameResultVoided`, `GameFlagged` | One-topic-per-producing-context pattern (O9) | Yes — event semantics unchanged |
| `architecture/PLAN.md` | Redis deployment model note | Functional key naming unchanged | Yes — no key collision risk |

---

## 4. Design Artifact Changed — `GameCompleted` Payload

| Artifact | Change | Design Checkpoint reference | Architecture constraint | Domain guarantee unchanged? |
|---|---|---|---|---|
| `design/COMMANDS_EVENTS.md` §2.1 — `GameCompleted` | Added `outcome: completed\|abandoned` field | Del. 4 — Event Catalog | Ranking must detect abandoned casual games for Elo exclusion; deriving from `forfeited.size() == total_players` requires knowing original player count | Yes — invariant "no Elo for abandoned casual games" is *strengthened* with first-class payload signal |

---

## 5. Design Artifacts Explicitly Unchanged

| Design artifact | Status | Notes |
|---|---|---|
| `design/GLOSSARY.md` | **Unchanged** | All terms used in architecture specs reference existing glossary entries |
| `design/CONTEXT_MAP.md` | **Two changes** — see §2 above (tie-break fix + Analytics extraction) |
| `design/DOMAIN_MODEL.md` | **One change** — see §1 above (session ordering clarification) |
| `design/COMMANDS_EVENTS.md` | **Two changes** — see §1 and §4 above (`PlayerSkipped.reason` + `GameCompleted.outcome`) |
| `design/EVENT_FLOWS.md` | **Two changes** — see §1 above (reconnection privacy + tournament Elo separation) |
| `design/CONSISTENCY_RECOVERY.md` | **Unchanged** | Idempotent consumer keys in architecture specs match documented dedup keys |
| `design/FAILURE_PATHS.md` | **Unchanged** | Architecture crash-recovery paths are additive safety nets |
| `design/ASCII_FLOW.md` | **Unchanged** | |
| `design/REQUIREMENTS_TRACEABILITY.md` | **Unchanged** | |

---

## 6. Summary

**Two design artifacts were changed** (see §1 and §2): `COMMANDS_EVENTS.md` and `CONTEXT_MAP.md`, plus clarifications to `EVENT_FLOWS.md` and `DOMAIN_MODEL.md`. All changes are traceable to evaluator feedback or architecture integration constraints. The architecture additionally introduces:

1. **Internal RPC mechanisms** (`CreateRoom`, `ForceCompleteGame`, `StartNextGameInRoom`, `POST /internal/push/{player_id}`) that implement existing domain command semantics via HTTP.
2. **Crash-recovery safety nets** (challenge-window reconciliation sweep, passive-connection heartbeat validation, pre-commit HTTP call reconciliation) that strengthen invariants without changing domain semantics.
3. **Infrastructure decisions** (Redis instance topology, PostgreSQL sharding, API Gateway push endpoint) that are deployment-level, not domain-level.
4. **New service specs** (Ranking, Moderation) for bounded contexts documented in the Design Checkpoint.
5. **Mandatory deliverables** (CAPACITY_SKETCH.md, INTEGRATION_VIEW.md) required by §6.3 and §6.5.

**No Design Checkpoint non-negotiable domain guarantee was weakened or dropped.**
