# UnoArena — Design Assumptions & Open Decisions

This document records all assumptions made during the domain design phase and open decisions deferred to implementation or later design iterations. It corresponds to deliverable 8 of the assignment.

---

## 1. Connection Semantics Assumptions

- **Delivery guarantee**: the platform assumes **at-least-once delivery** for all server-to-client event pushes. Clients must tolerate receiving duplicate events.
- **Idempotency**: every client command carries a client-generated UUID (idempotency key). If the server receives the same UUID twice, it returns the original outcome without reprocessing.
- **Event ordering**: events within a single game are delivered in strict causal order, enforced by the state version sequence number (see [CONSTRAINTS.md — Section 9](./CONSTRAINTS.md)). Cross-game event ordering is not guaranteed.
- **Client push mechanism**: the system assumes a persistent server-to-client push channel (e.g., SSE or equivalent) for real-time game state updates. The exact protocol is deferred to the next design iteration.
- **Reconnection state sync**: on reconnection, a client is assumed to receive a full current-state snapshot followed by a replay of any events it missed. Delivery of this snapshot is assumed to be reliable (retried until acknowledged by the client).
- **Clock skew**: all timestamps used for timer resolution (Uno! window, Wild Draw Four window, turn timer, reconnection window) are **server-generated**. Client clocks are not trusted.

---

## 2. Concurrency and Stale Command Model

- A **state version number** per game is the primary concurrency control mechanism (see [CONSTRAINTS.md — Section 9](./CONSTRAINTS.md)).
- **Rejected stale commands** result in a conflict response visible to the client. Clients are responsible for reconciling and retrying if the intended action is still valid in the current state.
- **No distributed transaction** is assumed between bounded contexts (e.g., Room Gameplay and Ranking). Cross-context consistency is achieved via eventual consistency through domain events with idempotent consumers.
- **Timer enforcement is server-side**: the server enforces all timers authoritatively. Client-side timers are for UI feedback only and do not affect server decisions.

---

## 3. Elo Formula Rationale

### 3.1 Casual Multi-Player Elo

The placement-based multi-player Elo extension (defined in [CONSTRAINTS.md — Section 5.2](./CONSTRAINTS.md)) is a standard adaptation of the two-player Elo model for N-player zero-sum rankings. It treats each player's final rank as the outcome of N−1 virtual one-on-one matches against every other participant.

**Design choices and rationale:**

| Choice | Rationale |
|---|---|
| Placement-based actual score | Directly rewards finishing position; aligns with competitive intent |
| Pairwise expected score | Preserves the standard Elo property: rating differences predict win probability |
| Divisor (N−1) for expected score | Normalizes to [0, 1] range, maintaining the same K-factor interpretation as two-player Elo |
| K-factor decay (32 → 16 → 12) | Standard "provisional player" pattern: larger adjustments early in a player's history, smaller once rating is stable |
| +3 points bonus for dominant score | Prevents two players with identical placements but very different point totals from receiving identical Elo adjustments; small enough not to distort rankings |
| Forfeit = last place | Consistent with the rule that no Elo update occurs for voided games; forfeiting is a definitive loss |

**Example** (3-player game, ratings 1200 / 1000 / 800, final ranks 2nd / 1st / 3rd):

- Player B (1000, 1st): S = (3−1)/(3−1) = 1.0; E ≈ 0.5; K=16; ΔR ≈ +8.0
- Player A (1200, 2nd): S = (3−2)/(3−1) = 0.5; E ≈ 0.65; K=12; ΔR ≈ −1.8
- Player C (800, 3rd): S = (3−3)/(3−1) = 0.0; E ≈ 0.35; K=32; ΔR ≈ −11.2

### 3.2 Tournament-Placement Elo

Defined in [TOURNAMENT_RULES.md — Section 8](./TOURNAMENT_RULES.md). The same pairwise model is applied post-tournament across all T participants using final placement as the ranking input.

**Design choices:**

| Choice | Rationale |
|---|---|
| Applied once post-tournament | All metrics (placement, rounds reached, win rates) are fully available; avoids mid-tournament Elo distortions |
| K = 40 (higher than casual) | Tournament outcomes carry more weight; reflects the commitment and skill required to compete across multiple rounds |
| Placement bucket for same-round eliminees | Players eliminated in the same round are genuinely peers; sub-ordering by win rate provides finer granularity without inventing artificial ranking |
| Forfeit = worst placement in elimination round | Consistent with the tournament forfeit rule (permanent elimination); does not disadvantage players who lost fairly |

---

## 4. Regional Matchmaking Assumptions

- Region assignment at registration is **self-selected** and treated as immutable after the player's first 30 days. Region changes after that period require admin review.
- **Cross-region matching thresholds** (how long the matchmaking system waits before expanding the regional search radius) are an implementation detail deferred to the infrastructure design phase.
- For tournament matchmaking, region preference is secondary to qualifier pool availability — once the round-start threshold is reached, rooms may be formed cross-region to avoid indefinite waiting.

---

## 5. Game Log Contents

The post-game public log records all of the following:

- Every card played, including card identity (color, type, value) and the player who played it.
- Every card drawn (from draw pile or penalty), with card identity attributed to the drawing player.
- All Uno! calls (player, timestamp) and challenge outcomes (challenger, result, penalty applied).
- Wild Draw Four plays, challenge declarations, the accused player's hand composition as verified server-side (not shown to any player during the game — becomes public post-game), and challenge outcomes.
- Turn advances, skips (from Skip cards, Draw Two, Wild Draw Four), direction changes, jump-in events.
- Disconnection events, reconnection events, forfeit events, AFK forfeit triggers.
- Round-end events with scores; game-end events with final standings.
- Match-end events (tournament) with game win counts and advancement decisions.

**Note on Wild Draw Four hand reveal**: the accused player's hand, which is revealed exclusively to the challenger during an active game (see [CONSTRAINTS.md — Section 4.2](./CONSTRAINTS.md)), **becomes part of the public post-game log**. This is intentional for dispute resolution, replay integrity, and audit purposes.

---

## 6. Authentication Model

Authentication uses a **hybrid JWT + server-side invalidation record** approach (Option 3).

### Mechanism

1. On login, the server issues a signed JWT containing the player ID and an `issued_at` timestamp.
2. The server writes a single record per player to a central store: `{ player_id → valid_sessions_from: <timestamp> }`.
3. On every authenticated request, the server:
   - Verifies the JWT signature (stateless).
   - Reads the player's `valid_sessions_from` record and rejects the token if `issued_at` predates it.

### Single-session enforcement

When a player logs in from a new device:
- A new JWT is issued with the current timestamp.
- `valid_sessions_from` is updated to that timestamp.
- All tokens issued before that timestamp are now invalid — including any active session on another device.
- If the invalidated session was in an active game, the standard 60-second reconnection window applies (see [CONSTRAINTS.md — Section 2.5](./CONSTRAINTS.md)).

### Design rationale

| Property | Benefit |
|---|---|
| JWT for signature verification | No store lookup needed to verify token integrity; scales horizontally |
| One record per player (not per token) | Minimal storage; instant invalidation without a growing blocklist |
| Server-side `valid_sessions_from` | Cleanly enforces the single-session invariant on new login |
| Server-generated timestamps | Consistent with the general rule that client clocks are not trusted |

---

## 7. Open Decisions (Deferred)



| # | Decision | Notes |
|---|---|---|
| 1 | Exact client connection protocol (SSE, WebSocket, long-poll, etc.) | Deferred to next design iteration per assignment scope constraints |
| 2 | Cross-region matching wait duration before expanding radius | Implementation / infrastructure detail |
| 3 | K-factor fine-tuning after launch | Can be adjusted based on observed rating distribution and inflation/deflation |
| 4 | Matchmaking queue window duration for Quick Play | Implementation detail; affects lobby fill speed vs. Elo precision |
| 5 | Admin tooling and UI | Out of scope for domain design |
| 6 | Ban escalation tiers beyond the 7-day window | Implementation detail (CONSTRAINTS.md Section 10 defines up to that point) |
| 7 | Region change policy details | Currently: immutable after 30 days, admin review required; exact appeal process TBD |
| 8 | Exact formula for "adjacent region" expansion timing in matchmaking | Implementation detail; may be Elo-range-dependent |
| 9 | Whether partial-room game results contribute to the public game log and dispute system | Domain decision: currently assumed yes, but no special rules apply |
| 10 | Behavior when a tournament admin-cancel occurs mid-round (partial Elo for completed games?) | Currently: no Elo applied for any game in a cancelled tournament; may be reconsidered |

**Resolved decisions (previously open):**

| # | Decision | Resolution |
|---|---|---|
| R1 | Casual tiebreak: shared position vs. randomized | **Randomized** — tied players (equal points and card count) are assigned distinct positions randomly. No shared-position concept in rankings or Elo. |
| R2 | Tournament match format: best-of-three vs. fixed three games | **Best-of-Three (Bo3)** — up to 3 games are played; the match ends early if any player reaches 2 game wins, otherwise it ends after Game 3. |
| R3 | Tournament advancement criterion: game wins vs. cumulative points | **Match wins first**. Advancement uses game wins, then tie-breaks by lower cumulative card-point burden (sum of remaining card values as non-negative totals), then lower cumulative cards remaining. |
| R4 | Voluntary disconnect handling | **60-second reconnection window** applies to all disconnections regardless of whether voluntary or involuntary. Immediate forfeit requires an explicit forfeit command. |
| R5 | No-show handling in Round 2+ tournament lobbies | Same rule as Round 1 applies to all rounds: absent player is treated as forfeited before the game starts. |
| R6 | Wild Draw Four challenge hand reveal | Hand is **never revealed** to any player during the game. Verification is server-side only; hand composition appears in the post-game public log. |
| R7 | Match continuation when forfeits leave 1 player | Remaining games are not played; the sole player wins the match. Forfeited players rank below all active players regardless of match wins or tie-break metrics. |
| R8 | Multi-card draw when draw pile is insufficient | Server pre-checks draw pile size before the draw begins and appends a reshuffled discard pile if needed; if still insufficient, remaining penalty is waived. |
| R9 | Session reconnection definition | Reconnection is complete only when session is re-established **and** game state is fully synchronized. |
| R10 | Tournament Elo formula inputs | Formula uses final placement only. Rounds reached and win rates are profile statistics used solely to sub-order same-round eliminees for placement bucketing. |
| R11 | Authentication mechanism | **JWT + server-side invalidation record** — JWT for stateless signature verification; one `valid_sessions_from` timestamp per player enforces single-session rule. See Section 6. |
