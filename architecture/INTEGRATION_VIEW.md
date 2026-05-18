# UnoArena — Integration View

This document specifies the communication patterns between every pair of components that interact, the pattern used (sync HTTP, async Kafka event, Redis Pub/Sub, Redis key), and the failure semantics for each integration. It also declares the client connection model as required by §6.3.

---

## 1. Client Connection Model

### 1.1 Protocol and Connection Termination

**Active players** connect via **WebSocket** (`wss://`) to the **API Gateway**. The gateway terminates TLS and the WebSocket connection, authenticates the player via JWT on upgrade, and forwards each incoming WebSocket frame as an HTTP POST to `room-gameplay-service` carrying the validated `player_id` and `game_id` in headers.

**Spectators** connect via **WebSocket** (`wss://`) to the **API Gateway**. The gateway performs TLS termination and JWT validation on the HTTP upgrade request, then **proxies the live WebSocket connection** to a `spectator-service` instance: the client-facing TCP connection stays at the gateway, but the gateway opens a persistent WebSocket connection to the selected `spectator-service` pod and bidirectionally forwards frames. The `spectator-service` instance therefore holds the effective application-level connection and reads Redis Streams directly to fan out filtered events. This distinguishes the spectator path (gateway → service WebSocket proxy) from the active-player path (gateway → service HTTP-per-command). Spectators subscribe to a specific game's stream via `wss://.../v1/spectator/games/{game_id}`.

**REST endpoints** (registration, login, tournament management, admin, analytics) are standard HTTPS requests terminated at the API Gateway and proxied to the appropriate service.

### 1.2 Per-Room Event Ordering

All game events for a given `game_id` are produced to the `game-events` Kafka topic partitioned by `game_id`. This guarantees **total order per game**: all consumers (Ranking, Spectator View, Tournament Orchestration, Analytics) receive events for the same game in the order they were committed.

For active players, ordering is naturally preserved by the synchronous request-response path: the player sends a command, receives the `200 OK` response (with events), and the gateway pushes those events to the player's WebSocket before any Kafka consumer has seen them.

**Broadcast to non-acting players in the same game:** The `200 OK` response from Room Gameplay includes the full event payload and a `notify_player_ids` list (all game participants). The API Gateway uses its in-memory connection registry to push the event to every other active player in the same game immediately, without waiting for Kafka. This keeps the hot-path latency low (sub-100 ms end-to-end) and avoids N individual HTTP calls from Room Gameplay to the Gateway. If a player is not connected on the Gateway instance handling the response, the event is silently skipped; the player will catch up on reconnect via the same `GET /v1/games/{game_id}/state` REST fallback used for reconnect snapshots.

Spectators receive events via Redis Streams (`XREAD BLOCK`), which delivers events in `XADD` order per stream.

### 1.3 Session Invalidation and Connection Termination

When a player's session is invalidated (new device login, suspension, ban), the push-invalidation path is:

1. Identity/Session publishes `PUBLISH session:invalidated:<player_id> <invalidated_at_timestamp>` to Redis Pub/Sub.
2. Every API Gateway instance (subscribed to `PSUBSCRIBE session:invalidated:*`) checks its in-memory connection registry for connections belonging to `<player_id>`.
3. Any connection whose JWT `issued_at` is older than `<invalidated_at_timestamp>` is closed immediately (WebSocket close frame).
4. **Passive-connection mitigation:** For connections idle >30 seconds (no inbound command), the gateway validates `valid_sessions_from` on outbound event pushes (game broadcasts, timer expiry). If stale, the connection is closed at that point.

If the Pub/Sub message is lost, the fallback is JWT validation on the next inbound command (which fails and disconnects the client). The maximum exposure window for a passive player is **30 seconds** (outbound push heartbeat), not the full 45-second turn timer.

### 1.4 Spectator Privacy

Spectator WebSocket connections never receive hand data or private game state. The privacy filter is applied at Kafka consumption by `spectator-game-consumer-worker`, before any data enters the Redis read model. Spectator connections are pure read-only: they receive filtered events and can query public read models (PublicGameView, BracketView, LeaderboardView) but cannot submit commands.

### 1.5 Reconnection Path

When a player reconnects after a disconnection (within the 60-second reconnection window):

1. Player calls `POST /v1/games/reconnect` (authenticated with new JWT).
2. Identity/Session validates the reconnection window, emits `PlayerReconnected` to Kafka, and cancels the reconnection timer.
3. Room Gameplay receives `PlayerReconnected` via `identity-events`, re-activates the player, and calls `POST /internal/push/{player_id}` on the API Gateway with the full `GameSession` state snapshot.
4. The Gateway delivers the snapshot to the player's WebSocket connection.

---

## 2. Rate Limiting

### 2.1 Rate Limiting Layers

| Layer | Scope | Deployable | Mechanism | Key Template | Limit |
|---|---|---|---|---|---|
| Per-IP | Unauthenticated requests (login, register) | API Gateway | Fixed-window counter (Redis `INCR`) | `ratelimit:ip:<ip>:<bucket>` | 60 requests/min per IP (unauthenticated); 120 requests/min (authenticated) |
| Per-user (general) | All authenticated requests | API Gateway | Sliding-window ZSET (Redis) | `ratelimit:user:<player_id>` | 30 game-action commands/min; 10 queue join/leave/min |
| Per-user (flag) | `FlagGame` endpoint only | API Gateway | Fixed-window counter (Redis `INCR`) | `ratelimit:user:<player_id>:flag:<bucket>` | 5 flags/hour per user |
| Per-game-action | Game commands (play-card, draw, challenge) | API Gateway + room-gameplay-service | Fixed-window counter (Redis) | `ratelimit:game:<player_id>:<action>:<bucket>` | 30 commands/min per player per action type |
| Per-admin-action | Moderation endpoints | API Gateway | Fixed-window counter (Redis) | `ratelimit:admin:<admin_id>:<action>:<bucket>` | 10 requests/min per admin per action |

**Identity mechanism:** The API Gateway extracts `player_id` from the JWT (authenticated requests) or source IP (unauthenticated). Room Gameplay receives `player_id` in headers (injected by Gateway) and applies per-action rate limits before command processing.

**Abuse escalation:** When a rate limit is exceeded, the API Gateway emits `ActionRateLimitExceeded` to `identity-events`. Moderation consumes it; after 5 violations in 10 minutes, `PlayerAbuseWarningIssued` is emitted; after 3 warnings in 24 hours, Moderation calls `SuspendPlayer` on Identity/Session. See moderation.md §5.

---

## 3. Integration Table

Every significant component-to-component integration is listed below. Each row specifies the direction, pattern, and failure semantics.

### 3.1 Gateway → Room Gameplay (game command path)

| From → To | Pattern | Rationale | Failure semantics |
|---|---|---|---|
| Client → API Gateway | WebSocket (wss://) | Full-duplex bidirectional; single persistent connection for all game commands and event pushes | Gateway closes connection on auth failure or rate limit; client reconnects |
| API Gateway → room-gameplay-service | HTTP POST (sync, mTLS over HTTP/2) | One command per request; response carries events synchronously; HTTP/2 multiplexing reduces connection count between Gateway and Room Gameplay | Circuit breaker: if Room Gameplay is unavailable, Gateway returns `503` to client; client retries with backoff. Timeouts: 5s connect, 10s read. |

### 3.2 Gateway → Room Gameplay (outbound push path)

| From → To | Pattern | Rationale | Failure semantics |
|---|---|---|---|
| room-gameplay-service → API Gateway | HTTP POST `/internal/push/{player_id}` (mTLS, internal) | Server-initiated WebSocket push for reconnect snapshots, timer-expiry side-effect broadcasts, and targeted game-event pushes when the Gateway fan-out path is unavailable (e.g., player on a different Gateway instance); Gateway looks up player's connection in in-memory registry and writes to WebSocket | `404` response = player not connected on that gateway instance (load balancer may have routed the push to a different instance than the one holding the connection). Room Gameplay treats `404` as a no-op and does not retry. **Client responsibility:** if the client reconnects but receives no server-pushed snapshot within 2 seconds, it must proactively call `GET /v1/games/{game_id}/state` to fetch the current `PublicGameView`. This REST fallback is always available as an explicit catch-up path. `200` = snapshot delivered. |

### 3.3 Gateway → Identity/Session (auth path)

| From → To | Pattern | Rationale | Failure semantics |
|---|---|---|---|
| API Gateway → identity-service | HTTP GET (sync, mTLS) — cache miss only | JWT validation is local; Redis cache-aside (`identity:vsf:<player_id>`) avoids calling Identity on every request. Call only on cache miss. | On Identity unavailable: Gateway serves from cache (stale `valid_sessions_from` is acceptable for up to 60s TTL). If cache miss AND Identity down: reject request with `503`. |

### 3.4 Identity → Gateway (session invalidation push)

| From → To | Pattern | Rationale | Failure semantics |
|---|---|---|---|
| identity-service → Redis Pub/Sub | `PUBLISH session:invalidated:<player_id> <timestamp>` | Fast-path push to terminate stale WebSocket connections sub-ms after session invalidation | Fire-and-forget. If Pub/Sub message is lost: stale connection persists until (a) next inbound command fails JWT validation, or (b) outbound push heartbeat check (30s) detects stale session. See ADR-005. |
| Redis Pub/Sub → API Gateway (all instances) | `PSUBSCRIBE session:invalidated:*` | Fan-out to all running gateway instances | Each instance processes independently. If an instance is down when message arrives, it misses it — no persistent state is lost; the instance will have no stale connections on restart. |

### 3.5 Outbox relay → Kafka (game events)

| From → To | Pattern | Rationale | Failure semantics |
|---|---|---|---|
| room-gameplay-service outbox-relay → Kafka `game-events` | At-least-once (idempotent producer, `enable.idempotence=true`, `acks=all`) | Guarantees eventual delivery of all committed game events. Idempotent producer prevents duplicate messages on retry. | If Kafka is unavailable: outbox rows remain `delivered=false`; relay retries with exponential backoff. No events are lost (durable in PostgreSQL). Room Gameplay command handling is unaffected — the `200 OK` to the client is sent after the DB commit, before Kafka delivery. |

### 3.6 game-events → Tournament Orchestration

| From → To | Pattern | Rationale | Failure semantics |
|---|---|---|---|
| Kafka `game-events` → tournament-service `tournament-game-cg` | At-least-once consumer | Consumes `GameCompleted`, `PlayerForfeited`, `GameStarted` to update match state | Consumer lag grows if Tournament Orchestration falls behind. Rebalance on pod failure. No backpressure on Room Gameplay (separate consumer group). Idempotent by `game_id` dedup key. |

### 3.7 Tournament → Room Gameplay (HTTP command path)

| From → To | Pattern | Rationale | Failure semantics |
|---|---|---|---|
| tournament-service → room-gameplay-service | HTTP POST (sync, mTLS) — `CreateRoom`, `AssignPlayersToRoom`, `ForceCompleteGame`, `StartNextGameInRoom` | Bo3 next-game trigger; match timeout resolution; room creation | Idempotent by `(room_id, game_sequence_number)` or `game_id`. On timeout or failure: tournament-service retries with the same idempotency key. After 3 retries: room creation failure → DLQ path (see tournament.md §6.5). |

### 3.8 Tournament → Room Gameplay (round-kickoff Kafka path)

| From → To | Pattern | Rationale | Failure semantics |
|---|---|---|---|
| tournament-service kickoff-outbox-relay → Kafka `tournament-kickoff` | At-least-once (idempotent producer, rate-limited to ≤1,000 rooms/s) | Handles 100K room creation surge (first-round fan-out). Rate limit prevents thundering herd. | Idempotent room IDs (`UUID5`); retries produce the same `room_id`. If Room Gameplay's consumer falls behind, Kafka lag grows naturally — no backpressure on the producer. DLQ for rooms failing after 3 retries. |

### 3.9 Identity → Room Gameplay (session lifecycle events)

| From → To | Pattern | Rationale | Failure semantics |
|---|---|---|---|
| identity-service → Kafka `identity-events` → room-gameplay-service `room-gameplay-identity-cg` | At-least-once consumer | `SessionInvalidated` → `PlayerDisconnected`; `ReconnectionWindowExpired` → `PlayerForfeited`; `PlayerSuspended`/`PlayerBanned` → `PlayerForfeited` | Consumer lag → delayed forfeit (acceptable: game continues until event arrives). Idempotent by event dedup key. |

### 3.10 Timer expiry → Room Gameplay (Redis keyspace notification)

| From → To | Pattern | Rationale | Failure semantics |
|---|---|---|---|
| Redis timer instance (keyspace notification) → room-gameplay-service `timer-subscription-worker` | At-most-once (Redis Pub/Sub) | Turn timer (45s), challenge window (5s) expiry notifications | If notification is lost: reconciliation sweep (turn-timer every 60s, challenge-window every 2s) catches stale timers. See ADR-004 and room-gameplay.md §6. |

### 3.11 Reconnection timer → Identity/Session (Redis keyspace notification)

| From → To | Pattern | Rationale | Failure semantics |
|---|---|---|---|
| Redis timer instance (keyspace notification) → identity-service `timer-subscription-worker` | At-most-once (Redis Pub/Sub) | Reconnection window (60s) expiry notification | If notification is lost: Identity startup sweep recovers unclosed windows; `ReconnectionWindowExpired` is produced via outbox (durable). |

### 3.12 Room Gameplay → Spectator View (via Kafka)

| From → To | Pattern | Rationale | Failure semantics |
|---|---|---|---|
| Kafka `game-events` → spectator-game-consumer-worker | At-least-once consumer; privacy filter at consumption | Spectator receives privacy-filtered events only; read model never contains hand data | Consumer lag → delayed live updates (acceptable: spectators can tolerate seconds of lag). Idempotent by `(game_id, state_version)`. |

### 3.13 Spectator View ← Redis Streams (fan-out to connected spectators)

| From → To | Pattern | Rationale | Failure semantics |
|---|---|---|---|
| spectator-game-consumer-worker → Redis `spectator:stream:{game_id}` | XADD per event; MAXLEN ~200 | Event history buffer for reconnect; spectators XREAD BLOCK for live delivery | If Redis is temporarily unavailable, spectator WebSocket connections stall; reconnection path serves snapshot from Redis Hash + XREAD for missed events. |

### 3.14 Room Gameplay → Ranking (via Kafka)

| From → To | Pattern | Rationale | Failure semantics |
|---|---|---|---|
| Kafka `game-events` → ranking-service `ranking-cg` | At-least-once consumer | `GameCompleted` triggers casual Elo update; `GameCompleted.game_type = 'casual'` determines Elo scope | Consumer lag → delayed Elo update (acceptable: rankings are eventually consistent). Idempotent by `game_id`. |

### 3.15 Tournament → Ranking (via Kafka)

| From → To | Pattern | Rationale | Failure semantics |
|---|---|---|---|
| Kafka `tournament-events` → ranking-service `ranking-tournament-cg` | At-least-once consumer | `TournamentCompleted` triggers tournament Elo update; `TournamentCancelled` triggers Elo reversal | Same eventual consistency as above. `EloReverted` is idempotent by `tournament_id`. |

### 3.16 Moderation → Identity/Session (HTTP, corrective)

| From → To | Pattern | Rationale | Failure semantics |
|---|---|---|---|
| moderation-service → identity-service | HTTP POST (sync, mTLS) — `SuspendPlayer`, `BanPlayer` | Admin-initiated corrective commands requiring immediate session termination | On Identity unavailable: Moderation retries with circuit breaker (3 attempts, exponential backoff). If all fail: Moderation logs the failure for admin review; the ban/suspension can also be picked up via `identity-events` once Identity recovers. |

### 3.17 Moderation → Tournament (HTTP, corrective)

| From → To | Pattern | Rationale | Failure semantics |
|---|---|---|---|
| moderation-service → tournament-service | HTTP POST (sync, mTLS) — `CancelTournament` | Admin-initiated tournament cancellation; requires sync confirmation for audit | Same circuit-breaker pattern. Failure blocks the cancellation (admin should retry manually). |

### 3.18 Moderation → Ranking (via Kafka, GameResultVoided)

| From → To | Pattern | Rationale | Failure semantics |
|---|---|---|---|
| moderation-service outbox relay → Kafka `moderation-events` → ranking-service `ranking-moderation-cg` | At-least-once consumer | `GameResultVoided` triggers casual Elo reversal for the voided game | Consumer lag → delayed Elo reversal (acceptable: voiding is an admin action, not time-critical). Idempotent by `game_id`. |

### 3.19 Moderation → Spectator View (via Kafka, GameFlagged)

| From → To | Pattern | Rationale | Failure semantics |
|---|---|---|---|
| Kafka `moderation-events` → spectator-service `spectator-moderation-cg` | At-least-once consumer | `GameFlagged` marks game for admin review in spectator read model | Consumer lag → delayed flag display (acceptable). Idempotent by `(game_id, player_id)`. |

### 3.20 Analytics event consumption

| From → To | Pattern | Rationale | Failure semantics |
|---|---|---|---|
| Kafka `game-events` → analytics-game-worker `analytics-game-cg` | At-least-once consumer; dedicated group (isolated from other consumers) | Isolated consumer group: Analytics lag does not affect Ranking, Spectator, or Tournament | ClickHouse insert failures → worker pauses, retries with backoff, Kafka offsets not committed. Lag drains when ClickHouse recovers. No backpressure on Room Gameplay. |

### 3.21 StartNextGameInRoom — pre-commit HTTP call

| From → To | Pattern | Rationale | Failure semantics |
|---|---|---|---|
| tournament-service → room-gameplay-service | HTTP POST `/v1/internal/rooms/{room_id}/games` (sync, mTLS) | Issues `StartNextGameInRoom` before tournament-service DB transaction commits | The call is made before the transaction commit. If the DB commit fails after the HTTP succeeds, Room Gameplay has created the game but tournament-service has no record. Recovery: when `GameStarted` arrives via `game-events`, tournament-service's `GameStarted` consumer detects a `game_id` with no matching `match_games` row and triggers a reconciliation lookup. The game is either absorbed (if the match eventually commits) or marked as orphaned and resolved via `ForceCompleteGame` after a timeout. This is documented in tournament.md §5.2. |

---

## 4. Cross-Context Sequence Diagrams

### 4.1 Tournament Game Completion → Match Outcome → Round Advancement

This diagram traces the path from a player's winning `PlayCard` command through match-series tracking and into round advancement. Spans Room Gameplay, Tournament Orchestration, Ranking, and Spectator View.

```
room-gameplay-service    Kafka (game-events)    tournament-service    Kafka (tournament-events)    ranking-service    spectator-service
        |                        |                      |                        |                       |                   |
[PlayCard accepted]              |                      |                        |                       |                   |
[GameCompleted written          |                      |                        |                       |                   |
 to game_events + outbox]       |                      |                        |                       |                   |
        |                        |                      |                        |                       |                   |
[outbox-relay publishes]-------->|                      |                        |                       |                   |
        |           GameCompleted|                      |                        |                       |                   |
        |           {game_id,    |                      |                        |                       |                   |
        |            match_id,   |---GameCompleted------>|                        |                       |                   |
        |            placements, |  (tournament-game-cg)|                        |                       |                   |
        |            game_type:  |                      |                        |                       |                   |
        |            tournament} |  [SELECT FOR UPDATE  |                        |                       |                   |
        |                        |   matches WHERE      |                        |                       |                   |
        |                        |   match_id = M1]     |                        |                       |                   |
        |                        |  [UPDATE match_wins] |                        |                       |                   |
        |                        |  [INSERT match_games]|                        |                       |                   |
        |                        |                      |                        |                       |                   |
        |                        |                [player A reached 2 wins → match over]                |                   |
        |                        |                      |                        |                       |                   |
        |                        |  [COMMIT: match_games|                        |                       |                   |
        |                        |   + tournament_outbox|                        |                       |                   |
        |                        |   rows: MatchCompleted,                        |                       |                   |
        |                        |   AdvancementResolved]                         |                       |                   |
        |                        |                      |                        |                       |                   |
        |                        | [tournament-kickoff-outbox relay]              |                       |                   |
        |                        |                      |---MatchCompleted------->|                       |                   |
        |                        |                      |   {match_id, winner,   |                       |                   |
        |                        |                      |    tournament_id,      |                       |                   |
        |                        |                      |    round_id}           |                       |                   |
        |                        |                      |---AdvancementResolved->|                       |                   |
        |                        |                      |                        |---MatchCompleted------>|                   |
        |                        |                      |                        |  (spectator-          |                   |
        |                        |                      |                        |   tournament-cg)      |---update BracketView|
        |                        |                      |                        |                       |   push bracket WS|
        |                        |                      |                        |                       |                   |
[If round is complete (all matches done):] 
        |                        |                      |                        |                       |                   |
        |                        |                      |[Tournament Orchestration detects all matches complete]             |
        |                        |                      |[INSERT tournament_outbox: RoundCompleted]       |                   |
        |                        |                      |---RoundCompleted------->|                       |                   |
        |                        |                      |                        |---RoundCompleted------>|                   |
        |                        |                      |                        |  (ranking-tournament-cg)|---[update bracket/standings]
        |                        |                      |                        |                       |                   |
[If tournament is over (final round):
        |                        |                      |---TournamentCompleted-->|                       |                   |
        |                        |                      |                        |                       |                   |
        |                        |                      |                        |---TournamentCompleted->|                   |
        |                        |                      |                        |  (ranking-tournament-cg)                  |
        |                        |                      |                        |  [UPDATE tournament_elo]                  |
        |                        |                      |                        |  [INSERT elo_deltas]   |                   |
        |                        |                      |                        |  [INSERT ranking_outbox: TournamentEloUpdated]
        |                        |                      |                        |---TournamentEloUpdated->|                   |
        |                        |                      |                        |  (spectator-ranking-cg) ---update leaderboard WS
```

**Key causal chain:**
1. `GameCompleted` is written to `game_events` + `outbox` atomically before Kafka receives it.
2. Tournament Orchestration's `GameCompleted` handler runs under a row lock on `matches` — no race between game-3 completion and match-timeout.
3. `MatchCompleted` and `AdvancementResolved` are written to `tournament_outbox` in the same transaction as the `matches` update.
4. Tournament Elo is updated only once per `TournamentCompleted`, never per game (Elo scope invariant).

---

### 4.2 Casual Game Completion → Elo Update

This diagram traces the path from a casual game ending through Elo computation, leaderboard update, and display to other players.

```
room-gameplay-service    Kafka (game-events)    ranking-service    Redis (leaderboard)    spectator-service    Client
        |                        |                    |                    |                     |               |
[Last card played:               |                    |                    |                     |               |
 GameCompleted written           |                    |                    |                     |               |
 to game_events + outbox]        |                    |                    |                     |               |
[game_type: "casual",            |                    |                    |                     |               |
 placements: [{P1, rank:1},      |                    |                    |                     |               |
              {P2, rank:2},      |                    |                    |                     |               |
              {P3, rank:3}],     |                    |                    |                     |               |
 forfeited: [],                  |                    |                    |                     |               |
 non_placed: []]                 |                    |                    |                     |               |
        |                        |                    |                    |                     |               |
[outbox-relay publishes]-------->|                    |                    |                     |               |
        |           GameCompleted|                    |                    |                     |               |
        |           {game_id,    |---GameCompleted---->|                    |                     |               |
        |            game_type:  |  (ranking-cg)      |                    |                     |               |
        |            "casual",   |                    |                    |                     |               |
        |            placements} |  [check dedup:     |                    |                     |               |
        |                        |   last_casual_game_id != game_id]       |                     |               |
        |                        |  [check outcome:   |                    |                     |               |
        |                        |   outcome='abandoned'→skip]             |                     |               |
        |                        |  [SELECT FOR UPDATE |                    |                     |               |
        |                        |   elo_records WHERE|                    |                     |               |
        |                        |   player_id IN (P1,P2,P3)               |                     |               |
        |                        |   ORDER BY player_id]                   |                     |               |
        |                        |   -- consistent lock order prevents deadlock               |               |
        |                        |  [compute pairwise Elo deltas]          |                     |               |
        |                        |  [K-factor: P1→K=16,|                    |                     |               |
        |                        |             P2→K=32,|                    |                     |               |
        |                        |             P3→K=12]|                    |                     |               |
        |                        |  [UPDATE casual_elo per player]         |                     |               |
        |                        |  [INSERT elo_deltas (audit)]            |                     |               |
        |                        |  [INSERT ranking_outbox: EloUpdated×3]  |                     |               |
        |                        |  [COMMIT]          |                    |                     |               |
        |                        |                    |                    |                     |               |
        |                        |  [ranking outbox relay]                 |                     |               |
        |                        |                    |--ZADD ranking:------>|                     |               |
        |                        |                    |  leaderboard:casual  |                     |               |
        |                        |                    |  <elo> <player_id>  |                     |               |
        |                        |   (×3, one per player)                  |                     |               |
        |                        |                    |                    |                     |               |
        |                        |---EloUpdated------->|                    |---EloUpdated-------->|               |
        |                        |  (spectator-        |                    | (spectator-ranking-cg)|               |
        |                        |   ranking-cg)       |                    | [update LeaderboardView in Redis]    |
        |                        |                    |                    |                     |               |
        |                        |                    |                    |                     |---push leaderboard
        |                        |                    |                    |                     |   update WS-->|
```

**Key invariants shown:**
- `game_type: "casual"` gates the Elo update — tournament games never trigger this path.
- Forfeited players receive rank N (last place), counted in the Elo computation (see ranking.md §5.3).
- The dedup check (`last_casual_game_id != game_id`) at the start of the Ranking handler makes the entire handler idempotent.
- Elo is updated for **all** players in the same atomic PostgreSQL transaction — no partial update possible.

---

## 5. Integration Pattern Summary

| Pattern | Used for | Rationale |
|---|---|---|
| **Sync HTTP (mTLS)** | Gateway → services (command routing); Tournament → Room Gameplay (room creation, game start); Moderation → Identity/Tournament (corrective commands); Reconnect snapshot push (Gateway push endpoint) | Commands requiring immediate acknowledgment; idempotent retries safe via dedup keys |
| **Async Kafka (at-least-once)** | All cross-context event delivery (game-events, tournament-events, identity-events, moderation-events, ranking-events) | Decouples producers from consumers; natural fan-out for spectator, ranking, analytics; backpressure isolation via separate consumer groups |
| **Kafka (at-least-once producer)** | Room Gameplay outbox relay, Identity outbox relay, Tournament outbox relay | Ensures events are not lost between DB commit and Kafka publish; idempotent producer prevents duplicates |
| **Redis Pub/Sub (fire-and-forget)** | Session invalidation push (Identity → Gateway) | Sub-ms fan-out to all gateway instances; fire-and-forget acceptable because DB is source of truth |
| **Redis keyspace notification (at-most-once)** | Timer expiry (turn, challenge, reconnection, match timeout) | Sub-ms precision for short timers; reconciliation sweep compensates for lost notifications (ADR-004) |
| **Redis Streams (fan-out)** | Spectator event delivery per game_id | Preserves event history for reconnect; unlimited concurrent readers; `XREAD BLOCK` for live delivery |
| **Redis cache-aside** | `valid_sessions_from`, idempotency keys | Reads from cache on every request; cache miss falls through to PostgreSQL; TTL-based staleness acceptable |
| **Redis String TTL (timer)** | Turn timer, challenge window, reconnection window, match timeout | Millisecond precision; survives process crashes; token fence for idempotency |