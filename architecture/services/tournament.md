# Tournament Orchestration Service

**Bounded context:** Tournament Orchestration  
**Phase:** 3  
**Dependencies:** [PLAN.md](../PLAN.md) resolved decisions R3, R6; O2 (one service); O5 settled as Kafka partitioned fan-out.

---

## 1. Purpose and Scope

Tournament Orchestration owns the full tournament lifecycle, from registration through champion declaration. It is the only context that orchestrates cross-game workflows: tracking Bo3 match state, deciding when to start the next game, and advancing qualifiers through successive rounds.

**Owns:**
- `Tournament` aggregate — lifecycle, registration, round sequencing, champion
- `TournamentRound` aggregate — qualifier pool, room formation, phase-start threshold, advancement
- `Match` aggregate — Bo3 game sequencing, match win accounting, 20-minute timeout
- Round-kickoff fan-out (100K room creation surge at `StartTournament`)
- Match timeout timer

**Does NOT own:**
- Game state within individual games (Room Gameplay)
- Player identity or session validity (Identity/Session)
- Elo computation (Ranking)
- Spectator projections (Spectator View)
- Casual matchmaking (Room Gameplay)

---

## 2. Containers

| Container | Type | Responsibility |
|---|---|---|
| `tournament-service` | Long-running HTTP service | Tournament lifecycle commands, registration management, match state tracking, round advancement |
| `tournament-outbox-relay-worker` | In-process background thread | Reads undelivered outbox rows, publishes to `tournament-events` Kafka topic, marks rows delivered |
| `kickoff-outbox-relay-worker` | In-process background thread | Reads undelivered kickoff-outbox rows, publishes to `tournament-kickoff` Kafka topic at rate-limited pace (≤1,000 rooms/s); separate from the main outbox relay to allow independent rate control |
| `match-timer-worker` | In-process background thread | Subscribes to Redis keyspace expiry notifications for `tournament:match-timeout:*` keys; triggers `ForceCompleteGame` on expiry |
| `game-events-consumer-worker` | In-process background thread | Consumes `game-events` Kafka topic (consumer group `tournament-game-cg`) for `GameCompleted`, `PlayerForfeited`, `GameStarted` |
| `identity-events-consumer-worker` | In-process background thread | Consumes `identity-events` Kafka topic (consumer group `tournament-identity-cg`) for `PlayerSuspended`, `PlayerBanned` |

All six run in the same deployed container. No separate deployment for background workers.

---

## 3. Public Synchronous Interfaces

Base path: `/v1/` (all endpoints require a valid JWT unless noted; admin endpoints require an additional admin role claim in the JWT).

### 3.1 Tournament Lifecycle Commands (via API Gateway)

| Command | Method + Path | Auth | Notes |
|---|---|---|---|
| `CreateTournament` | `POST /v1/admin/tournaments` | Admin JWT | `{scheduled_start, registration_opens_at, registration_closes_at}`; idempotent by `tournament_id` |
| `RegisterForTournament` | `POST /v1/tournaments/{tournament_id}/register` | Player JWT | Idempotent by `(tournament_id, player_id)` |
| `WithdrawFromTournament` | `DELETE /v1/tournaments/{tournament_id}/register` | Player JWT | Idempotent — no-op if not registered |
| `CloseRegistration` | `POST /v1/admin/tournaments/{tournament_id}/close-registration` | Admin JWT or system scheduler | Idempotent — no-op if already closed |
| `StartTournament` | `POST /v1/admin/tournaments/{tournament_id}/start` | Admin JWT or system scheduler | Precondition: `confirmed_players ≥ 1,000`; idempotent |

The `CloseRegistration` and `StartTournament` commands are also triggered automatically by a system scheduler at the times recorded in `tournaments.registration_closes_at` and `tournaments.scheduled_start`. The scheduler makes the same HTTP call as an admin would. Both calls are idempotent.

Responses follow standard HTTP semantics (`200 OK`, `409 Conflict` on duplicate, `422` on precondition failure such as fewer than 1,000 confirmed players).

### 3.2 Internal Commands (from Moderation — mTLS, not via API Gateway)

| Command | Method + Path | Notes |
|---|---|---|
| `CancelTournament` | `POST /v1/internal/tournaments/{tournament_id}/cancel` | `{cancelled_by_admin_id, reason}`; idempotent; stops kickoff if in-progress, marks all active matches as cancelled |

---

## 4. Public Asynchronous Interfaces

### 4.1 Events Produced on `tournament-events` topic

**Partitioned by:** `tournament_id`  
**Produced via:** `tournament-outbox-relay-worker`  
**Schema version:** `schema_version: 1` on all events

| Event | Idempotency key | Primary consumers |
|---|---|---|
| `TournamentCreated` | `tournament_id` | — |
| `RegistrationOpened` | `tournament_id` | Spectator View |
| `RegistrationClosed` | `tournament_id` | Spectator View |
| `TournamentStarted` | `tournament_id` | Spectator View |
| `RoundStarted` | `(tournament_id, round_number)` | Spectator View |
| `PhaseStartThresholdReached` | `(tournament_id, round_number)` | Spectator View |
| `TournamentRoomAssigned` | `room_id` | Spectator View (bracket display) |
| `LoneQualifierAdvanced` | `(tournament_id, round_number, player_id)` | Spectator View |
| `MatchStarted` | `match_id` | Spectator View |
| `GameInMatchStarted` | `(match_id, game_sequence_number)` | Spectator View |
| `MatchWinAwarded` | `(match_id, player_id, game_sequence_number)` | Spectator View |
| `MatchEndedEarly` | `match_id` | Spectator View, TournamentRound (internal) |
| `MatchEndedAfterGame3` | `match_id` | Spectator View, TournamentRound (internal) |
| `MatchTimeoutReached` | `match_id` | Spectator View, TournamentRound (internal) |
| `MatchCompleted` | `match_id` | Spectator View |
| `AdvancementResolved` | `(tournament_id, round_number, room_id)` | Spectator View |
| `RoundCompleted` | `(tournament_id, round_number)` | Spectator View |
| `FinalRoomCreated` | `(tournament_id, room_id)` | Spectator View |
| `TournamentCompleted` | `tournament_id` | Ranking, Spectator View |
| `TournamentCancelled` | `tournament_id` | Ranking, Spectator View |

### 4.2 Events Produced on `tournament-kickoff` topic

**Partitioned by:** `room_id`  
**Produced via:** `kickoff-outbox-relay-worker` (rate-limited to ≤1,000 rooms/s)  
**Retention:** 7 days (same as `game-events`)

| Event | Idempotency key | Consumers |
|---|---|---|
| `TournamentRoomAssigned` | `room_id` | Room Gameplay workers (consumer group `room-gameplay-kickoff-cg`) |

`TournamentRoomAssigned` payload: `{tournament_id, round_number, room_id, player_ids: List<player_id>}`. The `player_ids` list contains all players assigned to this room — Room Gameplay uses this to create the room and assign players atomically without a separate `AssignPlayersToRoom` call.

### 4.3 Events Consumed from `game-events` topic

Consumer group: `tournament-game-cg`

| Event | Action |
|---|---|
| `GameCompleted` | Update `match_standings`; check for match end (§5.1); start next game or emit `MatchCompleted` |
| `PlayerForfeited` | Mark player as permanently eliminated in `qualifier_pools`; check for unconditional advancement (§9) |
| `GameStarted` | Update `matches.active_game_id` to the new game_id; confirms Room Gameplay created the game |

### 4.4 Events Consumed from `identity-events` topic

Consumer group: `tournament-identity-cg`

| Event | Action |
|---|---|
| `PlayerSuspended` | If player is in an active tournament game: mark as eliminated in `qualifier_pools`; the ongoing game will produce `PlayerForfeited` via Room Gameplay's own consumption of `PlayerSuspended` |
| `PlayerBanned` | Same as `PlayerSuspended` |

---

## 5. Match Series Coordination

### 5.1 GameCompleted Processing

When `GameCompleted(game_id, match_id, placements, forfeited, game_type: tournament, ...)` arrives from `game-events`:

```
1. Acquire SELECT FOR UPDATE on matches WHERE match_id = $match_id
   (serializes all GameCompleted events for the same match)

2. Look up match_games to confirm this game_id belongs to this match and is not
   already processed (idempotency: if match_games[game_id].status = 'completed' → skip)

3. Update match_standings for each player:
   - Add game winner's match_wins += 1 (game winner = player at placements[0])
   - Add cumulative_card_point_burden from each player's result
   - Add cumulative_finish_time from each player's finish_timestamp
   - Set forfeited = true for each player in forfeited list

4. Determine match outcome:
   a. Any player has match_wins = 2 → MatchEndedEarly
   b. game_sequence_number = 3 → MatchEndedAfterGame3
   c. Otherwise → start next game (§5.2)

5. BEGIN transaction:
   - UPDATE match_games SET status = 'completed'
   - UPDATE match_standings
   - If match ends (cases a or b):
       UPDATE matches SET status = 'completed'
       INSERT tournament_outbox: MatchWinAwarded (winner only)
       INSERT tournament_outbox: MatchEndedEarly | MatchEndedAfterGame3
       INSERT tournament_outbox: MatchCompleted (with final_standings, qualifiers)
       INSERT tournament_outbox: AdvancementResolved (top 3 qualifiers)
       UPDATE qualifier_pools: set qualifiers to 'advanced', others to 'eliminated'
       [Check round completion — §5.3]
   - If next game (case c):
       INSERT tournament_outbox: MatchWinAwarded (if this game produced a win)
       [StartNextGameInRoom HTTP call made before commit — see §5.2]
   COMMIT

6. Release row lock
```

**Idempotency:** dedup key `game_id` per match. If `match_games[game_id].status = 'completed'` on entry, the entire handler is a no-op.

### 5.2 Starting the Next Game (Bo3 Game 2/3)

When case (c) above applies (match not yet decided, game < 3):

```
HTTP POST /v1/internal/rooms/{room_id}/games
Body: {
  match_id: M1,
  game_sequence_number: 2,   // or 3
  idempotency_key: uuid
}
→ Room Gameplay creates new GameSession (same players, no lobby timer, immediate deal)
→ Returns 200 OK with {game_id: G2}
```

The call is made **before** the transaction commit (so the new `game_id` can be stored in the outbox for `GameInMatchStarted`). Room Gameplay's `StartNextGameInRoom` is idempotent by `(room_id, game_sequence_number)` — if called twice, the second returns the existing `game_id`.

After the HTTP call returns, within the same transaction:
```
INSERT match_games (match_id, game_id=G2, sequence_number=2, status='in_progress')
UPDATE matches SET active_game_id = G2, game_sequence = 2
INSERT tournament_outbox: GameInMatchStarted {match_id, game_id: G2, sequence_number: 2}
```

The match timer is NOT reset on new game — the 20-minute match timeout runs from `MatchStarted`, not from each individual game start.

> **Design note — pre-commit ordering:** The `StartNextGameInRoom` HTTP call is intentionally issued *before* the tournament-service transaction commits. This minimises the gap between consecutive games in a Bo3 match: the new game is created and dealing begins as soon as possible, rather than waiting for the tournament-service commit + outbox relay cycle (~200–500 ms). The cost is a narrow consistency window: if the DB commit fails after the HTTP call succeeds, Room Gameplay has created Game N but tournament-service has no record of it. This window is fully handled by the `GameStarted` reconciliation path described in §5.2.1. An outbox-based alternative (commit first → relay `StartNextGameCommand` event → Room Gameplay creates the game → tournament-service reacts to `GameStarted`) would eliminate the window entirely at the cost of ~300–500 ms additional latency between games. That trade-off was rejected because minimising between-game delay is a player-experience priority in a competitive Bo3 match.

### 5.2.1 Pre-Commit HTTP Call — Failure Recovery

The HTTP call to `StartNextGameInRoom` is issued before the tournament-service transaction commits. If the DB commit fails after the HTTP call succeeds, Room Gameplay has created `G2` but tournament-service has no record of it. This is a real but narrow consistency gap.

**Recovery path:** When `GameStarted` for `G2` arrives via `game-events` (produced by Room Gameplay's outbox relay), tournament-service's `GameStarted` consumer (§4.3) performs a reconciliation check:

1. Look up `match_games` for the `game_id` from the event.
2. If no row exists (tournament-service transaction failed), check whether the `match_id` in the event matches an active match.
3. If the match exists and is `in_progress` at the expected `game_sequence_number`: the row was lost due to a commit failure. Re-insert the `match_games` row and update `matches.active_game_id`. This is idempotent — a duplicate `GameStarted` event triggers the same check and finds the row already exists.
4. If the match does not exist or is `completed`: the game is an orphan. Room Gameplay receives `ForceCompleteGame` from tournament-service's periodic orphan sweep, or the game times out naturally.

This reconciliation ensures that a transient DB commit failure does not permanently strand a game without a parent match. The `GameStarted` consumer is the primary recovery mechanism; an additional startup sweep of `game_sessions` for orphaned games (no matching `match_games` row) provides a fallback.

### 5.3 MatchCompleted → Round Advancement

When `MatchCompleted` is committed (inside the same transaction as §5.1 cases a or b):

```
UPDATE tournament_rounds:
  - Add qualifiers to qualifiers_for_next_round
  - Increment rooms_resolved_count

Check: rooms_resolved_count == total_rooms_in_round?
  → Yes: INSERT tournament_outbox: RoundCompleted {tournament_id, round_number, total_qualifiers}
         Check: qualifiers_for_next_round.size ≤ 10?
           → Yes: INSERT tournament_outbox: FinalRoomCreated
                  [Create the final room via StartNextGameInRoom or CreateRoom HTTP call]
           → No:  INSERT tournament_outbox: RoundStarted {round_number + 1, ...}
                  [kickoff-producer-worker picks up the new round]
  → No:  do nothing (round still in-progress; wait for remaining rooms)
```

This check runs inside the same PostgreSQL transaction as the `MatchCompleted` commit. No separate coordination round is needed — if any two `MatchCompleted` events arrive concurrently, they acquire the `tournament_rounds` row lock sequentially, and each checks the correct count.

---

## 6. Round-Kickoff Surge (O5: Kafka Partitioned Fan-out)

The first-round surge is the highest-throughput event in the system: 100,000 rooms must be created within seconds of `StartTournament`. This section describes the full fan-out path.

### 6.1 Room Assignment Generation

On `StartTournament` (or on `PhaseStartThresholdReached` for subsequent rounds), the `tournament-service` command handler:

1. Computes `total_rounds = ceil(log(confirmed_players / 10) / log(10/3))`.
2. Groups confirmed players into rooms of 10 (final room may have 2–9 players).
3. Assigns deterministic room IDs: `room_id = UUID5(TOURNAMENT_NS, "${tournament_id}:${round_number}:${room_index}")`.
4. In a single PostgreSQL transaction:
   - `INSERT tournament_rounds (status = 'forming')`
   - `INSERT tournament_rooms (room_id, match_id, player_ids JSONB, status = 'pending')` for each room (bulk insert)
   - `INSERT qualifier_pools (player_id, status = 'assigned')` for each player
   - `INSERT kickoff_outbox` for each room (one row per `TournamentRoomAssigned` event)
   - `INSERT tournament_outbox`: `TournamentStarted`, `RoundStarted`, `PhaseStartThresholdReached`
5. COMMIT.

### 6.2 Rate-Limited Kickoff Publication

The `kickoff-outbox-relay-worker` drains `kickoff_outbox` at a controlled rate:

```
Loop every 1ms:
  SELECT id, room_id, payload FROM kickoff_outbox
  WHERE delivered = false
  ORDER BY id
  LIMIT 1000                       -- publish up to 1,000 rooms per tick
  FOR UPDATE SKIP LOCKED;

  For each row:
    Publish to tournament-kickoff topic (key = room_id, value = TournamentRoomAssigned payload)
    using idempotent Kafka producer (enable.idempotence=true, acks=all)

  UPDATE kickoff_outbox SET delivered = true WHERE id IN (...)

  Sleep 0ms if count < 1000 (burst available)
  Sleep 1ms between 1,000-row batches (sustained rate ≤ 1,000 rooms/s at full load)
```

This rate limit (1,000 rooms/s) means all 100K rooms enter the `tournament-kickoff` topic within ~100 seconds. Room Gameplay workers begin consuming immediately, so effective lag between first and last room creation is minimized by the consumer parallelism.

> **Margin note:** 100 seconds to enqueue all rooms leaves ~20 seconds of headroom against a 120-second target before the first lobby timers (10s) would expire on early-created rooms. If the kickoff producer falls behind or rooms require DLQ retry, the margin narrows. Mitigations: (a) the rate limit can be raised to 1,500 rooms/s (67 seconds total) if the PostgreSQL insert throughput on the consumer side allows it; (b) lobby timers are started only after the consumer commits the room, so late-arriving rooms simply get later timer starts — the system remains correct, just with staggered game-start times within a round.

### 6.3 Room Gameplay Consumption

Room Gameplay's `tournament-kickoff-consumer-worker` processes `TournamentRoomAssigned` events:

```
Consumer group: room-gameplay-kickoff-cg
Partitions: ≥100 (by room_id, ensuring even distribution)
Instances: 50–100 room-gameplay-service pods × partition subset

On TournamentRoomAssigned {room_id, player_ids, tournament_id, round_number}:
  BEGIN transaction on gameplay PostgreSQL:
    -- Idempotency check:
    SELECT id FROM rooms WHERE room_id = $room_id
    IF EXISTS → COMMIT (no-op; room already created)

    INSERT rooms (room_id, room_type='tournament', status='waiting',
                  tournament_room_ref={tournament_id, round_number})
    INSERT room_players × len(player_ids)
    INSERT outbox: RoomCreated
    INSERT outbox: PlayerAssignedToRoom × len(player_ids)
    INSERT outbox: LobbyTimerStarted {timer_expires_at: now() + 10s}
      (10s because tournament rooms are pre-filled to exactly their assigned size;
       ≥5 players guarantees timer starts; capacity=10 means reduced timer applies)
    SET gameplay:lobby-lock:{room_id} "uuid" PX 10000 NX
      (distributed lock to prevent double-start if consumer re-delivers this event)
  COMMIT
  SET gameplay:lobby-timer:{room_id} "lobby-uuid" PX 10000 NX
    (Redis timer; outside transaction; crash recovery via startup sweep)
```

**Parallelism:** With 100 partitions and 50 worker pods (each owning 2 partitions), Room Gameplay processes 50 rooms concurrently per poll cycle. At 10ms per room (PostgreSQL insert + Redis write), this yields ~5,000 rooms/s sustainable throughput — enough to consume the 1,000 rooms/s producer rate with headroom.

### 6.4 Thundering-Herd Controls

| Control | Mechanism |
|---|---|
| Producer rate limit | kickoff-outbox-relay-worker enforces ≤1,000 rows/s drain rate |
| Consumer backpressure | Kafka consumer lag is the natural signal; workers never receive faster than they commit to PostgreSQL |
| PostgreSQL write batching | Room Gameplay inserts can batch adjacent rooms within a single transaction if partition locality allows |
| Redis write isolation | Lobby timer key set outside the transaction; `NX` flag prevents duplicate timers |
| Burst tolerance | `tournament-kickoff` topic has 7-day retention; consumers can lag and catch up |

### 6.5 Partial Failure Handling

**Room creation failure (Room Gameplay side):**
- PostgreSQL insert fails → Kafka offset not committed → message re-delivered → idempotent retry.
- After 3 redelivery failures (Kafka DLQ policy): message routed to `tournament-kickoff-dlq` topic.
- `tournament-service` consumes `tournament-kickoff-dlq` (consumer group `tournament-dlq-cg`):
  - If the affected room has exactly 1 player → auto-advance player (`LoneQualifierAdvanced`).
  - If 2–9 players → flag for admin resolution in `room_kickoff_failures` table.
  - Update `tournament_rooms.status = 'failed'`.

**Idempotent room IDs:**
Room IDs are deterministic: `UUID5(namespace, "${tournament_id}:${round_number}:${room_index}")`. A retry with the same room assignment produces the same room ID, hitting the existence check in Room Gameplay → no-op.

---

## 7. Phase-Start Threshold

Each `TournamentRound` has a `phase_start_threshold`: the minimum number of qualifiers that must be present before room formation begins. This prevents starting a round with too few players (e.g., because many matches in the prior round are still in-progress).

**Enforcement:**

```
On MatchCompleted:
  qualifier_pool_size = qualifier_pool_size + len(qualifiers)
  IF qualifier_pool_size >= phase_start_threshold AND round.status = 'pending':
    UPDATE tournament_rounds SET status = 'forming'
    INSERT tournament_outbox: PhaseStartThresholdReached
    [Trigger room formation: INSERT kickoff_outbox for all ready players]
```

**Late qualifiers** (arrive after `PhaseStartThresholdReached`):
- If room formation is still active (kickoff_outbox not fully drained): late qualifiers are added to remaining unfilled rooms or get their own room if ≥2.
- If room formation is complete: late qualifiers are auto-advanced as lone qualifiers (`LoneQualifierAdvanced`) or held for admin decision if they form a valid room.
- A player who arrives after the formation window may receive a bye (auto-advance) — this is noted in the `qualifier_pools.advancement_reason` column.

---

## 8. Match Timeout

### Timer Lifecycle

**Set when:** `MatchStarted` is committed.

```sql
UPDATE matches SET timeout_token = <uuid>, timeout_deadline = now() + INTERVAL '20 minutes'
INSERT tournament_outbox: MatchStarted {match_id, room_id, timeout_deadline}
COMMIT

-- After commit:
SET tournament:match-timeout:<match_id> "<uuid>" PX 1200000 NX
```

**Key template:** `tournament:match-timeout:<match_id>` (from PLAN.md Redis usage map)  
**TTL:** 1,200,000 ms (20 minutes)

**Crash recovery:** On `tournament-service` startup, sweep `matches WHERE status = 'in_progress'`. For each row: `SET tournament:match-timeout:<match_id> "<timeout_token>" PX <(timeout_deadline - now()) ms> NX`. The `NX` flag is a no-op if the timer is already running.

### On Timer Expiry

The `match-timer-worker` receives a keyspace notification for `tournament:match-timeout:<match_id>`:

```
1. Parse match_id from key.
2. SELECT * FROM matches WHERE match_id = $1 AND status = 'in_progress'
   AND timeout_token = <value from Redis before expiry>
   → if no row (already completed or wrong token): no-op.

3. HTTP POST /v1/internal/games/{active_game_id}/force-complete
   Body: {resolution: lowest_card_burden, idempotency_key: <uuid>}
   → Room Gameplay resolves the game (lowest card-point burden → fewest cards remaining → RNG)
   → Returns 200 OK with resolved GameCompleted payload

4. BEGIN transaction:
   UPDATE matches SET status = 'timed_out', active_game_id = null
   INSERT tournament_outbox: MatchTimeoutReached {match_id, active_game_id, standings_at_timeout}
   INSERT tournament_outbox: MatchCompleted {match_id, timed_out: true, final_standings}
   INSERT tournament_outbox: AdvancementResolved
   UPDATE qualifier_pools for the match's players
   [Check round completion]
   COMMIT

5. Idempotency: if GameCompleted already arrived before timeout fired (race condition),
   the match status = 'completed' → step 2 returns no row → no-op.
```

**Idempotency:** The `timeout_token` field in PostgreSQL is the fence. If the token in Redis does not match the DB row (e.g., match was already completed and a new match started with a different token), the handler exits without action.

### Fallback: Room Gameplay Unavailable at Timeout

If `ForceCompleteGame` fails after 3 retries (e.g., Room Gameplay is restarting or its PostgreSQL primary is failing over), tournament-service escalates:

1. Log the failure to `admin_actions` with `action_type = 'match_timeout_resolution_failed'`.
2. Mark the match as `status = 'timed_out_pending_resolution'`.
3. Every 30 seconds, a background sweep re-attempts `ForceCompleteGame` with the same `idempotency_key` until it succeeds.
4. If the match remains unresolved after 5 minutes (well beyond any reasonable Room Gameplay outage), tournament-service resolves the match administratively:
   - Compute standings from the last known `match_standings` snapshot.
   - Advance the player with the fewest remaining cards (or by RNG tie-break if equal).
   - Emit `MatchTimeoutReached`, `MatchCompleted`, and `AdvancementResolved` without a final `GameCompleted` from Room Gameplay.
   - Room Gameplay will eventually receive the `ForceCompleteGame` success (or a duplicate no-op); the game is marked as resolved and no further events are produced.

This fallback preserves tournament progression even during a partial Room Gameplay outage. The 5-minute administrative window is long enough for normal failover (~60s RTO) but short enough to prevent a single stalled match from blocking an entire round indefinitely.

---

## 9. Abandoned vs. Completed Game Distinction

Tournament context treats forfeits as permanent elimination. All outcomes are derived from `PlayerForfeited.reason` and from `GameCompleted.forfeited`.

| Scenario | Detection | Tournament outcome |
|---|---|---|
| Player forfeits voluntarily or AFK | `PlayerForfeited(reason: Voluntary\|AFK)` on `game-events` | Marked as eliminated in `qualifier_pools`; `match_standings.forfeited = true` |
| Player forfeits due to reconnection window expiry | `PlayerForfeited(reason: ReconnectionExpired)` on `game-events` | Same — permanently eliminated |
| Player suspended/banned mid-game | `PlayerSuspended`/`PlayerBanned` on `identity-events` → Room Gameplay emits `PlayerForfeited` | Same path via `PlayerForfeited` |
| All but 1 player forfeits in a room | `GameCompleted` with 1 player as winner | Winner advances; eliminated players do not |
| Forfeits leave ≤3 active players in a tournament room | `PlayerForfeited.remaining_active_players ≤ 3` on `game-events` | All remaining active players advance unconditionally (`AdvancementResolved` with all as qualifiers); match ends without completing |
| Tournament cancelled by admin | `TournamentCancelled` via Moderation | All active rooms receive `CancelTournament` command; `GameCompleted` emitted by Room Gameplay with `reason: TournamentCancelled`; no Elo applied |

**No Elo update** for any game within a cancelled tournament. This is enforced by Ranking consuming `TournamentCancelled` and reversing any Elo deltas already applied (idempotent by `tournament_id`).

The `GameCompleted.game_type: tournament` field is the signal to Ranking that this game does NOT trigger a casual Elo update. Ranking only applies Elo on `TournamentCompleted`, not per-game in tournament play.

---

## 10. Cross-Context Sequence Diagram — Game Completion → Match Advancement

This shows the full path from a tournament `GameCompleted` through match resolution, next-game start, and (eventually) round advancement.

```
Room Gameplay      game-events (Kafka)   tournament-service    tournament-events (Kafka)   Room Gameplay (new game)   Spectator View
     |                    |                      |                          |                         |                     |
[Game G1 ends]           |                      |                          |                         |                     |
     |--outbox relay---->|                      |                          |                         |                     |
     |                   |--GameCompleted------->|                          |                         |                     |
     |                   |  {game_id:G1,         |                          |                         |                     |
     |                   |   match_id:M1,        |                          |                         |                     |
     |                   |   placements:[P1,P2], |                          |                         |                     |
     |                   |   forfeited:[],       |                          |                         |                     |
     |                   |   game_type:tournament}|                         |                         |                     |
     |                   |                       |[SELECT matches WHERE     |                         |                     |
     |                   |                       |  match_id=M1 FOR UPDATE] |                         |                     |
     |                   |                       |[Update match_standings:  |                         |                     |
     |                   |                       |  P1: match_wins=1,       |                         |                     |
     |                   |                       |  P2: match_wins=0]       |                         |                     |
     |                   |                       |[No player at 2 wins;     |                         |                     |
     |                   |                       |  game_seq=1 < 3          |                         |                     |
     |                   |                       |  → start Game 2]         |                         |                     |
     |                   |                       |                          |                         |                     |
     |                   |                       |--POST /rooms/R1/games--->|                         |                     |
     |                   |                       |  {match_id:M1,           |                         |[creates GameSession G2]|
     |                   |                       |   game_sequence:2,        |                         |[shuffles + deals]   |
     |                   |                       |   idempotency_key}       |                         |--GameStarted------->|
     |                   |                       |<--200 OK {game_id:G2}----|                         | (via outbox, game-events)|
     |                   |                       |                          |                         |                     |
     |                   |                       |--BEGIN transaction------->|                         |                     |
     |                   |                       |--UPDATE matches          |                         |                     |
     |                   |                       |  active_game_id=G2       |                         |                     |
     |                   |                       |--UPDATE match_games      |                         |                     |
     |                   |                       |  G1 status=completed     |                         |                     |
     |                   |                       |--INSERT match_games      |                         |                     |
     |                   |                       |  G2 sequence=2           |                         |                     |
     |                   |                       |--INSERT outbox:          |                         |                     |
     |                   |                       |  MatchWinAwarded(P1)     |                         |                     |
     |                   |                       |  GameInMatchStarted(G2)  |                         |                     |
     |                   |                       |--COMMIT                  |                         |                     |
     |                   |                       |                          |--MatchWinAwarded-------->|                     |
     |                   |                       |                          |--GameInMatchStarted------>|                     |
     |                   |                       |                          |                         |--MatchWinAwarded--->|
     |                   |                       |                          |                         |--GameInMatchStarted->|
     |                   |                       |                          |                         |                     |[BracketView updated]
     |                   |                       |                          |                         |                     |
     |                   |[G2 plays out …]        |                          |                         |                     |
     |                   |                       |                          |                         |                     |
     |                   |--GameCompleted------->|                          |                         |                     |
     |                   |  {game_id:G2,         |                          |                         |                     |
     |                   |   match_id:M1,        |                          |                         |                     |
     |                   |   placements:[P1,...] }|                         |                         |                     |
     |                   |                       |[Update standings:        |                         |                     |
     |                   |                       |  P1: match_wins=2        |                         |                     |
     |                   |                       |  → MatchEndedEarly]      |                         |                     |
     |                   |                       |--BEGIN transaction------->|                         |                     |
     |                   |                       |--UPDATE matches          |                         |                     |
     |                   |                       |  status=completed         |                         |                     |
     |                   |                       |--UPDATE qualifier_pools  |                         |                     |
     |                   |                       |  P1→advanced, P2→eliminated                        |                     |
     |                   |                       |--INSERT outbox:          |                         |                     |
     |                   |                       |  MatchWinAwarded(P1, w=2)|                         |                     |
     |                   |                       |  MatchEndedEarly(P1)     |                         |                     |
     |                   |                       |  MatchCompleted          |                         |                     |
     |                   |                       |  AdvancementResolved     |                         |                     |
     |                   |                       |--[if last room in round:]|                         |                     |
     |                   |                       |  INSERT outbox:          |                         |                     |
     |                   |                       |  RoundCompleted          |                         |                     |
     |                   |                       |  RoundStarted(round 2)   |                         |                     |
     |                   |                       |--COMMIT                  |                         |                     |
     |                   |                       |                          |--MatchWinAwarded-------->|                     |
     |                   |                       |                          |--MatchEndedEarly-------->|                     |
     |                   |                       |                          |--MatchCompleted---------->|                     |
     |                   |                       |                          |--AdvancementResolved----->|                     |
     |                   |                       |                          |--RoundCompleted---------->|                     |--BracketView
     |                   |                       |                          |--RoundStarted------------>|                     |  updated
```

---

## 11. PostgreSQL Schema

```sql
CREATE TABLE tournaments (
    tournament_id          UUID PRIMARY KEY,
    status                 TEXT NOT NULL DEFAULT 'registration_open',
    created_by_admin_id    UUID NOT NULL,
    confirmed_player_count INTEGER,
    total_rounds           INTEGER,
    current_round_number   INTEGER,
    champion_id            UUID,
    scheduled_start        TIMESTAMPTZ NOT NULL,
    registration_opens_at  TIMESTAMPTZ,
    registration_closes_at TIMESTAMPTZ,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE tournament_registrations (
    tournament_id UUID NOT NULL,
    player_id     UUID NOT NULL,
    registered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status        TEXT NOT NULL DEFAULT 'registered',   -- registered | confirmed | withdrawn
    PRIMARY KEY (tournament_id, player_id)
);

CREATE TABLE tournament_rounds (
    tournament_id          UUID NOT NULL,
    round_number           INTEGER NOT NULL,
    status                 TEXT NOT NULL DEFAULT 'pending',  -- pending|forming|in_progress|completed
    expected_qualifier_count INTEGER,
    phase_start_threshold  INTEGER NOT NULL,
    rooms_resolved_count   INTEGER NOT NULL DEFAULT 0,
    total_room_count       INTEGER,
    PRIMARY KEY (tournament_id, round_number)
);

CREATE TABLE tournament_rooms (
    room_id       UUID PRIMARY KEY,
    tournament_id UUID NOT NULL,
    round_number  INTEGER NOT NULL,
    match_id      UUID NOT NULL,
    player_ids    JSONB NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending|in_progress|completed|failed
    retry_count   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE qualifier_pools (
    tournament_id      UUID NOT NULL,
    round_number       INTEGER NOT NULL,
    player_id          UUID NOT NULL,
    qualified_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    status             TEXT NOT NULL DEFAULT 'waiting',  -- waiting|assigned|advanced|eliminated
    advancement_reason TEXT,    -- 'match_win' | 'lone_qualifier' | 'unconditional' | 'bye'
    PRIMARY KEY (tournament_id, round_number, player_id)
);

CREATE TABLE matches (
    match_id         UUID PRIMARY KEY,
    room_id          UUID NOT NULL,
    tournament_id    UUID NOT NULL,
    round_number     INTEGER NOT NULL,
    status           TEXT NOT NULL DEFAULT 'in_progress',  -- in_progress|completed|timed_out
    active_game_id   UUID,
    game_sequence    INTEGER NOT NULL DEFAULT 0,
    timeout_token    UUID NOT NULL,
    timeout_deadline TIMESTAMPTZ NOT NULL,
    timed_out        BOOLEAN NOT NULL DEFAULT false,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE match_standings (
    match_id                      UUID NOT NULL,
    player_id                     UUID NOT NULL,
    match_wins                    INTEGER NOT NULL DEFAULT 0,
    cumulative_card_point_burden  INTEGER NOT NULL DEFAULT 0,
    cumulative_finish_time_ms     BIGINT NOT NULL DEFAULT 0,
    forfeited                     BOOLEAN NOT NULL DEFAULT false,
    forfeit_timestamp             TIMESTAMPTZ,
    PRIMARY KEY (match_id, player_id)
);

CREATE TABLE match_games (
    match_id        UUID NOT NULL,
    game_id         UUID NOT NULL,
    sequence_number INTEGER NOT NULL,
    status          TEXT NOT NULL DEFAULT 'in_progress',  -- in_progress|completed
    PRIMARY KEY (match_id, sequence_number)
);

-- Kickoff outbox: separate from main outbox for rate-limited delivery to tournament-kickoff topic
CREATE TABLE kickoff_outbox (
    id            BIGSERIAL PRIMARY KEY,
    room_id       UUID NOT NULL,
    payload       JSONB NOT NULL,   -- TournamentRoomAssigned payload
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered     BOOLEAN NOT NULL DEFAULT false,
    delivered_at  TIMESTAMPTZ
);
CREATE INDEX ON kickoff_outbox (delivered, id) WHERE delivered = false;

-- Dead-letter queue for rooms that fail creation after N retries
CREATE TABLE room_kickoff_failures (
    id            BIGSERIAL PRIMARY KEY,
    tournament_id UUID NOT NULL,
    round_number  INTEGER NOT NULL,
    room_id       UUID NOT NULL,
    player_ids    JSONB NOT NULL,
    failure_reason TEXT,
    retry_count   INTEGER NOT NULL,
    resolved      BOOLEAN NOT NULL DEFAULT false,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Main outbox for tournament-events topic
CREATE TABLE tournament_outbox (
    id            BIGSERIAL PRIMARY KEY,
    tournament_id UUID NOT NULL,
    event_type    TEXT NOT NULL,
    payload       JSONB NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered     BOOLEAN NOT NULL DEFAULT false,
    delivered_at  TIMESTAMPTZ
);
CREATE INDEX ON tournament_outbox (delivered, id) WHERE delivered = false;
```

---

## 12. Dependencies on Other Contexts

| Dependency | Direction | Mechanism | What is delegated |
|---|---|---|---|
| Room Gameplay | Outbound command (HTTP, mTLS) | `POST /v1/internal/rooms`, `AssignPlayersToRoom`, `ForceCompleteGame`, `StartNextGameInRoom` | Room creation, player assignment, match timeout resolution, Bo3 next-game initialization |
| Room Gameplay | Inbound event (Kafka `game-events`) | `GameCompleted`, `PlayerForfeited`, `GameStarted` | Match state updates, forfeit tracking, active game confirmation |
| Identity/Session | Inbound event (Kafka `identity-events`) | `PlayerSuspended`, `PlayerBanned` | Permanent player elimination |
| Ranking | Outbound event (Kafka `tournament-events`) | `TournamentCompleted`, `TournamentCancelled` | Tournament Elo triggers and cancellation compensation |
| Spectator View | Outbound event (Kafka `tournament-events`, `tournament-kickoff`) | All tournament lifecycle events | Bracket display, room list, leaderboard |
| Moderation | Inbound command (HTTP, mTLS) | `CancelTournament` | Admin cancellation |

**Anti-corruption layer:** Tournament Orchestration never reads Room Gameplay's PostgreSQL schema. All game state is learned through `game-events` Kafka events. The `match_standings` in Tournament Orchestration are derived entirely from `GameCompleted` and `PlayerForfeited` payloads — no cross-schema query occurs.
