# CHANGELOG-design.md — Design Artifact Changes for Architecture

This document enumerates every design artifact changed to support the architecture, citing the original Design Checkpoint deliverable, the reason for change, and confirmation that no domain guarantee was weakened.

---

## 1. No Changes to Core Domain Design

After reviewing all architecture service specifications against the design artifacts (`COMMANDS_EVENTS.md`, `DOMAIN_MODEL.md`, `EVENT_FLOWS.md`, `CONSISTENCY_RECOVERY.md`, `FAILURE_PATHS.md`, `CONTEXT_MAP.md`, `GLOSSARY.md`, `ASCII_FLOW.md`, `REQUIREMENTS_TRACEABILITY.md`), **no domain-level commands, events, aggregates, or invariants were changed**. All architecture interfaces trace directly to documented commands and events.

The following entries document where the architecture introduces **internal implementation mechanisms** that were not explicitly named in the design, and where the architecture adds **structural elements** (service specs, ADRs, capacity sketch, integration view) that are new deliverables but do not modify domain semantics.

---

## 2. Architecture-Only Additions (No Design Delta)

These are new architecture documents that describe implementation choices for existing domain concepts. None require changes to the design package.

| Artifact | What was added | Design reference | Domain guarantee unchanged? |
|---|---|---|---|
| `architecture/services/room-gameplay.md` | Internal HTTP commands: `CreateRoom`, `AssignPlayersToRoom`, `ForceCompleteGame`, `StartNextGameInRoom` | These implement the Match aggregate's Bo3 sequencing (DOMAIN_MODEL.md §Match) and tournament room creation; they are internal RPCs, not new domain commands | ✅ Yes — Match aggregate still owns game sequencing; the HTTP calls are the delivery mechanism |
| `architecture/services/room-gameplay.md` §6 | Challenge-window reconciliation sweep (every 2s) | Implements the 5-second challenge window timer durability requirement (ADR-004, RULESET.md) | ✅ Yes — the sweep is a crash-recovery safety net; it does not change the 5-second window semantics |
| `architecture/services/room-gameplay.md` §10 | Gameplay PostgreSQL sharding by `game_id % 16` | No design change — sharding is an infrastructure decision for the `GameSession` aggregate's persistence layer | ✅ Yes — per-game serialization is preserved via row-level locks within each shard |
| `architecture/services/room-gameplay.md` §10 | `POST /internal/push/{player_id}` on API Gateway | Implements the push-invalidation path required by the single-active-session invariant (DOMAIN_MODEL.md §PlayerSession, ADR-005) | ✅ Yes — the invariant is strengthened (passive-connection heartbeat check), not weakened |
| `architecture/adr/ADR-004-timer-durability.md` | Challenge-window reconciliation sweep added to Consequences | Extends the existing reconciliation sweep (originally turn-timer only) to cover the 5-second challenge window | ✅ Yes — extends crash recovery without changing timer behavior |
| `architecture/adr/ADR-005-session-invalidation-push.md` | Passive-connection heartbeat validation added to Consequences | Closes the passive-player window from 45s to 30s by adding outbound push validation | ✅ Yes — strengthens single-active-session; no domain invariant is relaxed |
| `architecture/CONTAINER_VIEW.md` | Redis deployment model: separate instances instead of logical DBs | No design change — Redis key namespacing was already `identity:*`, `gameplay:*`, etc. The deployment model clarifies Cluster compatibility | ✅ Yes — no key names or patterns changed; only the instance topology |
| `architecture/services/tournament.md` §5.2.1 | Pre-commit HTTP call failure recovery path documented | Documents the recovery path when `GameStarted` arrives for a game_id with no matching `match_games` row | ✅ Yes — no design command or event was changed; the reconciliation is an operational safety net |
| `architecture/CAPACITY_SKETCH.md` | New document (mandatory deliverable §6.5) | No design changes; numbers derived from existing architecture specifications | N/A — new document, no prior design artifact to change |
| `architecture/INTEGRATION_VIEW.md` | New document (mandatory deliverable §6.3) | No design changes; integrates existing architecture specifications into a single view | N/A — new document, no prior design artifact to change |
| `architecture/services/ranking.md` | New service spec for the Ranking bounded context | Events consumed/produced match COMMANDS_EVENTS.md exactly: `GameCompleted` (casual Elo), `TournamentCompleted` (tournament Elo), `EloUpdated`, `EloReverted` | ✅ Yes — no new events; all event names and payloads match the design catalog |
| `architecture/services/ranking.md` §4.4 | Added `moderation-events` topic consumption for `GameResultVoided` | `GameResultVoided` was already documented in COMMANDS_EVENTS.md as consumed by Ranking for Elo reversal; the architecture previously incorrectly routed it through `identity-events` — now correctly via `moderation-events` | ✅ Yes — the event and its handler are unchanged; only the Kafka topic routing is corrected |
| `architecture/services/ranking.md` §5 | Elo formula aligned with CONSTRAINTS.md §5.2: pairwise multi-player Elo with 3-tier K-factors (<20→32, 20-99→16, 100+→12), performance bonus (+3), and starting Elo = 1000 | Constraints were already authoritative; the architecture spec had a simplified approximation | ✅ Yes — the domain invariant (forfeit = last place, abandoned = no Elo) is preserved |
| `architecture/services/moderation.md` | New service spec for the Moderation/Admin bounded context | `GameResultVoided` matches COMMANDS_EVENTS.md §VoidGameResult; `SuspendPlayer`/`BanPlayer` are corrective commands referenced in FAILURE_PATHS.md | ✅ Yes — no new events; corrective commands are admin operations, not domain commands |
| `architecture/services/moderation.md` §3.4 | Added `FlagGame` endpoint (player-facing, 5 flags/hour per user) | `FlagGame` was documented in COMMANDS_EVENTS.md §3.5; produces `GameFlagged` event on `moderation-events` | ✅ Yes — matches the documented command catalog |
| `architecture/services/moderation.md` §5.2 | Added write-before-effect invariant explicit documentation | PLAN Phase 5 requirement: audit row must be written in same PostgreSQL transaction as corrective command dispatch | ✅ Yes — strengthens ordering guarantee |
| `architecture/services/moderation.md` §7 | Added full rate limiting map and abuse escalation thresholds aligned with CONSTRAINTS.md §10 | Escalation thresholds now match: 5 violations/10min → warning, 3 warnings/24h → suspend 15min | ✅ Yes — implements documented abuse policy |
| `architecture/services/moderation.md` §4.1 | `moderation-events` Kafka topic introduced for `GameResultVoided` and `GameFlagged` | Previously `GameResultVoided` was (incorrectly) routed through `identity-events`; new topic follows the one-topic-per-producing-context pattern (decision O9) | ✅ Yes — event semantics unchanged; only topic routing corrected |
| `architecture/PLAN.md` | Redis deployment model note added | Functional key naming unchanged; only deployment topology clarified | ✅ Yes — no key collision risk introduced |

---

## 3. Design Artifacts Explicitly Unchanged

| Design artifact | Status | Notes |
|---|---|---|
| `design/GLOSSARY.md` | **Unchanged** | All terms used in architecture specs reference existing glossary entries |
| `design/CONTEXT_MAP.md` | **Unchanged** | Six bounded contexts map directly to six service specs (Ranking and Moderation now have their own specs, consistent with the context map) |
| `design/DOMAIN_MODEL.md` | **Unchanged** | `Match` aggregate behavior (Bo3 sequencing, timeout token) implemented by `tournament-service` internal logic; no aggregate boundary was crossed |
| `design/COMMANDS_EVENTS.md` | **Unchanged** | Every event name in the architecture spec matches a documented event. Internal HTTP commands (`CreateRoom`, `ForceCompleteGame`, `StartNextGameInRoom`, `POST /internal/push/{player_id}`) are implementation mechanisms, not new domain commands. `match_id?` and `game_type` fields on `GameCompleted` were already present in the design |
| `design/EVENT_FLOWS.md` | **Unchanged** | All flows in the architecture are traceable to documented event flows |
| `design/CONSISTENCY_RECOVERY.md` | **Unchanged** | Idempotent consumer keys in architecture specs match documented dedup keys |
| `design/FAILURE_PATHS.md` | **Unchanged** | Failure paths documented in architecture (timer reconciliation, pre-commit HTTP call recovery) are additive safety nets, not changes to documented failure handling |

---

## 4. Summary

**No design artifacts were changed.** All architecture interfaces trace directly to documented commands and events. The architecture adds:

1. **Internal RPC mechanisms** (`CreateRoom`, `ForceCompleteGame`, `StartNextGameInRoom`, `POST /internal/push/{player_id}`) that implement existing domain command semantics via HTTP.
2. **Crash-recovery safety nets** (challenge-window reconciliation sweep, passive-connection heartbeat validation, pre-commit HTTP call reconciliation) that strengthen invariants without changing domain semantics.
3. **Infrastructure decisions** (Redis instance topology, PostgreSQL sharding, API Gateway push endpoint) that are deployment-level, not domain-level.
4. **New service specs** (Ranking, Moderation) for bounded contexts that were documented in the Design Checkpoint but did not yet have architecture specs.
5. **Mandatory deliverables** (CAPACITY_SKETCH.md, INTEGRATION_VIEW.md) required by §6.3 and §6.5.

**No Design Checkpoint non-negotiable domain guarantee was weakened or dropped.**