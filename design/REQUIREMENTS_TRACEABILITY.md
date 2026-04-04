# UnoArena — Requirements Traceability Matrix

This document maps every mandatory deliverable from the assignment specification to the exact file and section where it is addressed. It also separates validated requirements from open assumptions, and validates cross-reference consistency across design artifacts.

---

## 1. Assignment Deliverable Coverage

### Deliverable 1 — Domain Glossary

| Assignment requirement | Covered in | Section |
|---|---|---|
| Ubiquitous language with precise definitions | [GLOSSARY.md](./GLOSSARY.md) | All sections |
| Distinguish: `game`, `match`, `round`, `tournament` | [GLOSSARY.md](./GLOSSARY.md) | Section 1 — Core Structural Terms |
| Define `forfeit`, `placement`, `advancement`, `qualifier` | [GLOSSARY.md](./GLOSSARY.md) | Sections 1, 4 |
| Anti-ambiguity notes for overlapping terms | [GLOSSARY.md](./GLOSSARY.md) | Section 9 — Anti-Ambiguity Notes |
| Context-specific term nuances | [CONTEXT_MAP.md](./CONTEXT_MAP.md) | Section 2 (per-context local term nuances) |

---

### Deliverable 2 — Bounded Contexts & Context Map

| Assignment requirement | Covered in | Section |
|---|---|---|
| Proposed contexts (Room Gameplay, Tournament Orchestration, Ranking, Identity/Session, Spectator View) | [CONTEXT_MAP.md](./CONTEXT_MAP.md) | Section 2 |
| Moderation/Admin context | [CONTEXT_MAP.md](./CONTEXT_MAP.md) | Section 2.6 |
| Relationships between contexts (upstream/downstream) | [CONTEXT_MAP.md](./CONTEXT_MAP.md) | Section 3 |
| Explicit treatment of Spectator View: what crosses its boundary | [CONTEXT_MAP.md](./CONTEXT_MAP.md) | Section 2.5 — Privacy contract table |
| What is withheld from Spectator View and why | [CONTEXT_MAP.md](./CONTEXT_MAP.md) | Section 2.5 — Privacy contract table |
| Which domain events drive Spectator View updates | [CONTEXT_MAP.md](./CONTEXT_MAP.md) | Section 2.5 — Events consumed |
| Cross-context event contracts table | [CONTEXT_MAP.md](./CONTEXT_MAP.md) | Section 4 |
| Visual context map diagram | [CONTEXT_MAP.md](./CONTEXT_MAP.md) | Section 1 |
| Spectator View read models (DDD artifacts) | [DOMAIN_MODEL.md](./DOMAIN_MODEL.md) | Section 5 |

---

### Deliverable 3 — Aggregates, Entities, Value Objects

| Assignment requirement | Covered in | Section |
|---|---|---|
| Candidate aggregates and consistency boundaries | [DOMAIN_MODEL.md](./DOMAIN_MODEL.md) | Section 1 |
| `GameSession` aggregate with invariants | [DOMAIN_MODEL.md](./DOMAIN_MODEL.md) | Section 1.1 |
| `Room` aggregate with invariants | [DOMAIN_MODEL.md](./DOMAIN_MODEL.md) | Section 1.2 |
| `Match` aggregate with invariants | [DOMAIN_MODEL.md](./DOMAIN_MODEL.md) | Section 1.3 |
| `TournamentRound` aggregate with invariants | [DOMAIN_MODEL.md](./DOMAIN_MODEL.md) | Section 1.4 |
| `Tournament` aggregate with invariants | [DOMAIN_MODEL.md](./DOMAIN_MODEL.md) | Section 1.5 |
| `PlayerProfile` aggregate with invariants | [DOMAIN_MODEL.md](./DOMAIN_MODEL.md) | Section 1.6 |
| `PlayerSession` aggregate with invariants | [DOMAIN_MODEL.md](./DOMAIN_MODEL.md) | Section 1.7 |
| Entities inventory | [DOMAIN_MODEL.md](./DOMAIN_MODEL.md) | Section 2 |
| Value objects inventory | [DOMAIN_MODEL.md](./DOMAIN_MODEL.md) | Section 3 |
| Aggregate interaction map (event-driven, no direct calls) | [DOMAIN_MODEL.md](./DOMAIN_MODEL.md) | Section 4 |
| Consistency boundary summary | [DOMAIN_MODEL.md](./DOMAIN_MODEL.md) | Section 6 |

---

### Deliverable 4 — Commands & Domain Events Catalog

| Assignment requirement | Covered in | Section |
|---|---|---|
| Core commands with causality | [COMMANDS_EVENTS.md](./COMMANDS_EVENTS.md) | Section 1 |
| Command preconditions and rejection reasons | [COMMANDS_EVENTS.md](./COMMANDS_EVENTS.md) | Section 1 (per command) |
| Idempotency considerations per command | [COMMANDS_EVENTS.md](./COMMANDS_EVENTS.md) | Sections 1, 4 |
| Stale command behavior | [COMMANDS_EVENTS.md](./COMMANDS_EVENTS.md) | Section 4 |
| Domain events with producer, payload, consumers | [COMMANDS_EVENTS.md](./COMMANDS_EVENTS.md) | Section 2 |
| Causality map (what triggers what) | [COMMANDS_EVENTS.md](./COMMANDS_EVENTS.md) | Section 3 |
| Bo3-specific events (`MatchWinAwarded`, `MatchEndedEarly`, `MatchEndedAfterGame3`, `AdvancementResolved`, `MatchTimeoutReached`) | [COMMANDS_EVENTS.md](./COMMANDS_EVENTS.md) | Section 2.3 |
| Challenge window differentiation (Uno vs WD4 vs Combined) | [COMMANDS_EVENTS.md](./COMMANDS_EVENTS.md) | Section 2.1 — `ChallengeWindowOpened` |
| Abuse escalation events | [COMMANDS_EVENTS.md](./COMMANDS_EVENTS.md) | Section 2.7 |

---

### Deliverable 5 — Domain Event Flow Narratives

| Assignment requirement | Covered in | Section |
|---|---|---|
| Room creation to completion (end-to-end) | [EVENT_FLOWS.md](./EVENT_FLOWS.md) | Flow 1 |
| Tournament round advancement | [EVENT_FLOWS.md](./EVENT_FLOWS.md) | Flow 2 |
| Match timeout handling | [EVENT_FLOWS.md](./EVENT_FLOWS.md) | Flow 2 — Phase C |
| Elo/ranking updates after game completion | [EVENT_FLOWS.md](./EVENT_FLOWS.md) | Flow 3 — Phase A |
| Tournament Elo update after tournament concludes | [EVENT_FLOWS.md](./EVENT_FLOWS.md) | Flow 3 — Phase B |
| Admin Elo revert flow | [EVENT_FLOWS.md](./EVENT_FLOWS.md) | Flow 3 — Phase C |
| Disconnection, reconnection, forfeit flows | [EVENT_FLOWS.md](./EVENT_FLOWS.md) | Flow 4 |
| Synchronous decision points labeled | [EVENT_FLOWS.md](./EVENT_FLOWS.md) | All flows (`[SYNC]` tags) |
| Asynchronous propagation labeled | [EVENT_FLOWS.md](./EVENT_FLOWS.md) | All flows (`[ASYNC]` tags) |
| Server-side timer events labeled | [EVENT_FLOWS.md](./EVENT_FLOWS.md) | All flows (`[TIMER]` tags) |
| Uno! window timing model (concurrent with turn timer) | [EVENT_FLOWS.md](./EVENT_FLOWS.md) | Flow 1 — Phase C, NOTE block |

---

### Deliverable 6 — Edge Cases & Failure-Path Analysis

| Assignment requirement | Covered in | Section |
|---|---|---|
| Concurrent conflicting actions | [FAILURE_PATHS.md](./FAILURE_PATHS.md) | Section 1 (7 scenarios) |
| Two players simultaneously playing a card | [FAILURE_PATHS.md](./FAILURE_PATHS.md) | Section 1.1 |
| Simultaneous jump-ins | [FAILURE_PATHS.md](./FAILURE_PATHS.md) | Section 1.2 |
| Simultaneous Uno! challenges | [FAILURE_PATHS.md](./FAILURE_PATHS.md) | Section 1.3 |
| Disconnections and late rejoin attempts | [FAILURE_PATHS.md](./FAILURE_PATHS.md) | Section 2 (7 scenarios) |
| Late rejoin after forfeit issued | [FAILURE_PATHS.md](./FAILURE_PATHS.md) | Section 2.3 |
| Disconnect during challenge window | [FAILURE_PATHS.md](./FAILURE_PATHS.md) | Section 2.5 |
| No-show in tournament lobby | [FAILURE_PATHS.md](./FAILURE_PATHS.md) | Section 2.6 |
| Stale commands | [FAILURE_PATHS.md](./FAILURE_PATHS.md) | Section 3.1 |
| Replayed commands | [FAILURE_PATHS.md](./FAILURE_PATHS.md) | Section 3.2 |
| Partial failures between contexts | [FAILURE_PATHS.md](./FAILURE_PATHS.md) | Section 4 (6 scenarios) |
| Security and abuse scenarios | [FAILURE_PATHS.md](./FAILURE_PATHS.md) | Section 5 (7 scenarios) |
| Session takeover | [FAILURE_PATHS.md](./FAILURE_PATHS.md) | Section 5.1 |
| Spam / flooding | [FAILURE_PATHS.md](./FAILURE_PATHS.md) | Section 5.4 |
| Spectator privacy violations | [FAILURE_PATHS.md](./FAILURE_PATHS.md) | Section 6 (6 scenarios) |
| Player attempting to read another's hand via spectator channel | [FAILURE_PATHS.md](./FAILURE_PATHS.md) | Section 6.1, 6.2 |
| Expected domain behavior and emitted events for each case | [FAILURE_PATHS.md](./FAILURE_PATHS.md) | All sections (per-scenario) |

---

### Deliverable 7 — Consistency & Recovery Strategy

| Assignment requirement | Covered in | Section |
|---|---|---|
| Retries and deduplication at business level | [CONSISTENCY_RECOVERY.md](./CONSISTENCY_RECOVERY.md) | Sections 2.1, 2.2 |
| Compensation / saga decisions | [CONSISTENCY_RECOVERY.md](./CONSISTENCY_RECOVERY.md) | Section 3 (5 sagas) |
| How invariant violations are prevented | [CONSISTENCY_RECOVERY.md](./CONSISTENCY_RECOVERY.md) | Section 4 (per aggregate) |
| How invariant violations are detected | [CONSISTENCY_RECOVERY.md](./CONSISTENCY_RECOVERY.md) | Section 4 (enforcement mechanism column) |
| Projection lag reconciliation | [CONSISTENCY_RECOVERY.md](./CONSISTENCY_RECOVERY.md) | Section 5 |
| Deduplication cache TTL guidance | [CONSISTENCY_RECOVERY.md](./CONSISTENCY_RECOVERY.md) | Section 6 |

---

### Deliverable 8 — Open Questions & Assumptions

| Assignment requirement | Covered in | Section |
|---|---|---|
| Connection semantics assumptions | [specs/ASSUMPTIONS.md](../specs/ASSUMPTIONS.md) | Section 1 |
| At-least-once delivery assumption | [specs/ASSUMPTIONS.md](../specs/ASSUMPTIONS.md) | Section 1 |
| Server-authoritative clocks assumption | [specs/ASSUMPTIONS.md](../specs/ASSUMPTIONS.md) | Section 1 |
| Concurrency and stale command model | [specs/ASSUMPTIONS.md](../specs/ASSUMPTIONS.md) | Section 2 |
| Elo formula rationale (casual) | [specs/ASSUMPTIONS.md](../specs/ASSUMPTIONS.md) | Section 3.1 |
| Elo formula rationale (tournament) | [specs/ASSUMPTIONS.md](../specs/ASSUMPTIONS.md) | Section 3.2 |
| Regional matchmaking assumptions | [specs/ASSUMPTIONS.md](../specs/ASSUMPTIONS.md) | Section 4 |
| Game log contents | [specs/ASSUMPTIONS.md](../specs/ASSUMPTIONS.md) | Section 5 |
| Authentication mechanism | [specs/ASSUMPTIONS.md](../specs/ASSUMPTIONS.md) | Section 6 |
| Open decisions (deferred) | [specs/ASSUMPTIONS.md](../specs/ASSUMPTIONS.md) | Section 7 |
| Resolved decisions | [specs/ASSUMPTIONS.md](../specs/ASSUMPTIONS.md) | Section 7 — Resolved decisions table |

---

### EventStorming Methodology (mandatory per assignment)

| Assignment requirement | Covered in | Section |
|---|---|---|
| Main business flows via EventStorming | [ASCII_FLOW.md](./ASCII_FLOW.md) | Sections 4, 5 |
| Exceptional flows (timeouts, stale commands, disconnects, forfeits) | [ASCII_FLOW.md](./ASCII_FLOW.md) | Sections 2, 6 |
| [ASCII_FLOW.md](./ASCII_FLOW.md) | Sections 4, 5 (policies shown) |
| Cross-context interactions triggered by domain events | [ASCII_FLOW.md](./ASCII_FLOW.md) | Section 8 |
| Invariants and policy decisions | [ASCII_FLOW.md](./ASCII_FLOW.md) | Sections 4, 5 (`{POL:}` nodes) |
| Timer window timing models | [ASCII_FLOW.md](./ASCII_FLOW.md) | Section 3 |

---

## 2. Validated Requirements vs Open Assumptions

### Validated (locked in design artifacts)

| Decision | Validated in |
|---|---|
| Casual tiebreak is randomized (no shared positions) | [specs/ASSUMPTIONS.md](../specs/ASSUMPTIONS.md) — R1 |
| Match format is Best-of-Three with early end at 2 wins | [specs/TOURNAMENT_RULES.md](../specs/TOURNAMENT_RULES.md) — Section 3; [DOMAIN_MODEL.md](./DOMAIN_MODEL.md) — Section 1.3 |
| Tournament advancement: match wins → card-point burden → cards remaining | [specs/TOURNAMENT_RULES.md](../specs/TOURNAMENT_RULES.md) — Section 4; [DOMAIN_MODEL.md](./DOMAIN_MODEL.md) — `MatchStanding` |
| 60-second reconnection window applies to all disconnections | [specs/CONSTRAINTS.md](../specs/CONSTRAINTS.md) — Section 2.5 |
| No-show in Round 2+ treated identically to Round 1 | [specs/TOURNAMENT_RULES.md](../specs/TOURNAMENT_RULES.md) — Section 9 |
| WD4 hand never revealed during game; enters post-game log only | [specs/ASSUMPTIONS.md](../specs/ASSUMPTIONS.md) — R6; [FAILURE_PATHS.md](./FAILURE_PATHS.md) — Section 6.3 |
| Sole remaining player after forfeits wins match unconditionally | [specs/TOURNAMENT_RULES.md](../specs/TOURNAMENT_RULES.md) — Section 3 |
| Multi-card draw pre-checks draw pile; penalty waived if still insufficient | [specs/RULESET.md](../specs/RULESET.md) — Section 11 |
| Reconnection is complete only when session re-established AND state synced | [specs/ASSUMPTIONS.md](../specs/ASSUMPTIONS.md) — R9 |
| Tournament Elo formula uses final placement only; win rates are for sub-ordering | [specs/ASSUMPTIONS.md](../specs/ASSUMPTIONS.md) — R10 |
| Authentication is JWT + server-side `valid_sessions_from` invalidation | [specs/ASSUMPTIONS.md](../specs/ASSUMPTIONS.md) — R11 |
| Uno! challenge window runs concurrently with next player's 45s turn timer | [specs/RULESET.md](../specs/RULESET.md) — Section 8; [EVENT_FLOWS.md](./EVENT_FLOWS.md) — Flow 1 NOTE block |
| WD4 challenge window runs sequentially before next player's 45s turn timer | [specs/RULESET.md](../specs/RULESET.md) — Section 6; [EVENT_FLOWS.md](./EVENT_FLOWS.md) — Flow 1 |
| Combined window (WD4 as second-to-last card) runs sequentially, pauses on action | [specs/RULESET.md](../specs/RULESET.md) — Section 8 |
| Draw Two stacking enabled; WD4 stacking disabled in all forms | [specs/RULESET.md](../specs/RULESET.md) — Section 5 |

---

### Open (deferred to implementation or future design iteration)

| # | Open decision | Blocking? | Notes |
|---|---|---|---|
| 1 | Exact client connection protocol (SSE, WebSocket, long-poll) | No | Deferred per assignment scope; assumed persistent push channel |
| 2 | Cross-region matching wait duration before expanding radius | No | Implementation detail; does not affect domain model |
| 3 | K-factor fine-tuning post-launch | No | Initial values validated; adjustment is operational |
| 4 | Matchmaking queue window duration for Quick Play | No | Affects lobby fill speed vs Elo precision; not a domain constraint |
| 5 | Admin tooling and UI | No | Out of scope for domain design |
| 6 | Ban escalation tiers beyond 7-day window | No | Domain defines up to that point; further tiers are policy |
| 7 | Region change policy appeal process details | No | 30-day immutability + admin review is validated; appeal workflow is UX |
| 8 | Adjacent region expansion timing in matchmaking | No | Implementation detail |
| 9 | Whether partial-room game results contribute to dispute system | No | Assumed yes; no special domain rules required |
| 10 | Behavior when tournament admin-cancel occurs mid-round re: partial Elo | Partial | Currently: no Elo for any game in cancelled tournament; may be reconsidered |

---

## 3. Cross-Reference Consistency Validation

Checks that no contradictory rule text exists between specs and design artifacts.

| Rule | Source | Design artifact | Status |
|---|---|---|---|
| Turn timer is 45 seconds | CONSTRAINTS.md §2.3 | GLOSSARY.md §3, EVENT_FLOWS.md Flow 1 | ✓ Consistent |
| Uno! window is 5 seconds, concurrent with turn timer | RULESET.md §8, CONSTRAINTS.md §2.3 | EVENT_FLOWS.md Flow 1 NOTE, ASCII_FLOW.md §3.2 | ✓ Consistent (fixed from earlier inconsistency) |
| WD4 window is 5 seconds, sequential before turn timer | RULESET.md §6 | EVENT_FLOWS.md Flow 1, ASCII_FLOW.md §3.3 | ✓ Consistent |
| Combined window pauses on any action | RULESET.md §8 | ASCII_FLOW.md §3.4, DOMAIN_MODEL.md `ChallengeWindow` | ✓ Consistent |
| Reconnection window is 60 seconds | CONSTRAINTS.md §2.5 | GLOSSARY.md §2, DOMAIN_MODEL.md `ReconnectionWindow`, EVENT_FLOWS.md Flow 4 | ✓ Consistent |
| AFK forfeit at 3 consecutive expired timers (connected only) | CONSTRAINTS.md §2.4 | DOMAIN_MODEL.md §1.1, ASCII_FLOW.md §6 | ✓ Consistent |
| Top 3 advance per tournament room | TOURNAMENT_RULES.md §4 | DOMAIN_MODEL.md §1.3, COMMANDS_EVENTS.md §2.3 | ✓ Consistent |
| All active players advance if ≤3 remain | TOURNAMENT_RULES.md §4 | DOMAIN_MODEL.md §1.3 invariant, FAILURE_PATHS.md §1.5 | ✓ Consistent |
| Match timeout is 20 minutes | TOURNAMENT_RULES.md §3.1 | DOMAIN_MODEL.md §1.3, EVENT_FLOWS.md Flow 2 Phase C | ✓ Consistent |
| Casual Elo updated per completed game; tournament Elo once post-tournament | CONSTRAINTS.md §5.1 | DOMAIN_MODEL.md §1.6, EVENT_FLOWS.md Flow 3 | ✓ Consistent |
| Voided game: no Elo changes for any player | CONSTRAINTS.md §2.6 | COMMANDS_EVENTS.md §3.1 causality, CONSISTENCY_RECOVERY.md §3.1 | ✓ Consistent |
| Cancelled tournament: no Elo for any game in it | CONSTRAINTS.md §7 | CONSISTENCY_RECOVERY.md §3.3, FAILURE_PATHS.md §4.5 | ✓ Consistent |
| Spectators see hand counts but never card identities | CONSTRAINTS.md §4.3 | CONTEXT_MAP.md §2.5, DOMAIN_MODEL.md §5, FAILURE_PATHS.md §6 | ✓ Consistent |
| WD4 hand withheld during game; public post-game | CONSTRAINTS.md §4.2, ASSUMPTIONS.md R6 | FAILURE_PATHS.md §6.3, COMMANDS_EVENTS.md `WildDrawFourChallengeResolved` | ✓ Consistent |
| Single active session per player | CONSTRAINTS.md §1 | DOMAIN_MODEL.md §1.7, CONSISTENCY_RECOVERY.md §4.5 | ✓ Consistent |
| Forfeit = last place for Elo; voided game = no Elo | CONSTRAINTS.md §5.3 | DOMAIN_MODEL.md §1.6, EVENT_FLOWS.md Flow 3 | ✓ Consistent |
| Minimum 1,000 confirmed players to start tournament | TOURNAMENT_RULES.md §2 | DOMAIN_MODEL.md §1.5 invariant | ✓ Consistent |
| Phase-start thresholds vary by round number | TOURNAMENT_RULES.md §5 | DOMAIN_MODEL.md §1.4, EVENT_FLOWS.md Flow 2 | ✓ Consistent |
| Waiting state defined by timer not started (not purely player count) | CONSTRAINTS.md §2.2 | GLOSSARY.md §4 (corrected) | ✓ Consistent |
