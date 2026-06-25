# Spectator View Service

**Bounded Context:** Spectator View  
**Status:** Phase 4 — complete  
**Decisions applied:** O6 (Redis Streams fan-out), O7 (privacy filter at consumption), R1 (WebSocket)

---

## 1. Purpose and Scope

Spectator View is a **pure read-side context**. It accepts no commands from clients and issues no commands to other services. All writes are driven by Kafka event consumption.

**Owns:**
- `PublicGameView` — live, privacy-filtered snapshot of an in-progress game; stored in Redis.
- `PublicGameLog` — immutable, sealed record of a completed game (post-game hand reveal included); stored in PostgreSQL.
- `BracketView` — tournament bracket and round-by-round standings; stored in Redis (live) and PostgreSQL (persistent).
- `SpectatorRoomList` — list of joinable rooms with status; stored in Redis.
- `LeaderboardView` — read-only view of Elo rankings; served from the authoritative `ranking:leaderboard:casual` / `ranking:leaderboard:tournament` sorted sets owned by Ranking.

**Does NOT own:**
- `GameSession` or any game write state (owned by Room Gameplay).
- `EloRecord` or leaderboard sorted sets (owned by Ranking; Spectator View reads without writing).
- Tournament lifecycle state (owned by Tournament Orchestration).
- Any player hand data at any time during an in-progress game.

---

## 2. Containers

### 2.1 `spectator-service`

| Property | Value |
|---|---|
| **Technology** | JVM or Go service; Redis (Streams + Hashes + Sorted Sets); PostgreSQL (`spectator` schema) |
| **Primary responsibility** | Holds spectator WebSocket connections; serves read model queries (REST); fans events from Redis Streams to connected spectators |
| **Instances** | Horizontally scalable; no sticky routing required — any instance can serve any spectator by reading from the shared Redis Streams |

**Interfaces (inbound):**
- WebSocket: `wss://.../v1/spectator/games/{game_id}` — live event stream (via API Gateway)
- REST: `GET /v1/spectator/games/{game_id}` — PublicGameView snapshot
- REST: `GET /v1/spectator/games/{game_id}/log` — PublicGameLog (sealed post-game)
- REST: `GET /v1/spectator/rooms` — SpectatorRoomList
- REST: `GET /v1/spectator/brackets/{tournament_id}` — BracketView
- REST: `GET /v1/spectator/leaderboard?type=casual|tournament&limit=N` — LeaderboardView

**Interfaces (outbound):**
- Redis `XREAD BLOCK 0 STREAMS spectator:stream:{game_id} {last_id}` — reads filtered events for WebSocket fan-out
- Redis `HGETALL spectator:gameview:{game_id}` — snapshot on spectator connect/reconnect
- PostgreSQL — reads `public_game_logs`, `bracket_views` for REST queries

### 2.2 `spectator-game-consumer-worker`

| Property | Value |
|---|---|
| **Consumer group** | `spectator-game-cg` |
| **Topic** | `game-events` |
| **Instances** | Scales with partition count; ≥10 instances (one per partition subset) |
| **Primary responsibility** | Apply privacy whitelist; update `PublicGameView` in Redis; append filtered events to Redis Streams; seal `PublicGameLog` on `GameCompleted` |

### 2.3 `spectator-tournament-consumer-worker`

| Property | Value |
|---|---|
| **Consumer group** | `spectator-tournament-cg` |
| **Topic** | `tournament-events` |
| **Instances** | 5–10 |
| **Primary responsibility** | Update `BracketView` and `SpectatorRoomList` on `TournamentRoomAssigned`, `MatchCompleted`, `RoundCompleted`, `TournamentCompleted` |

### 2.4 `spectator-ranking-consumer-worker`

| Property | Value |
|---|---|
| **Consumer group** | `spectator-ranking-cg` |
| **Topic** | `ranking-events` |
| **Instances** | 3–5 |
| **Primary responsibility** | Push leaderboard update notifications to connected spectator WebSocket clients on `EloUpdated`, `TournamentEloUpdated`, `EloReverted`; no ZADD (ranking-service maintains the authoritative sorted sets at `ranking:leaderboard:casual` / `ranking:leaderboard:tournament`) |

---

## 3. Privacy Enforcement

### 3.1 Non-Negotiable Privacy Contract

Spectators **never** receive card identities from any player's hand during an in-progress game. The following fields are always stripped before entering the read model:

| Event | Stripped field | Exposed substitute |
|---|---|---|
| `CardDrawn` | `card_identity` (the drawn card) | `new_hand_count` only |
| `PenaltyCardsDrawn` | `card_identities` (list of penalty cards) | `count`, `new_hand_count` |
| `WildDrawFourChallengeResolved` | `accused_hand_at_time` (full hand snapshot) | Appears only in `PublicGameLog` after `GameCompleted` |
| `RaceResolved` | `player_rtts` (individual RTT values per player) | `winner_player_id`, `resolution_method` |

Post-game, the `PublicGameLog` reveals hands (for dispute resolution) only to authorized consumers: admin users and the players themselves. Spectators may only access aggregate summaries from the log.

### 3.2 Filter Placement

The privacy whitelist filter is applied **at event consumption** — inside `spectator-game-consumer-worker`, before any data is written to Redis or PostgreSQL.

**Why at consumption (not at send):**
The read model itself never contains private data. A bug in the WebSocket fan-out layer (e.g., sending the wrong field from Redis) cannot leak hand information because the hand data is not in Redis. The filter is a structural guarantee, not a runtime check.

**Defense-in-depth at send layer:**
`spectator-service` also applies a secondary field filter when serializing events for WebSocket push. This adds no correctness value (the read model is already clean) but catches any future schema additions that include private fields by default. Failed secondary filter checks are logged as WARN for investigation.

### 3.3 Privacy Filter Implementation

The consumer runs a whitelist transform on each incoming event:

```
function applySpectatorFilter(event):
  allowed = WHITELIST[event.type]   // static map of event_type → allowed fields
  if allowed is null:
    return null  // event type not exposed to spectators at all (e.g., internal events)
  return pick(event, allowed)
```

The whitelist is defined per event type and is the single source of truth for what spectators see. Adding a new field to an event schema defaults to **not exposed** — it must be explicitly added to the whitelist.

---

## 4. Redis Streams Fan-Out (O6)

### 4.1 Rationale

Redis Pub/Sub was considered and rejected. See ADR-008 for the full comparison. The core problems with Pub/Sub for this use case:
- Fire-and-forget: a spectator that disconnects for 200ms misses all events published during the gap and must re-subscribe and receive a full snapshot (expensive at 100K concurrent games).
- No message history: catch-up requires a separate snapshot path that must be tightly coordinated with Pub/Sub delivery to avoid gaps.
- Pattern subscription cost: `PSUBSCRIBE spectator:game:*` with 100K active games taxes Redis pattern matching on every published message.

Redis Streams provide a small per-stream message history, allowing `XREAD` from a last-seen message ID without a separate snapshot-coordination protocol.

### 4.2 Stream Layout

| Key | Value |
|---|---|
| `spectator:stream:{game_id}` | Redis Stream; one entry per filtered game event |
| MAXLEN | `~200` (approximate trimming); keeps the last ~200 events per game in memory |
| TTL | Deleted (via `EXPIRE`) when `GameCompleted` is consumed + 24h buffer |
| Entry fields | `event_type`, `payload` (privacy-filtered JSON), `sequence_number`, `ts` |

The `XADD` command produces a monotonic stream entry ID (`{timestamp_ms}-{seq}`). Spectator clients track the last-received ID and resume from it on reconnect.

### 4.3 Consumer (Spectator-service → WebSocket)

Each `spectator-service` instance runs one goroutine/thread per subscribed WebSocket connection:

```
XREAD BLOCK 0 COUNT 10 STREAMS spectator:stream:{game_id} {last_id}
```

- `BLOCK 0` suspends until new entries arrive (no busy-polling).
- `last_id = $` on initial connect (only new events; snapshot handles prior state).
- `last_id = {client_last_seen_id}` on reconnect (catch-up from last-received event).

Multiple `spectator-service` instances may read from the same stream simultaneously — Redis Streams supports unlimited concurrent readers without consumer group coordination (consumer groups would serialize readers; here we want fan-out).

### 4.4 Spectator Connect / Reconnect Protocol

**Initial connect:**
1. Spectator connects WebSocket to `spectator-service`.
2. `spectator-service` reads `HGETALL spectator:gameview:{game_id}` from Redis (current PublicGameView), including `state_version` and `last_stream_id` written by the projection worker in the same update batch as the Hash fields.
3. `spectator-service` sends the snapshot to the client and records the snapshot's `state_version` and `last_stream_id`.
4. `spectator-service` begins `XREAD BLOCK ... STREAMS spectator:stream:{game_id} {last_stream_id}` so events committed after the snapshot are not missed.
5. Client receives a continuous stream of filtered events.

**Late join mid-game:**
1. The first payload is always a snapshot from `spectator:gameview:{game_id}`, not a full stream replay from `0-0`.
2. The service then tails the Redis Stream from the snapshot's `last_stream_id`.
3. If the Hash is missing but the stream still exists, the service reconstructs a bounded snapshot by reading `XREAD COUNT 200 STREAMS spectator:stream:{game_id} 0-0`; if neither exists, it returns `404 game_not_available`.
4. Redis retains approximately the last 200 filtered events per game plus a 24h post-completion TTL. This is enough for reconnect catch-up, while late joins use snapshot+delta to avoid replaying an entire active game.

**Reconnect after disconnect:**
1. Client reconnects with `?last_id={last_received_stream_id}` in the WebSocket handshake URL.
2. `spectator-service` reads `XREAD COUNT 200 STREAMS spectator:stream:{game_id} {last_id}` to retrieve missed events (up to MAXLEN limit).
3. If the last ID is older than what the stream retains (client was gone > full game worth of events), fall back to a fresh snapshot (step 2 above).
4. Resume live with `XREAD BLOCK` from the latest stream ID.

### 4.5 Stream Lifecycle

- Created on first `XADD` for a `game_id` (typically triggered by `GameStarted`).
- Populated for the duration of the game.
- On `GameCompleted` consumption: `spectator-game-consumer-worker` issues `EXPIRE spectator:stream:{game_id} 86400` (24h buffer for late-connecting spectators who missed the game end).
- `spectator:gameview:{game_id}` Redis Hash receives the same EXPIRE (24h).

---

## 5. Read Models

### 5.1 PublicGameView

**Store:** Redis Hash `spectator:gameview:{game_id}`  
**Staleness:** Updated synchronously as `spectator-game-consumer-worker` processes each event (consumer lag ≤1s under normal load).  
**Contents (privacy-filtered):**
```
player_count          — number of players still active
current_turn_player   — player_id whose turn it is
hand_counts           — map<player_id, int> (card count per player)
discard_top           — top card of discard pile (color, type)
direction             — clockwise | counter-clockwise
draw_pile_remaining   — estimated count (server-side only; omit if revealing draw pile info)
game_status           — waiting | in_progress | completed
state_version         — current game state version (for client ordering)
```

**Update mechanism:** On each filtered event, the worker uses `HSET` to update only the affected fields (not a full overwrite). Atomic field-level updates prevent spectators from seeing partially updated state.

**TTL:** Set to `EXPIRE spectator:gameview:{game_id} 86400` on `GameCompleted`.

### 5.2 PublicGameLog

**Store:** PostgreSQL `public_game_logs` table  
**Populated:** `spectator-game-consumer-worker` appends events to a staging table throughout the game; on `GameCompleted`, the log is sealed (status = `completed`, post-game hand reveals unlocked for authorized access).  
**Staleness:** Eventually consistent; up to a few seconds behind Room Gameplay's authoritative `game_events` log.  
**Schema:**
```sql
public_game_logs (
  id              BIGSERIAL PRIMARY KEY,
  game_id         UUID NOT NULL,
  sequence_number INT NOT NULL,
  event_type      TEXT NOT NULL,
  event_payload   JSONB NOT NULL,   -- privacy-filtered payload (no hands during game)
  post_game_data  JSONB,            -- hands and WD4 challenge details, populated on GameCompleted
  recorded_at     TIMESTAMPTZ NOT NULL,
  UNIQUE(game_id, sequence_number)
)
```

**Access:**
- Spectators: filtered view (no post_game_data unless game is completed and they have player authorization).
- Admin / dispute resolution: full access including post_game_data; authenticated via admin JWT with `admin:game_log:read` scope.

### 5.3 BracketView

**Store:** Redis Hash `spectator:bracket:{tournament_id}:round:{round_number}` (live) + PostgreSQL `bracket_views` table (persistent).  
**Staleness:** Redis updated within seconds of `MatchCompleted` / `RoundCompleted`; PostgreSQL version written on each round completion.  
**Contents:** Room assignments, match scores, advancement status per room, round winner list.

### 5.4 SpectatorRoomList

**Store:** Redis Hash `spectator:roomlist:{room_id}` per room; Redis Set `spectator:active_rooms` for list query.  
**Staleness:** Updated by `spectator-tournament-consumer-worker` on `TournamentRoomAssigned`, `RoomStatusChanged`, `GameCompleted`.  
**TTL:** `EXPIRE spectator:roomlist:{room_id} 3600` after `GameCompleted`.

### 5.5 LeaderboardView

**Store:** Redis Sorted Sets `ranking:leaderboard:casual` and `ranking:leaderboard:tournament`, owned and written exclusively by `ranking-service` (Leaderboard Redis instance). Spectator View reads directly from these authoritative sorted sets — no display copy is maintained.

**TTL:** No TTL (noeviction policy on Leaderboard Redis instance).  
**Query:** `ZRANGE ranking:leaderboard:casual 0 99 REV WITHSCORES` for top-100.

---

## 6. Events Consumed

### 6.1 From `game-events` (consumer group `spectator-game-cg`)

| Event | Action |
|---|---|
| `GameStarted` | Initialize `PublicGameView` Redis Hash; create Redis Stream for game |
| `CardPlayed` | Update discard_top, current_turn_player; XADD to stream |
| `CardDrawn` | Update hand_counts (strip card_identity); XADD to stream |
| `PenaltyCardsDrawn` | Update hand_counts (strip card_identities); XADD to stream |
| `TurnSkipped` | Update current_turn_player; XADD to stream |
| `DirectionReversed` | Update direction; XADD to stream |
| `ColorDeclared` | Update discard_top color; XADD to stream |
| `UnoAnnounced` | Update hand_counts; XADD to stream |
| `UnoChallengeResolved` | Update hand_counts; XADD to stream |
| `WildDrawFourChallengeResolved` | Update hand_counts (strip accused_hand_at_time); XADD to stream |
| `RaceResolved` | Update current_turn_player (strip player_rtts); XADD to stream |
| `PlayerForfeited` | Update hand_counts (remove player); XADD to stream |
| `PlayerDisconnected` | XADD to stream (no model update — status only) |
| `PlayerReconnected` | XADD to stream |
| `GameCompleted` | Seal PublicGameLog; set EXPIRE on Redis Stream and Hash; XADD to stream |

### 6.2 From `tournament-events` (consumer group `spectator-tournament-cg`)

| Event | Action |
|---|---|
| `TournamentRegistered` | — (no spectator view impact) |
| `TournamentStarted` | Initialize BracketView skeleton |
| `TournamentRoomAssigned` | Add room to SpectatorRoomList; update BracketView |
| `MatchCompleted` | Update BracketView with match result |
| `RoundCompleted` | Advance bracket, seal round standings in PostgreSQL |
| `TournamentCompleted` | Seal BracketView; persist final bracket to PostgreSQL |
| `TournamentCancelled` | Mark BracketView as cancelled |

### 6.3 From `ranking-events` (consumer group `spectator-ranking-cg`)

| Event | Action |
|---|---|
| `EloUpdated` | Push leaderboard update notification to connected spectator clients subscribed to leaderboard updates |
| `TournamentEloUpdated` | Push tournament leaderboard update notification to connected spectator clients |
| `EloReverted` | Push corrective leaderboard notification to connected spectator clients |

### 6.4 From `moderation-events` (consumer group `spectator-moderation-cg`)

| Event | Action |
|---|---|
| `GameResultVoided` | Mark game as voided in `PublicGameLog` (if sealed); update `PublicGameView` status if game is still live |
| `GameFlagged` | Add flagged indicator to `PublicGameView` for the game (visible badge in spectator UI) |

---

## 7. Anti-Corruption Layer

Spectator View treats all upstream events as external contracts — it does not share code or models with Room Gameplay, Tournament Orchestration, or Ranking. The Kafka event payload is the contract boundary.

The privacy whitelist in `spectator-game-consumer-worker` is the **anti-corruption layer** for game events: it translates the authoritative internal game event (which may contain hand data) into the spectator's bounded context representation (which never does). Any change to the game event schema that introduces new hand-bearing fields is only surfaced to spectators after an explicit whitelist update in this layer.

---

## 8. Dependencies on Other Contexts

| Upstream context | Dependency | Pattern |
|---|---|---|
| Room Gameplay | `game-events` Kafka topic (read-only) | Async event consumption; ACL |
| Tournament Orchestration | `tournament-events` Kafka topic (read-only) | Async event consumption |
| Ranking | `ranking-events` Kafka topic (read-only) | Async event consumption |
| Moderation | `moderation-events` Kafka topic (read-only) | Async event consumption: `GameResultVoided`, `GameFlagged` |
| Identity / Session | JWT validation (via API Gateway; not direct) | Gateway-enforced; Spectator service does not call Identity |

**No synchronous dependencies on Room Gameplay or Tournament Orchestration.** Spectator View is purely downstream.

---

## 9. Sequence Diagram: Game Event → Spectator Fan-Out

End-to-end path for a `CardPlayed` event:

```
Room Gameplay         Kafka            spectator-game-         Redis               spectator-service          Spectator Client
  (gameplay DB)     game-events        consumer-worker      (Streams/Hash)           (WebSocket holder)          (browser)
      │                 │                   │                     │                        │                         │
      │  [1] TX commit  │                   │                     │                        │                         │
      │  outbox row +   │                   │                     │                        │                         │
      │  game_events    │                   │                     │                        │                         │
      │─────────────────>                   │                     │                        │                         │
      │  [2] relay pub  │                   │                     │                        │                         │
      │  CardPlayed     │                   │                     │                        │                         │
      │                 │──────────────────>│                     │                        │                         │
      │                 │  [3] consume      │                     │                        │                         │
      │                 │  CardPlayed       │                     │                        │                         │
      │                 │                   │  [4] Privacy        │                        │                         │
      │                 │                   │  whitelist filter   │                        │                         │
      │                 │                   │  (keep: hand_counts │                        │                         │
      │                 │                   │   strip: card_id)   │                        │                         │
      │                 │                   │─────────────────────>                        │                         │
      │                 │                   │  [5] HSET spectator:│                        │                         │
      │                 │                   │  gameview:{game_id} │                        │                         │
      │                 │                   │  hand_counts        │                        │                         │
      │                 │                   │─────────────────────>                        │                         │
      │                 │                   │  [6] XADD spectator:│                        │                         │
      │                 │                   │  stream:{game_id}   │                        │                         │
      │                 │                   │  {filtered payload} │                        │                         │
      │                 │                   │                     │  [7] XREAD BLOCK       │                         │
      │                 │                   │                     │  returns new entry     │                         │
      │                 │                   │                     │<───────────────────────│                         │
      │                 │                   │                     │                        │  [8] Defense-in-depth  │
      │                 │                   │                     │                        │  secondary filter       │
      │                 │                   │                     │                        │  (verify no hand data) │
      │                 │                   │                     │                        │─────────────────────────>
      │                 │                   │                     │                        │  [9] WebSocket push    │
      │                 │                   │                     │                        │  CardPlayed (filtered) │
```

**Steps [4]–[5] are atomic per event**: the Redis Hash update and Stream append both happen in the consumer before the Kafka offset is committed. If the consumer crashes between [5] and [6], Redis has the updated Hash state but the Stream lacks the entry. On restart, the consumer re-reads the same Kafka offset and the second `HSET` is idempotent; `XADD` appends a new entry (minor duplicate acceptable; clients deduplicate by `sequence_number`).

**Step [7]** occurs in the `spectator-service` goroutine dedicated to this game_id's XREAD loop. Redis unblocks the `XREAD` call as soon as [6] completes. End-to-end latency (steps [1] → [9]): typically 50–200ms under normal load (dominated by Kafka consumer lag and network RTT).

---

## 10. Persistence Layer

| Store | Tables / Keys | Consistency | TTL / Retention |
|---|---|---|---|
| Redis (Streams) | `spectator:stream:{game_id}` | Eventual (consumer lag ≤1s) | game duration + 24h; MAXLEN ~200 |
| Redis (Hashes) | `spectator:gameview:{game_id}`, `spectator:roomlist:{room_id}` | Eventual | game/room duration + 24h |
| Redis (Sorted Sets) | `ranking:leaderboard:casual`, `ranking:leaderboard:tournament` (read-only; owned by Ranking) | Eventual | noeviction (perpetual) |
| PostgreSQL | `public_game_logs`, `bracket_views` | Eventual (append by consumer) | Indefinite (audit record) |

**No shared database** with Room Gameplay. The PostgreSQL `spectator` schema is separate from `gameplay`, `tournament`, and `identity` schemas.
