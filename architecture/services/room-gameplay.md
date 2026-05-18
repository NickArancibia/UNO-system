# Room Gameplay Service

**Bounded context:** Room Gameplay  
**Phase:** 1  
**Dependencies:** [PLAN.md](../PLAN.md) resolved decisions R2, R5, R6; O3 settled as Redis TTL + keyspace notifications.

---

## 1. Purpose and Scope

Room Gameplay is the authoritative owner of all in-game state. It enforces every UNO rule, manages room lifecycle, and runs all per-game timers. It is the most command-intensive service in the system.

**Owns:**
- `GameSession` aggregate — all in-game state for one active game
- `Room` aggregate — lobby lifecycle, player membership, room status
- `MatchmakingQueue` aggregate — casual Quick Play queue
- Immutable game log (`game_events` table)
- Turn timers (45s) and challenge windows (5s / combined Uno!+WD4)

**Does NOT own:**
- Player identity or session validity (validated at API Gateway via JWT)
- Reconnection window timer (owned by Identity/Session context)
- Match timeout timer (owned by Tournament Orchestration)
- Tournament progression logic (Tournament Orchestration reacts to `GameCompleted`)
- Elo calculation (Ranking context)
- Spectator data filtering (Spectator View context)

---

## 2. Containers

| Container | Type | Responsibility |
|---|---|---|
| `room-gameplay-service` | Long-running HTTP/WebSocket service | Handles game commands, room lifecycle, matchmaking queue; owns the PostgreSQL transaction |
| `outbox-relay-worker` | In-process background thread (within `room-gameplay-service`) | Reads undelivered outbox rows, publishes to Kafka, marks rows delivered |
| `matchmaking-worker` | In-process background thread (within `room-gameplay-service`) | Polls `matchmaking_queue` table with `SELECT FOR UPDATE SKIP LOCKED`, assembles rooms |
| `timer-subscription-worker` | In-process background thread (within `room-gameplay-service`) | Subscribes to Redis keyspace expiry notifications, routes to timer handlers |
| `tournament-kickoff-consumer-worker` | In-process background thread (within `room-gameplay-service`) | Consumes `tournament-kickoff` Kafka topic (consumer group `room-gameplay-kickoff-cg`); creates tournament rooms and assigns players; idempotent by pre-assigned `room_id` |

All five run in the same deployed container. There is no separate deployment for the relay, matchmaking, or kickoff workers.

---

## 3. Public Synchronous Interfaces

Base path: `/v1/` (all endpoints require a valid JWT unless noted).

### 3.1 Game Commands (WebSocket, forwarded by API Gateway)

WebSocket connections are terminated at the API Gateway. The gateway forwards each incoming frame as an HTTP POST to `room-gameplay-service`, carrying the validated `player_id` and `game_id` in headers.

| Command | Path | Notes |
|---|---|---|
| `PlayCard` | `POST /v1/games/{game_id}/commands/play-card` | Carries `card`, `declared_color` (Wild/WD4), `state_version`, `idempotency_key` |
| `DrawCard` | `POST /v1/games/{game_id}/commands/draw-card` | Carries `state_version`, `idempotency_key` |
| `DrawStackPenalty` | `POST /v1/games/{game_id}/commands/draw-stack-penalty` | Carries `state_version`, `idempotency_key` |
| `JumpIn` | `POST /v1/games/{game_id}/commands/jump-in` | Carries `card`, `state_version`, `idempotency_key`; race window 150ms |
| `CallUno` | `POST /v1/games/{game_id}/commands/call-uno` | Carries `idempotency_key` |
| `ChallengeUno` | `POST /v1/games/{game_id}/commands/challenge-uno` | Carries `state_version`, `idempotency_key`; race window 150ms |
| `ChallengeWildDrawFour` | `POST /v1/games/{game_id}/commands/challenge-wdf` | Carries `state_version`, `idempotency_key` |
| `Forfeit` | `POST /v1/games/{game_id}/commands/forfeit` | Carries `idempotency_key` |

All game commands return:
- `200 OK` with the resulting event(s) if accepted.
- `409 Conflict` if `state_version` is stale.
- `422 Unprocessable Entity` if the command is invalid (illegal play, wrong turn, etc.).
- `200 OK` (original result) if the `idempotency_key` was already processed.

### 3.2 Room / Queue Commands (REST)

| Command | Method + Path | Notes |
|---|---|---|
| `JoinQueue` | `POST /v1/rooms/queue` | Casual Quick Play queue entry |
| `LeaveQueue` | `DELETE /v1/rooms/queue` | Remove self from queue before room assignment |
| `JoinAsSpectator` | `POST /v1/rooms/{room_id}/spectate` | No game state returned; Spectator View handles the stream |

### 3.3 Game Log Read API

| Query | Method + Path | Authorization |
|---|---|---|
| Read public game log | `GET /v1/games/{game_id}/log` | JWT required; returns public-filtered log (hand data withheld during game; WD4 accused hand revealed post-game) |
| Read full game log | `GET /v1/internal/games/{game_id}/log/full` | Internal only; `moderation-service` admin token; returns complete unfiltered log including hand contents at time of events |

### 3.4 Internal Commands (from Tournament Orchestration)

These endpoints are not exposed via the API Gateway. mTLS required.

| Command | Method + Path | Notes |
|---|---|---|
| `CreateRoom` | `POST /v1/internal/rooms` | Pre-assigned `room_id` from Tournament Orchestration (deterministic, idempotent) |
| `AssignPlayersToRoom` | `POST /v1/internal/rooms/{room_id}/players` | Bulk assignment; idempotent by `(room_id, player_id)` |
| `ForceCompleteGame` | `POST /v1/internal/games/{game_id}/force-complete` | Resolves active game for match timeout; idempotent by `game_id` |
| `StartNextGameInRoom` | `POST /v1/internal/rooms/{room_id}/games` | Initializes a new `GameSession` in an existing tournament room (Game 2 or Game 3); `{match_id, game_sequence_number: 2|3, idempotency_key}`; no lobby timer (immediate deal); idempotent by `(room_id, game_sequence_number)` |

---

## 4. Public Asynchronous Interfaces

**Topic:** `game-events`  
**Partitioned by:** `game_id` (ensures all events for one game arrive in order at consumers)  
**Produced via:** transactional outbox relay — never written directly to Kafka from the command handler  
**Schema version field:** all events carry `schema_version: 1` for forward-compatibility

| Event | Idempotency key | Primary consumers |
|---|---|---|
| `RoomCreated` | `room_id` | Spectator View |
| `RoomStatusChanged` | `(room_id, status)` | Spectator View |
| `PlayerAssignedToRoom` | `(room_id, player_id)` | Spectator View, Tournament Orchestration |
| `LobbyTimerStarted` | `room_id` | Spectator View |
| `LobbyTimerReduced` | `room_id` | Spectator View |
| `GameStarted` | `game_id` | Spectator View, Tournament Orchestration |
| `CardPlayed` | `(game_id, state_version)` | Spectator View |
| `CardDrawn` | `(game_id, state_version)` | Spectator View (withholds card identity) |
| `DrawPileReplenished` | `(game_id, state_version)` | Spectator View |
| `TurnAdvanced` | `(game_id, state_version)` | Spectator View |
| `DirectionReversed` | `(game_id, state_version)` | Spectator View |
| `PlayerSkipped` | `(game_id, state_version)` | Spectator View |
| `DrawTwoActivated` | `(game_id, state_version)` | Spectator View |
| `DrawTwoStacked` | `(game_id, state_version)` | Spectator View |
| `WildDrawFourActivated` | `(game_id, state_version)` | Spectator View |
| `PenaltyCardsDrawn` | `(game_id, state_version)` | Spectator View (withholds card identities) |
| `ChallengeWindowOpened` | `(game_id, state_version, window_type)` | Spectator View |
| `ChallengeWindowClosed` | `(game_id, state_version, window_type)` | Spectator View |
| `UnoCallMade` | `(game_id, state_version)` | Spectator View |
| `UnoChallengeIssued` | `(game_id, state_version)` | Spectator View |
| `UnoChallengeResolved` | `(game_id, state_version)` | Spectator View |
| `WildDrawFourChallengeIssued` | `(game_id, state_version)` | Spectator View |
| `WildDrawFourChallengeResolved` | `(game_id, state_version)` | Spectator View (withholds accused hand during game) |
| `JumpInOccurred` | `(game_id, state_version)` | Spectator View |
| `RaceResolved` | `(game_id, state_version)` | Spectator View |
| `PlayerDisconnected` | `(game_id, player_id)` | Spectator View, Tournament Orchestration |
| `PlayerReconnected` | `(game_id, player_id)` | Spectator View |
| `PlayerForfeited` | `(game_id, player_id)` | Spectator View, Tournament Orchestration, Ranking, Analytics |
| `PlayerPlaced` | `(game_id, player_id)` | Spectator View |
| `GameCompleted` | `game_id` | Ranking, Spectator View, Tournament Orchestration, Analytics. Payload includes `outcome: completed\|abandoned`; Ranking skips Elo when `outcome = abandoned`. |
| `PlayerJoinedQueue` | `(player_id, queue_entry_id)` | — (internal; logged only) |
| `PlayerLeftQueue` | `(player_id, queue_entry_id)` | — (internal; logged only) |
| `SpectatorJoined` | `(room_id, player_id)` | Spectator View |

---

## 5. Log-Before-Broadcast: Transactional Outbox

Every accepted game command executes in a single PostgreSQL transaction:

1. Acquire `SELECT ... FOR UPDATE` row lock on `game_sessions` where `game_id = $1`.
2. Read current `state_version` and aggregate state (JSONB).
3. Validate `state_version` from command matches server's current version → reject 409 if not.
4. Check idempotency key in Redis (`gameplay:idem:<game_id>:<key>`) → return cached result if hit.
5. Run legal play validation and all precondition checks → reject 422 if failed.
6. Compute new aggregate state.
7. `BEGIN` transaction:
   - `UPDATE game_sessions SET state = $new_state, state_version = state_version + 1`
   - `INSERT INTO game_events (game_id, state_version, event_type, payload, occurred_at) VALUES ...` (one row per produced event)
   - `INSERT INTO outbox (game_id, event_type, payload, created_at, delivered = false) VALUES ...` (one row per event to broadcast)
8. `COMMIT` → row lock released.
9. Write idempotency key to Redis: `SET gameplay:idem:<game_id>:<key> <result> PX <game_ttl+86400000> NX`.
10. After commit: set/reset the turn timer in Redis (see §6).
11. Return `200 OK` with event payload to API Gateway → client.

The **outbox-relay-worker** (background thread) runs independently:
- Polls: `SELECT id, payload FROM outbox WHERE delivered = false ORDER BY id LIMIT 100`.
- Publishes each row to the `game-events` Kafka topic using an **idempotent producer** (`enable.idempotence=true`, `acks=all`).
- After Kafka ACK: `UPDATE outbox SET delivered = true WHERE id = $id`.
- On relay crash: replays from last undelivered row on restart. Kafka idempotent producer prevents duplicate delivery.

**Guarantee:** No event reaches Kafka (and therefore no client or downstream consumer) before it is durably written to `game_events`. The game log row and the Kafka message are derived from the same outbox row — they cannot diverge.

### 5.1 Mandatory Sequence Diagram — PlayCard Hot Path

```
Client                API Gateway          room-gameplay-service         PostgreSQL        outbox-relay      Kafka        Spectator View
  |                        |                         |                        |                  |              |                |
  |--WS: PlayCard--------->|                         |                        |                  |              |                |
  |  {card, state_ver,     |                         |                        |                  |              |                |
  |   idempotency_key}     |                         |                        |                  |              |                |
  |                        |--POST /games/G1/-------->|                        |                  |              |                |
  |                        |  commands/play-card      |                        |                  |              |                |
  |                        |  [JWT validated,         |                        |                  |              |                |
  |                        |   player_id injected]    |                        |                  |              |                |
  |                        |                         |--SELECT game_sessions-->|                  |              |                |
  |                        |                         |  FOR UPDATE WHERE       |                  |              |                |
  |                        |                         |  game_id = 'G1'         |                  |              |                |
  |                        |                         |<--row locked, returned--|                  |              |                |
  |                        |                         |                        |                  |              |                |
  |                        |                         |[1. Check state_version] |                  |              |                |
  |                        |                         |    client ver = server ver ✓               |              |                |
  |                        |                         |[2. Check idempotency]   |                  |              |                |
  |                        |                         |    Redis: MISS → proceed|                  |              |                |
  |                        |                         |[3. Legal play validation]|                 |              |                |
  |                        |                         |    card legal ✓         |                  |              |                |
  |                        |                         |[4. Compute new state]   |                  |              |                |
  |                        |                         |                        |                  |              |                |
  |                        |                         |--BEGIN transaction----->|                  |              |                |
  |                        |                         |--UPDATE game_sessions-->|                  |              |                |
  |                        |                         |  SET state=...,        |                  |              |                |
  |                        |                         |  state_version=2        |                  |              |                |
  |                        |                         |--INSERT game_events---->|                  |              |                |
  |                        |                         |  (CardPlayed, ver=2)   |                  |              |                |
  |                        |                         |--INSERT game_events---->|                  |              |                |
  |                        |                         |  (TurnAdvanced, ver=2) |                  |              |                |
  |                        |                         |--INSERT outbox--------->|                  |              |                |
  |                        |                         |  (CardPlayed, undeliv'd)|                  |              |                |
  |                        |                         |--INSERT outbox--------->|                  |              |                |
  |                        |                         |  (TurnAdvanced, undel'd)|                  |              |                |
  |                        |                         |--COMMIT---------------->|                  |              |                |
  |                        |                         |<--ok--------------------|                  |              |                |
  |                        |                         |  (row lock released)    |                  |              |                |
  |                        |                         |                        |                  |              |                |
  |                        |                         |[5. Cache idempotency key in Redis]         |              |                |
  |                        |                         |[6. Reset turn timer in Redis: SETNX]       |              |                |
  |                        |                         |                        |                  |              |                |
  |                        |<--200 OK: CardPlayed----|                        |                  |              |                |
  |                        |   TurnAdvanced, ver=2   |                        |                  |              |                |
  |<--WS push: CardPlayed--|                         |                        |                  |              |                |
  |   TurnAdvanced         |                         |                        |                  |              |                |
  |                        |                         |                        |                  |              |                |
  |                        |                         |                        | [outbox-relay polls outbox]    |                |
  |                        |                         |                        |<-SELECT undeliv'd-|              |                |
  |                        |                         |                        |--rows returned--->|              |                |
  |                        |                         |                        |                  |--produce----->|                |
  |                        |                         |                        |                  |  CardPlayed   |                |
  |                        |                         |                        |                  |  TurnAdvanced |                |
  |                        |                         |                        |                  |<--ACK---------|                |
  |                        |                         |                        |<-UPDATE delivered-|              |                |
  |                        |                         |                        |  = true           |              |                |
  |                        |                         |                        |                  |              |--CardPlayed--->|
  |                        |                         |                        |                  |              |--TurnAdvanced->|
  |                        |                         |                        |                  |              |                |[apply privacy filter]
  |                        |                         |                        |                  |              |                |[update PublicGameView in Redis]
  |                        |                         |                        |                  |              |                |[push to spectator WS connections]
```

**Key property:** The client's `200 OK` response (and the WebSocket push from the Gateway) is sent _after_ the `COMMIT` but _before_ the Kafka publish. The client sees the result immediately. Kafka delivery — and therefore all downstream consumers — happens asynchronously after the durable write. There is no window in which the event can appear in Kafka without being in the game log.

---

## 6. Timer Ownership and Crash Behavior

All timers owned by this service are stored in Redis as String keys with hard TTLs. The `timer-subscription-worker` subscribes to `__keyevent@<db>__:expired` on the Redis timer database (`notify-keyspace-events KEA` must be enabled).

Each timer key stores a **UUID token** generated at timer-creation time. The same token is persisted in the `game_sessions` JSONB state. On expiry, the handler fetches the current game state and compares the stored token — only a matching token authorizes the side effect. This is the crash-recovery fence.

Timer keys are set with `SETNX` (NX flag): if the key already exists, the timer is already running — do nothing.

### Timer Table

| Timer | Key template | TTL | Set when | Cancelled when | On expiry | Idempotency |
|---|---|---|---|---|---|---|
| Turn timer | `gameplay:turn-timer:<game_id>` | 45,000 ms | After each `TurnAdvanced` (including game start) | Turn advances normally (Lua conditional DEL) | Handler acquires row lock → validates token → issues `TurnTimedOut` command → `PlayerForfeited` (AFK) or turn skipped | `(game_id, timer_token)` — stale token = no-op |
| Uno! challenge window | `gameplay:challenge:<game_id>:<state_version>:uno` | 5,000 ms | On `ChallengeWindowOpened` (Uno! type) | `ChallengeWindowClosed` event committed | Handler acquires row lock → validates window still open → issues `ChallengeWindowExpired` → `PenaltyCardsDrawn` (2) to target player if Uno! was not called | `(game_id, state_version, window_type)` |
| WD4 challenge window | `gameplay:challenge:<game_id>:<state_version>:wdf` | 5,000 ms | On `ChallengeWindowOpened` (WD4 type) | `ChallengeWindowClosed` event committed | Handler acquires row lock → validates window still open → issues `ChallengeWindowExpired` → `PenaltyCardsDrawn` (4) to next player (waived challenge) | `(game_id, state_version, window_type)` |
| Lobby timer | `gameplay:lobby-timer:<room_id>` | Configurable (default 5 min, reduced to 10s at max capacity) | On `LobbyTimerStarted` | N/A (always runs to expiry) | Room Gameplay checks player count: ≥2 → `GameStarted`; <2 → `RoomCancelled` | `room_id` + room status check; startup sweep re-arms or fires expired timers on recovery (see below) |
| Distributed lock (lobby start) | `gameplay:lobby-lock:<room_id>` | 10,000 ms | Before starting lobby timer (SETNX) | On lock release (Lua conditional DEL) | Lock TTL is safety-net only; the DB status column is the fence | N/A |

### Crash Behavior for Timer Node Failure

```
1. room-gameplay-service instance A sets turn timer:
     SET gameplay:turn-timer:G1 "uuid-abc" PX 45000

2. Instance A crashes after 20 seconds.

3. Redis continues counting; timer expires at T+45s.

4. Redis fires: __keyevent@1__:expired → gameplay:turn-timer:G1

5. Any living instance subscribed to keyspace notifications receives the event.
   (All instances subscribe; the first to receive acts.)

6. Instance B receives the notification:
   - Acquires SELECT FOR UPDATE on game_sessions WHERE game_id = 'G1'
   - Reads state: turn still belongs to original player, timer_token = "uuid-abc" ✓
   - Issues TurnTimedOut command → full transaction → PlayerForfeited or turn skip

7. If the notification is delivered to two instances simultaneously:
   - Both attempt the row lock; one waits.
   - First commits: state_version advances, turn_token changes.
   - Second acquires lock: reads new state_version, timer_token no longer matches → no-op.
```

### Reconciliation Sweeps (missed-notification safety net)

Redis keyspace notifications are at-most-once. Two background sweeps in `timer-subscription-worker` compensate for lost notifications:

**Turn-timer sweep — every 60s:**
```sql
SELECT game_id, state->>'turn_timer_token' AS token
FROM game_sessions
WHERE status = 'in_progress'
  AND (state->>'turn_started_at')::timestamptz < now() - INTERVAL '45 seconds'
```
For each result: check that `gameplay:turn-timer:<game_id>` does NOT exist in Redis (confirms
the key expired and the notification was missed). If absent → issue synthetic `TurnTimedOut`
command through the normal handler (same token fence applies).

**Challenge-window sweep — every 2s:**
```sql
SELECT game_id, state->>'challenge_window_token' AS token,
       state->>'challenge_window_type' AS window_type
FROM game_sessions
WHERE status = 'in_progress'
  AND state->>'challenge_window_status' = 'open'
  AND (state->>'challenge_window_opened_at')::timestamptz < now() - INTERVAL '5 seconds'
```
For each result: check that `gameplay:challenge:<game_id>:<state_version>:<window_type>` does
NOT exist in Redis. If absent → issue synthetic `ChallengeWindowExpired` command.

The 2-second interval is necessary: a 60-second sweep interval for a 5-second window would
extend the challenge window from 5s to up to 60s on a missed notification — a game-rule
violation. The 2-second sweep touches only games with an open challenge window, which is a
small subset of all active games at any instant.

To make the `challenge_window_status` query efficient, `game_sessions` carries a
`challenge_window_open BOOLEAN GENERATED ALWAYS` column derived from the JSONB state, indexed
separately:
```sql
ALTER TABLE game_sessions
  ADD COLUMN challenge_window_open BOOLEAN NOT NULL DEFAULT false;

CREATE INDEX ON game_sessions (challenge_window_open)
  WHERE challenge_window_open = true;
```
This column is set to `true` on `ChallengeWindowOpened` commit and `false` on
`ChallengeWindowClosed` commit, inside the same transaction as the state update.

**Lobby-timer startup sweep:**

On `room-gameplay-service` startup (before accepting requests), the service queries for rooms
that had a running lobby timer and re-arms or fires them:

```sql
SELECT room_id, lobby_started_at, lobby_duration_ms
FROM rooms
WHERE status = 'waiting'
  AND lobby_started_at IS NOT NULL
```

For each row:
```
remaining_ttl_ms = (lobby_started_at + lobby_duration_ms) - now_ms()

IF remaining_ttl_ms > 0:
    SET gameplay:lobby-timer:<room_id} "<lobby-uuid>" PX {remaining_ttl_ms} NX
    -- NX: only sets if key does not exist (another instance may have already re-armed it)
ELSE:
    -- Timer expired while service was down; fire the expiry handler immediately
    -- Handler checks player count: ≥2 → GameStarted; <2 → RoomCancelled (idempotent by room status)
    issue_lobby_timer_expired(room_id)
```

This covers the lobby timer's up-to-5-minute TTL gap (much longer than turn or challenge timers), which would otherwise leave stale `waiting` rooms indefinitely after a process restart.

---

## 7. Sequence-Number Enforcement

The `state_version` check is performed **inside the PostgreSQL row lock**, before the transaction commits:

```
LOCK row (SELECT FOR UPDATE)
  → read current state_version from DB
  → compare with command's state_version
  → if mismatch: return 409 immediately, release lock
  → if match: proceed with validation and commit
```

Because the row lock prevents any other command from reading-and-writing the same game row concurrently, no two commands can produce the same `state_version`. The check is linearized by the lock — there is no TOCTOU gap.

---

## 8. Casual Matchmaking

The `matchmaking-worker` background thread runs on every `room-gameplay-service` instance. Multiple instances compete safely via PostgreSQL `SELECT FOR UPDATE SKIP LOCKED`:

```sql
-- Runs periodically (e.g., every 500ms) on each instance:
BEGIN;

SELECT player_id, joined_at, region, casual_elo
FROM matchmaking_queue
WHERE status = 'waiting'
  AND region = $target_region          -- regional grouping
ORDER BY joined_at ASC
LIMIT 10
FOR UPDATE SKIP LOCKED;               -- other instances skip locked rows

-- If ≥ 2 rows returned:
--   1. Mark rows as 'assigned'
--   2. Compute room_id (UUID)
--   3. INSERT INTO rooms (room_id, room_type=casual, status=waiting)
--   4. INSERT INTO game_events / outbox: RoomCreated, PlayerAssignedToRoom × N
-- If 5+ players: also INSERT lobby timer start into outbox

COMMIT;
```

Room assembly criteria (from `specs/CONSTRAINTS.md`): same region, Elo proximity (±200 for established players; relaxed to ±400 after 60s wait). Room size 2–10; lobby timer starts at 5 players.

The `SKIP LOCKED` clause ensures that even if multiple instances run the loop simultaneously, each player row is claimed by exactly one instance. No player can be assigned to two rooms.

---

## 9. Game Log Read Path

The `game_events` table is append-only and immutable after `GameCompleted`. It contains the complete, unfiltered record of every state change including server-side RNG outcomes (shuffle seed, draw results) and WD4 accused hand contents.

| Access path | Authorized by | Returns | Purpose |
|---|---|---|---|
| `GET /v1/games/{game_id}/log` | Player JWT (own games only) or any authenticated player (post-game) | Public-filtered log: card identities withheld during game; WD4 accused hand revealed after `GameCompleted` | Player review, dispute initiation |
| `GET /v1/internal/games/{game_id}/log/full` | Moderation service admin token (mTLS, internal only) | Complete unfiltered log including all hand events and RNG seeds | Admin dispute resolution, audit |
| Spectator View `PublicGameLog` | Via `spectator-service` public API | Same as public-filtered log above | Spectator replay, tournament bracket display |

The full game log is never exposed to clients via the public API. Privacy filtering mirrors the Spectator View whitelist.

---

## 10. Persistence and Sharding

### 10.1 Primary Store

**PostgreSQL 15+** — `gameplay` schema (or sharded set of schemas, see §10.2).

| Table | Purpose | Write pattern | Consistency |
|---|---|---|---|
| `game_sessions` | Authoritative aggregate state (JSONB) + `state_version` | Row-lock (`SELECT FOR UPDATE`), update on every command | Strong (per-game linearized) |
| `game_events` | Immutable append-only game log | Append-only; one row per event per command | Strong (same transaction as state update) |
| `rooms` | Room lifecycle, player membership, status | Row-lock on room operations | Strong |
| `matchmaking_queue` | Quick Play queue entries | `SELECT FOR UPDATE SKIP LOCKED` | Strong (queue semantics) |
| `outbox` | Transactional outbox for Kafka relay | Append + mark delivered | Strong (same transaction as state update) |

**Transactional boundary:** Every accepted game command is a single PostgreSQL transaction containing: `UPDATE game_sessions`, `INSERT INTO game_events`, `INSERT INTO outbox`. This is the log-before-broadcast guarantee (see §5).

### 10.2 Sharding Strategy

At 100K concurrent games with ~1 command per second per game, the `game_sessions` table sustains ~100K TPS — well beyond a single PostgreSQL instance's capacity for row-lock-heavy write workloads (~10K–30K TPS).

The gameplay database is sharded by `game_id % 16` (16 shards). Each shard is an independent PostgreSQL instance (or a separate schema on a dedicated server for lower environments).

**Routing:** The `game_id` is included in every command URL (`POST /v1/games/{game_id}/commands/play-card`). The API Gateway or an internal routing layer extracts `game_id`, computes `game_id % 16`, and routes the request to any `room-gameplay-service` pod. Every pod connects to all 16 shards and includes the shard number in its connection pool key.

**Shard-local tables:** `game_sessions`, `game_events`, `outbox`, `rooms` — all include `game_id` (or `room_id`, which is derived from `game_id` / deterministically assigned) as a leading column in their primary key, enabling shard-local queries.

**Unsharded table:** `matchmaking_queue` remains on shard 0 (or a dedicated small instance) — write volume is low (players joining/leaving Quick Play, typically <1% of game command rate) and the `SELECT FOR UPDATE SKIP LOCKED` pattern requires a single table. At peak, queue operations are ~1,000 TPS (registration surges), well within a single PostgreSQL instance's capacity. If queue contention ever becomes a bottleneck, the table can be partitioned by `player_id % N` with a lightweight coordinator that routes queue polls to the appropriate partition.

**Per-shard TPS:** 100,000 / 16 ≈ 6,250 TPS per shard. A well-tuned PostgreSQL instance handles this with SSD-backed storage and appropriate `shared_buffers` / `work_mem` settings.

**Outbox relay:** One relay thread per shard (16 relay threads per pod), each polling its shard's `outbox` table independently. This avoids cross-shard polling complexity.

**Migration path:** Start with N=4 shards at low traffic. Scale to N=8, then N=16 as concurrent games grow. Resharding requires brief downtime for data movement but no application schema changes — all queries already include `game_id`.

### 10.3 Read Path for Game Log

| Access path | Authorized by | Returns | Store |
|---|---|---|---|
| `GET /v1/games/{game_id}/log` | Player JWT (own games only, or any player post-game) | Public-filtered log: card identities withheld during game; WD4 accused hand revealed after `GameCompleted` | PostgreSQL `game_events` on the game's shard |
| `GET /v1/internal/games/{game_id}/log/full` | Moderation admin token (mTLS, internal) | Complete unfiltered log including all hand events and RNG seeds | PostgreSQL `game_events` on the game's shard |
| Spectator View `PublicGameLog` | Via spectator-service public API | Privacy-filtered sealed log | PostgreSQL `public_game_logs` (Spectator's own schema) |

The game log is **immutable after `GameCompleted`**. No UPDATE or DELETE is ever issued against `game_events`. The primary key `(game_id, state_version)` ensures efficient range scans for full game replay.

### 10.4 Redis Usage (Room Gameplay)

All Redis keys used by this service are prefixed `gameplay:*`. See [PLAN.md](../PLAN.md) §Redis Usage Map for key templates and patterns.

| Key pattern | Purpose | Instance | TTL |
|---|---|---|---|
| `gameplay:turn-timer:<game_id>` | Turn timer (45s) | Timer instance | 45,000 ms |
| `gameplay:challenge:<game_id>:<state_version>:<type>` | Challenge window (5s) | Timer instance | 5,000 ms |
| `gameplay:idem:<game_id>:<idempotency_key>` | Idempotency cache | Cache instance | Game duration + 24h |
| `gameplay:lobby-timer:<room_id>` | Lobby timer | Timer instance | Configurable (5min / 10s) |
| `gameplay:lobby-lock:<room_id>` | Distributed lock for lobby start | Cache instance | 10,000 ms |
| `gameplay:afk:<game_id>` | AFK counter per player | Cache instance | Game duration |

---

## 11. Dependencies on Other Contexts

| Dependency | Direction | Mechanism | What is delegated |
|---|---|---|---|
| Identity / Session | Upstream | JWT claims validated at API Gateway; `player_id` injected into request headers | Player identity, session validity |
| Identity / Session | Inbound event | Consumes `identity-events` Kafka topic: `SessionInvalidated` → marks player as disconnected; `PlayerSuspended`/`PlayerBanned` → triggers `PlayerForfeited` if in active game | Session invalidation mid-game |
| Identity / Session | Inbound event | `ReconnectionWindowExpired` on `identity-events` → issues `PlayerForfeited` | Reconnection window expiry (timer owned by Identity/Session, not here) |
| Identity / Session | Inbound event | `PlayerReconnected` on `identity-events` → re-activates player in `PlayerHand.connected`, emits `PlayerReconnected` (game event) to Spectator View, then calls `POST /internal/push/{player_id}` on the API Gateway with the full public `GameSession` state snapshot (hand contents, discard top, draw pile count, turn order, current version). A `404` response means the player's WebSocket is on a different gateway instance than the one the load balancer selected for this call; Room Gameplay treats `404` as a no-op. The client is responsible for calling `GET /v1/games/{game_id}/state` if no snapshot is received within 2 seconds of reconnecting. | Reconnection completion; snapshot delivery via Gateway push endpoint |
| API Gateway | Outbound HTTP (mTLS, internal) | `POST /internal/push/{player_id}` — used to deliver server-initiated payloads (reconnect snapshot, timer-expiry side-effect broadcasts) to a specific player's live WebSocket connection | Server-initiated WebSocket push; 404 = player not connected (no-op) |
| Tournament Orchestration | Inbound command | Receives `CreateRoom`, `AssignPlayersToRoom`, `ForceCompleteGame`, `StartNextGameInRoom` via internal HTTP | Tournament room creation, match timeout resolution, Bo3 game sequencing |
| Tournament Orchestration | Inbound event | Consumes `tournament-kickoff` Kafka topic (`TournamentRoomAssigned`); creates room and assigns players atomically | Surge fan-out path for round-kickoff (100K rooms at `StartTournament`); replaces HTTP for the first-game creation at scale |
| Ranking | Outbound event | Publishes `GameCompleted` on `game-events` topic; Ranking consumes asynchronously | Elo calculation |
| Spectator View | Outbound event | All game events published via outbox to `game-events` topic; Spectator View applies privacy filter | Live game projection |
| Analytics | Outbound event | `GameCompleted`, `PlayerForfeited` on `game-events` topic | Player stats, round-end spike absorption |
