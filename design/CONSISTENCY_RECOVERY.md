# UnoArena — Consistency & Recovery Strategy

This document defines the consistency model for each bounded context, the retry and deduplication strategy per message type, compensation and saga decisions for cross-context workflows, invariant violation prevention per aggregate, and reconciliation procedures for read model lag. All terms follow [GLOSSARY.md](./GLOSSARY.md).

---

## 1. Consistency Model Overview

UnoArena uses two distinct consistency levels:

| Level | Scope | Mechanism |
|---|---|---|
| **Strong consistency** | Within a single aggregate | Optimistic concurrency via `state_version`; all commands are serialized; no two accepted commands produce the same version |
| **Eventual consistency** | Across bounded contexts | Domain events with at-least-once delivery; idempotent consumers; no distributed transactions |

**Core principle:** No operation requires a distributed transaction spanning two contexts. Cross-context consistency is achieved entirely through event-driven propagation with idempotent consumers and compensating events.

---

## 2. Retry & Deduplication Strategy

### 2.1 Client-to-Server Commands (inbound)

All write commands carry two safety mechanisms:

| Mechanism | Field | Behavior |
|---|---|---|
| **Optimistic concurrency** | `state_version` | Command rejected with 409 if version does not match server state. Client reconciles via event stream and retries with updated version if action is still valid. |
| **Idempotency key** | `idempotency_key` (UUID) | If the same UUID is received twice, the server returns the cached outcome without reprocessing. Cache TTL must exceed the maximum expected network retry window. |

**Deduplication key per command type:**

| Command | Dedup key |
|---|---|
| `PlayCard`, `DrawCard`, `JumpIn`, `DrawStackPenalty` | `idempotency_key` UUID |
| `CallUno`, `ChallengeUno`, `ChallengeWildDrawFour` | `idempotency_key` UUID |
| `Forfeit` | `idempotency_key` UUID (subsequent forfeits return original outcome) |
| `Login` | `player_id` + `issued_at` timestamp |
| `Register` | `username` (unique constraint) |
| `RegisterForTournament` | `player_id` + `tournament_id` |
| `VoidGameResult` | `game_id` (cannot be voided twice) |
| `CancelTournament` | `tournament_id` (cannot be cancelled twice) |

---

### 2.2 Cross-Context Event Delivery (outbound)

All domain events are delivered with **at-least-once** semantics. Every consumer must be idempotent.

| Event | Producer | Consumers | Dedup strategy at consumer |
|---|---|---|---|
| `GameCompleted` | Room Gameplay | Ranking, Tournament Orchestration, Spectator View | Keyed by `game_id`; consumer checks whether this game has already been processed before applying changes |
| `MatchCompleted` | Tournament Orchestration | TournamentRound, Spectator View | Keyed by `match_id` |
| `TournamentCompleted` | Tournament | Ranking, Spectator View | Keyed by `tournament_id`; Elo update applied once per tournament per player |
| `TournamentCancelled` | Moderation → Tournament | Ranking, Spectator View | Keyed by `tournament_id`; revert is idempotent (tracks reverted game IDs) |
| `GameResultVoided` | Moderation | Ranking, Spectator View | Keyed by `game_id`; revert is idempotent |
| `SessionInvalidated` | Identity/Session | Room Gameplay | Keyed by `player_id` + `invalidated_at`; reconnection window started at most once per invalidation event |
| `ReconnectionWindowExpired` | Identity/Session | Room Gameplay | Keyed by `player_id` + `game_id`; forfeit issued at most once per window expiry |
| `PlayerBanned` / `PlayerSuspended` | Identity/Session | Room Gameplay, Tournament Orchestration | Keyed by `player_id` + `timestamp` |
| `EloUpdated` | Ranking | Spectator View | Keyed by `player_id` + `game_id`; leaderboard updated at most once per game per player |
| `AdvancementResolved` | Tournament Orchestration | TournamentRound, Spectator View | Keyed by `tournament_id` + `round_number` + `room_id` |

**Retry policy:** Failed event deliveries are retried with exponential backoff. Events are not dropped — they remain in the delivery queue until acknowledged by the consumer. This is the at-least-once guarantee.

---

## 3. Saga & Compensation Decisions

A saga is a sequence of local transactions across multiple aggregates/contexts, where each step produces an event that triggers the next. If a step fails, a compensating action undoes the work done so far.

### 3.1 Casual Game Completion → Elo Update

```
Step 1: GameSession emits GameCompleted           [Room Gameplay]
Step 2: Ranking consumes GameCompleted            [Ranking]
        → computes and applies EloUpdated         [Ranking]
Step 3: Spectator View updates LeaderboardView    [Spectator View]

Compensation (triggered by GameResultVoided):
  Step C1: Moderation emits GameResultVoided
  Step C2: Ranking consumes GameResultVoided
           → issues EloReverted for all players in the game
  Step C3: Spectator View updates LeaderboardView
```

**Failure handling:**
- If Step 2 fails (Ranking down): event retried; Ranking processes idempotently on recovery.
- If Step 3 fails: LeaderboardView eventually catches up; no game integrity impact.
- No compensation needed for delivery failures — idempotent retry is sufficient.

---

### 3.2 Tournament Game Completion → Match Progression → Round Advancement

```
Step 1: GameSession emits GameCompleted           [Room Gameplay]
Step 2: Match consumes GameCompleted              [Tournament Orchestration]
        → emits MatchWinAwarded
        → [if early end] emits MatchEndedEarly → MatchCompleted
        → [if Game 3] emits MatchEndedAfterGame3 → MatchCompleted
Step 3: TournamentRound consumes MatchCompleted   [Tournament Orchestration]
        → emits AdvancementResolved
        → [if all rooms done] emits RoundCompleted
Step 4: Tournament consumes RoundCompleted        [Tournament Orchestration]
        → [if ≤10 players] emits FinalRoomCreated
        → [else] emits RoundStarted (next round)

Safety net: MatchTimeoutReached fires after 20 minutes regardless of Step 1–2 delivery.
```

**Failure handling:**
- If Step 2 fails (Match consumer down): event retried. If the 20-minute timeout fires first, `MatchTimeoutReached` resolves the active game and ends the match — this is the intended safety net, not an error condition.
- If Step 3 fails mid-accumulation (some `AdvancementResolved` processed, some not): idempotent processing on recovery; already-processed rooms are skipped by their `room_id` dedup key.
- If Step 4 fails after `RoundCompleted`: `Tournament` replays its event log on recovery; `RoundCompleted` is reprocessed idempotently.

**No compensation needed:** Tournament progression is forward-only. There is no rollback of advancement — once a player advances, they stay in the next round unless the entire tournament is cancelled (covered in 3.3).

---

### 3.3 Tournament Cancellation → Elo Revert (Compensating Saga)

```
Step 1: Admin emits TournamentCancelled           [Moderation]
Step 2: Tournament Orchestration marks cancelled  [Tournament Orchestration]
        → stops all active rooms and matches
Step 3: Ranking consumes TournamentCancelled      [Ranking]
        → queries all EloUpdated events for tournament_id
        → issues EloReverted for each affected player/game
Step 4: Spectator View updates LeaderboardView    [Spectator View]
```

**Failure handling:**
- If Step 3 partially completes (some EloReverted issued, then Ranking crashes): on recovery, Ranking replays from `TournamentCancelled`; already-reverted game IDs are skipped (idempotent).
- Ranking tracks a `revert_completed` flag per `tournament_id` to detect and skip fully processed cancellations.

---

### 3.4 Session Invalidation → In-Game Reconnection Window

```
Step 1: PlayerSession emits SessionInvalidated    [Identity/Session]
Step 2: Room Gameplay receives SessionInvalidated [Room Gameplay]
        → emits PlayerDisconnected
        → emits ReconnectionWindowStarted (60s)
Step 3a: Player reconnects within 60s
         → PlayerReconnected; turns resume
Step 3b: Window expires
         → ReconnectionWindowExpired → PlayerForfeited
```

**Failure handling:**
- If Step 2 fails (Room Gameplay misses `SessionInvalidated`): the player's connection is physically gone; Room Gameplay detects this via heartbeat timeout and emits `PlayerDisconnected` independently. The two paths converge on the same outcome.
- If `ReconnectionWindowExpired` is delivered twice: second delivery is idempotent — forfeit already issued, second attempt is a no-op.

---

### 3.5 Player Ban → Active Game Removal

```
Step 1: Moderation issues SuspendPlayer/BanPlayer [Moderation]
Step 2: Identity/Session emits PlayerBanned       [Identity/Session]
        → SessionInvalidated
Step 3: Room Gameplay receives PlayerBanned        [Room Gameplay]
        → PlayerForfeited (ban = immediate forfeit in any active game)
Step 4: Tournament Orchestration receives PlayerBanned [Tournament Orchestration]
        → player permanently eliminated from any active tournament
```

**Failure handling:**
- Steps 3 and 4 are independent consumers; partial failure in one does not block the other.
- If Room Gameplay misses `PlayerBanned`: the session is already invalidated; the player cannot act. Their next missed turn triggers the disconnection flow naturally.

---

## 4. Invariant Violation Prevention Per Aggregate

### 4.1 GameSession

| Invariant | Prevention mechanism |
|---|---|
| Only the active player may play or draw | `turn_index` check on every game command; rejected if submitter ≠ current player (except jump-in and challenge commands) |
| Cards must be legal plays | Legal play validation before state change; WD4 hand check performed server-side |
| `state_version` is strictly monotonic | Single-threaded command processing per game; version incremented atomically with state change |
| At most one challenge per window | `ChallengeWindow` tracks whether a challenge has been issued; second challenge rejected |
| Game ends immediately when a hand reaches zero | Post-play check after every `PlayCard`; `GameCompleted` is emitted before `TurnAdvanced` if the condition is met |
| Forfeited players cannot act | `PlayerHand` removed from `GameSession` on forfeit; all subsequent commands from that player_id rejected |

### 4.2 Room

| Invariant | Prevention mechanism |
|---|---|
| Lifecycle transitions are one-way | State machine enforcement: `waiting → lobby → in_progress → completed`; no reverse transitions |
| Lobby timer only starts at 5+ players | Player count checked before emitting `LobbyTimerStarted` |
| Game only starts with 2+ players | Timer expiry handler checks active player count; cancels room if < 2 |
| No active player joins an in_progress game | Status check on `JoinAsSpectator` vs player join; in_progress rooms reject new active players |

### 4.3 Match

| Invariant | Prevention mechanism |
|---|---|
| At most 3 games per match | Game sequence number tracked; Game 4 is never started |
| Match ends immediately at 2 wins | `MatchWinAwarded` handler checks whether any player reached 2; `MatchEndedEarly` emitted before next game starts |
| Forfeited players rank below all active players | `MatchStanding.forfeited` flag set on forfeit; ranking sort places forfeited players after all non-forfeited |
| Timeout ends the match irrevocably | `timeout_deadline` checked server-side; `MatchTimeoutReached` emitted regardless of game state |

### 4.4 Tournament

| Invariant | Prevention mechanism |
|---|---|
| Minimum 1,000 confirmed players to start | Confirmed player count checked at start time; tournament does not emit `TournamentStarted` if below threshold |
| `total_rounds` is immutable after start | Computed once at `TournamentStarted`; stored as a value, never recomputed |
| A player participates in at most one tournament at a time | `registered_players` checked against active tournament participation list at `RegisterForTournament` time |
| Final Room created exactly once | `FinalRoomCreated` is only emitted when transitioning from `RoundCompleted` to ≤10 players; flag set to prevent double-emission |

### 4.5 PlayerSession

| Invariant | Prevention mechanism |
|---|---|
| At most one valid session per player | `valid_sessions_from` updated atomically on every new login; all prior tokens are invalidated immediately |
| Reconnection window is created at most once per disconnection event | `ReconnectionWindowStarted` deduped by `player_id` + `invalidated_at`; duplicate `SessionInvalidated` delivery does not open a second window |
| Reconnection is only valid within the 60-second window | `expires_at` checked server-side on `ReconnectToGame`; no client-side timer is trusted |

### 4.6 EloRecord

| Invariant | Prevention mechanism |
|---|---|
| Casual Elo updated only for completed, non-voided casual games | Consumer checks `game_type: casual` and `voided: false` before applying `EloUpdated`; dedup by `game_id` |
| Tournament Elo updated only once per tournament, after full completion | Consumer checks `TournamentCompleted` (not mid-round events); dedup by `tournament_id` |
| Forfeiting player assigned last place for Elo | Forfeit flag in `GameCompleted` payload; Ranking assigns rank N before computing deltas |

---

## 5. Projection Reconciliation

Read models in Spectator View are eventually consistent. The following procedures apply when a projection falls behind or must be rebuilt.

### 5.1 PublicGameView (live game state)

**Normal operation:** Updated in near real-time as events arrive from Room Gameplay.

**Lag recovery:** If the consumer falls behind, events are buffered in delivery order (guaranteed by state version). On catchup, events are replayed in state_version order; the projection is rebuilt incrementally.

**Full rebuild trigger:** If the projection is corrupted or lost, it is rebuilt by replaying all events for the `game_id` from the event log, in state_version order. The whitelist filter is applied on replay identically to live processing.

**Consistency guarantee:** `PublicGameView` is always a valid suffix of the event log — it may lag but it never diverges or skips events.

---

### 5.2 LeaderboardView (Elo rankings)

**Normal operation:** Updated on each `EloUpdated` event (emitted by Ranking for both casual and tournament Elo updates; distinguished by `game_type: casual | tournament` in the payload).

**Lag recovery:** Ranking events are replayed in delivery order. Idempotent: if an `EloUpdated` event is applied twice, the second application detects the `game_id` was already processed and is a no-op.

**Reconciliation against source of truth:** If the leaderboard diverges from the Ranking context's own data (detectable by a periodic scan), the leaderboard is rebuilt from the current Elo values in all `EloRecord` aggregates. This is a point-in-time snapshot rebuild, not a full event replay.

---

### 5.3 BracketView (tournament progression)

**Normal operation:** Updated on `TournamentRoomAssigned`, `MatchCompleted`, `AdvancementResolved`, `RoundCompleted`.

**Lag recovery:** Tournament Orchestration events are replayed in causal order. BracketView can be rebuilt from `TournamentStarted` through all subsequent round and room events for a given `tournament_id`.

**Partial round display:** BracketView updates progressively as rooms complete within a round — it does not wait for the full round to finish. Spectators see partial results in real time.

---

### 5.4 PublicGameLog (post-game audit record)

**Sealed on completion:** `PublicGameLog` is built by processing all events for a `game_id` from `GameStarted` through `GameCompleted`. It is immutable after sealing.

**If GameCompleted is delivered twice:** Idempotent — log sealed flag prevents second processing.

**If log is lost after sealing:** Rebuilt from the event log for the `game_id`. All events including `WildDrawFourChallengeResolved` (with `accused_hand_at_time`) are included in the rebuild — this data is permanently retained in the event log.

---

## 6. Deduplication Window & Cache TTL

| Context | Dedup cache scope | Suggested TTL |
|---|---|---|
| GameSession command idempotency | Per `game_id` + `idempotency_key` | Duration of game + 24h buffer |
| Ranking `EloUpdated` dedup (casual, `game_type: casual`) | Per `game_id` | Permanent (game results never expire) |
| Ranking `EloUpdated` dedup (tournament, `game_type: tournament`) | Per `tournament_id` | Permanent |
| Ranking `EloReverted` dedup | Per `game_id` + `tournament_id` | Permanent |
| TournamentRound `AdvancementResolved` dedup | Per `tournament_id` + `round_number` + `room_id` | Duration of tournament + 7 days |
| Session invalidation dedup | Per `player_id` + `invalidated_at` | 24h (reconnection window is 60s) |

**Note:** TTL values are domain-level recommendations. Actual cache implementation (in-memory, Redis, database record) is an infrastructure decision deferred to the implementation phase.
