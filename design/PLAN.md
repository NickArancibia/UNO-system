# UnoArena DDD — Execution Plan

Deadline: **April 5, 2026 — 23:59**

---

## Current State

**Complete and ready (no changes needed):**
- `specs/RULESET.md` — full game mechanics
- `specs/CONSTRAINTS.md` — platform rules, Elo, sessions, rate limiting
- `specs/TOURNAMENT_RULES.md` — Bo3, rounds, advancement
- `specs/ASSUMPTIONS.md` — auth model, Elo rationale, open decisions

**To be created:** all 9 design deliverables + root `README.md`

---

## Phase 0 — Foundation

### Step 1: `design/GLOSSARY.md` ✓
- [x] Authoritative ubiquitous language for all domain terms
- [x] Core terms: `game`, `match`, `round`, `tournament`, `room`, `active player`, `forfeit`, `placement`, `advancement`, `state version`, `idempotency key`
- [x] Gameplay terms: `challenge window`, `Uno! call`, `hand`, `deck`, `draw pile`, `discard pile`, `jump-in`, `stack chain`, `turn timer`, `AFK`
- [x] Scoring & ranking terms: `game score`, `card-point burden`, `match wins`, `casual Elo`, `tournament-placement Elo`, `K-factor`
- [x] Anti-ambiguity notes (e.g., "score" vs "card-point burden", "win" at game vs match vs tournament level)

### Step 2: `README.md` (root) ✓
- [x] Links to all deliverables in correct reading order
- [x] Purpose statement and submission structure

---

## Phase 1 — DDD Structure

### Step 3: `design/CONTEXT_MAP.md` ✓
- [x] 6 bounded contexts: **Room Gameplay**, **Tournament Orchestration**, **Ranking**, **Identity/Session**, **Spectator View**, **Moderation/Admin**
- [x] Upstream/downstream relationships for each context pair
- [x] Events crossing each boundary (what is shared vs withheld)
- [x] Spectator View as first-class section: which events flow in, what is stripped, the privacy contract

### Step 4: `design/DOMAIN_MODEL.md` ✓
- [x] Aggregates + key invariants:
  - `GameSession` — card play, draw, UNO mechanics, state version
  - `Room` — lifecycle: waiting → lobby → in_progress → completed
  - `Match` — Bo3 tracking, match_wins, timeout
  - `TournamentRound` — phase thresholds, qualifier pool, room formation
  - `Tournament` — rounds, champion resolution
  - `PlayerProfile` — Elo, stats
  - `PlayerSession` — single-session enforcement, reconnection window
- [x] Entities and value objects: `Card`, `Hand`, `TurnState`, `Placement`, `TimerWindow`, `StateVersion`, `IdempotencyKey`, `EloRating`, `MatchStanding`, `ChallengeWindow`, etc.
- [x] Aggregate interaction map (event-driven, no direct calls)
- [x] Consistency boundary summary per aggregate

---

## Phase 2 — Behavior & Events

### Step 5: `design/COMMANDS_EVENTS.md` ✓
- [x] Full command catalog per aggregate: preconditions, rejection reasons, idempotency key behavior, stale-version behavior
- [x] Full domain event catalog: producing aggregate, payload summary, downstream consumers
- [x] Causality map (what triggers what) — 6 key chains
- [x] Bo3-specific events: `MatchWinAwarded`, `MatchEndedEarly`, `MatchEndedAfterGame3`, `AdvancementResolved`, `MatchTimeoutReached`
- [x] Idempotency and stale command reference table

### Step 6: `design/EVENT_FLOWS.md` ✓
- [x] End-to-end narrative: Room creation → game start → gameplay → completion
- [x] End-to-end narrative: Tournament round advancement (including phase-start thresholds, timeout, final room)
- [x] End-to-end narrative: Elo/ranking update after game completion (casual + tournament + admin void revert)
- [x] Bonus flow: Disconnection → reconnection → window expiry → forfeit + new login invalidation
- [x] Synchronous decision points and async propagation labeled explicitly ([SYNC], [ASYNC], [TIMER])

---

## Phase 3 — Hardening

### Step 7: `design/FAILURE_PATHS.md` ✓
- [x] Concurrent conflicting actions (simultaneous card plays, jump-ins, UNO challenges, forfeit vs completion race)
- [x] Disconnections and late rejoin attempts (7 scenarios)
- [x] Stale and replayed commands (6 scenarios)
- [x] Partial failures between contexts (6 scenarios including tournament cancel Elo revert)
- [x] Security/abuse scenarios (session takeover, command injection, rate-limit escalation, replay attack, concurrent login race)
- [x] Spectator privacy violations (6 scenarios including ACL defense-in-depth)
- [x] Each case: expected domain behavior + emitted events + invariant protected

### Step 8: `design/CONSISTENCY_RECOVERY.md` ✓
- [x] Retry/deduplication strategy per message type and context (dedup key table per command + event)
- [x] Compensation/saga decisions — 5 sagas with failure handling (game→Elo, tournament progression, cancel revert, session invalidation, ban cascade)
- [x] Invariant violation detection and prevention per aggregate (6 aggregates)
- [x] Reconciliation for projection lag (PublicGameView, LeaderboardView, BracketView, PublicGameLog)
- [x] Deduplication cache TTL table

### Step 9: `design/ASCII_FLOW.md` ✓
- [x] Room Lifecycle state machine (Mermaid)
- [x] Match Lifecycle in Tournament (Mermaid)
- [x] Turn lifecycle + all three timer window types (ASCII timeline)
- [x] EventStorming board: Game Session happy path (ASCII)
- [x] EventStorming board: Tournament Round Progression (ASCII)
- [x] Disconnect/Reconnect/Forfeit flow (Mermaid state diagram)
- [x] Identity & Session + abuse escalation flow (ASCII)
- [x] Cross-context event flow summary (ASCII)

---

## Phase 4 — Closure

### Step 10: `design/REQUIREMENTS_TRACEABILITY.md` ✓
- [x] One-to-one map: every assignment deliverable bullet → file + section
- [x] EventStorming methodology coverage mapped
- [x] Validated requirements vs open assumptions clearly separated (15 validated, 10 open)
- [x] Cross-reference consistency validation (19 rules checked, all consistent)

---

## Final File Layout

```
README.md                            ← root index (step 2)
specs/
  RULESET.md                         ✓ complete
  CONSTRAINTS.md                     ✓ complete
  TOURNAMENT_RULES.md                ✓ complete
  ASSUMPTIONS.md                     ✓ complete
design/
  PLAN.md                            ← this file
  GLOSSARY.md                        ← step 1
  CONTEXT_MAP.md                     ← step 3
  DOMAIN_MODEL.md                    ← step 4
  COMMANDS_EVENTS.md                 ← step 5
  EVENT_FLOWS.md                     ← step 6
  FAILURE_PATHS.md                   ← step 7
  CONSISTENCY_RECOVERY.md            ← step 8
  ASCII_FLOW.md                      ← step 9
  REQUIREMENTS_TRACEABILITY.md       ← step 10
```

---

## Phase Sequencing Rationale

Each phase depends on the previous:
1. **Glossary** establishes shared language — everything else references it
2. **Context map + domain model** defines who owns what and which boundaries exist
3. **Commands/events + flows** give the behavioral contract within those boundaries
4. **Failure paths + consistency** use that contract to handle every deviation
5. **Traceability** proves the whole package covers the assignment rubric
