# Identity / Session Service

**Bounded context:** Identity / Session  
**Phase:** 2  
**Dependencies:** [PLAN.md](../PLAN.md) resolved decisions R4, R6; O4 settled as Redis Pub/Sub.

---

## 1. Purpose and Scope

Identity / Session is the most upstream context in the system. It owns all player identity and session state and is the authoritative source for JWT validity.

**Owns:**
- `PlayerProfile` aggregate — username, region, account status, public statistics
- `PlayerSession` aggregate — `valid_sessions_from` timestamp, reconnection window, latency profile
- JWT issuance and invalidation
- Reconnection window lifecycle (creation → timer → expiry)
- Push-invalidation channel to the API Gateway

**Does NOT own:**
- Game state or room assignment (Room Gameplay context)
- Elo ratings (Ranking context)
- Tournament registration state (Tournament Orchestration context)
- Abuse escalation state (Moderation context — Moderation issues corrective commands to this service)

---

## 2. Containers

| Container | Type | Responsibility |
|---|---|---|
| `identity-service` | Long-running HTTP service | Auth commands, JWT issuance, session management, valid_sessions_from writes |
| `identity-outbox-relay-worker` | In-process background thread (within `identity-service`) | Reads undelivered outbox rows, publishes to Kafka, marks rows delivered |
| `timer-subscription-worker` | In-process background thread (within `identity-service`) | Subscribes to Redis keyspace expiry notifications for `identity:reconnect:*` keys, routes to reconnection window expiry handler |
| `game-state-projection-worker` | In-process background thread (within `identity-service`) | Consumes `game-events` Kafka topic (consumer group `identity-game-projection-cg`); maintains `player_active_games` table so the service knows which game a player is currently in when a session is invalidated |

All four run in the same deployed container. There is no separate deployment for the background workers.

---

## 3. Public Synchronous Interfaces

Base path: `/v1/` (all endpoints require a valid JWT unless noted).

### 3.1 Auth Commands (REST, via API Gateway)

| Command | Method + Path | Auth | Notes |
|---|---|---|---|
| `Register` | `POST /v1/auth/register` | None | `{username, password, region}`; idempotent by `username` |
| `Login` | `POST /v1/auth/login` | None | `{username, password}`; returns new JWT; invalidates prior session |
| `Logout` | `POST /v1/auth/logout` | JWT required | Invalidates the current session; triggers reconnection window if in active game |
| `ReconnectToGame` | `POST /v1/games/reconnect` | JWT required (valid new session) | Validates open reconnection window and emits `PlayerReconnected`; returns game state snapshot source |

All responses follow standard HTTP semantics:
- `200 OK` — command accepted; for Login: JWT in response body.
- `401 Unauthorized` — invalid credentials (Login) or invalid/expired JWT.
- `403 Forbidden` — account banned.
- `409 Conflict` — duplicate registration (Register); no open reconnection window (ReconnectToGame).

### 3.2 Internal Commands (from Moderation — mTLS, not exposed via API Gateway)

| Command | Method + Path | Notes |
|---|---|---|
| `SuspendPlayer` | `POST /v1/internal/players/{player_id}/suspend` | `{suspended_until: timestamp, reason}`; idempotent by `player_id + suspended_until` |
| `BanPlayer` | `POST /v1/internal/players/{player_id}/ban` | `{reason}`; idempotent by `player_id` |

On `SuspendPlayer` or `BanPlayer`: Identity/Session invalidates the player's current session (updates `valid_sessions_from`), creates a reconnection window if the player is in an active game, and emits `SessionInvalidated` → `PlayerSuspended`/`PlayerBanned` to the outbox. The corrective event is the output; the session invalidation is implicit.

### 3.3 Internal Query (from API Gateway — Redis cache miss only)

| Query | Method + Path | Notes |
|---|---|---|
| `GetValidSessionsFrom` | `GET /v1/internal/players/{player_id}/valid-sessions-from` | Returns `{player_id, valid_sessions_from}`. Only called on Redis cache miss; response is immediately cached by the gateway. mTLS required. |

---

## 4. Public Asynchronous Interfaces

**Topic produced:** `identity-events`  
**Partitioned by:** `player_id`  
**Produced via:** transactional outbox relay (same pattern as Room Gameplay)  
**Schema version field:** all events carry `schema_version: 1`

### 4.1 Events Produced

| Event | Idempotency key | Primary consumers |
|---|---|---|
| `PlayerRegistered` | `player_id` | Ranking (initialize EloRecord) |
| `SessionCreated` | `player_id + issued_at` | — (JWT delivered directly to client) |
| `SessionInvalidated` | `player_id + invalidated_at` | Room Gameplay (start PlayerDisconnected → reconnection watch), Tournament Orchestration |
| `ReconnectionWindowStarted` | `player_id + game_id` | Room Gameplay, Tournament Orchestration |
| `ReconnectionWindowExpired` | `player_id + game_id` | Room Gameplay (triggers `PlayerForfeited`) |
| `PlayerReconnected` | `player_id + game_id` | Room Gameplay (re-admits player to game state) |
| `PlayerSuspended` | `player_id + suspended_until` | Room Gameplay, Tournament Orchestration |
| `PlayerBanned` | `player_id` | Room Gameplay, Tournament Orchestration |

### 4.2 Events Consumed

**Topic:** `game-events` (consumer group: `identity-game-projection-cg`)

The `game-state-projection-worker` consumes a small subset of game events to maintain the `player_active_games` table:

| Event | Action |
|---|---|
| `GameStarted` | `UPSERT player_active_games (player_id, game_id, joined_at)` for each player in `player_ids` |
| `GameCompleted` | `DELETE FROM player_active_games WHERE game_id = $game_id` |
| `PlayerForfeited` | `DELETE FROM player_active_games WHERE player_id = $player_id AND game_id = $game_id` |

This table is an eventually consistent projection. The lag is negligible (milliseconds). A race between `Login` and a game the player just joined is extremely rare and acceptable: in the worst case, no reconnection window is created, and Room Gameplay forfeits the player when the session is invalidated (via `SessionInvalidated` → `PlayerDisconnected`). The game log records this as `reason: ReconnectionExpired` after the fact if the player attempts to reconnect.

---

## 5. Single-Active-Session Invariant

### Mechanism

1. On every authenticated request at the API Gateway:
   - Verify JWT signature locally (public key loaded at startup — no network call).
   - Read `identity:vsf:<player_id>` from Redis (Cache-Aside, 60s TTL with ±5s jitter).
   - Reject the request with `401` if `jwt.issued_at < valid_sessions_from`.
   - On Redis cache miss: call `GET /v1/internal/players/{player_id}/valid-sessions-from` on Identity/Session, cache the result with 60s TTL.

2. On new login:
   - Identity/Session issues a new JWT with the current server timestamp.
   - Updates `player_sessions.valid_sessions_from` to that timestamp in the same DB transaction that inserts the outbox row.
   - After commit: `DEL identity:vsf:<player_id>` from Redis (never UPDATE — avoids write-order race). The next Gateway request will miss the cache and re-read the fresh value.

### Ordering Guarantee

The domain invariant from `PlayerSession` §5 in `DOMAIN_MODEL.md` is preserved architecturally:

> The new session is always established before the old one is invalidated.

The DB transaction commits with the new `valid_sessions_from = new_jwt_issued_at`. The `SessionInvalidated` event is published to Kafka via the outbox relay only after the commit. Therefore, during the brief window between commit and relay delivery, the new JWT is already valid and the old one is invalid for new requests — but the gateway's cached value is stale until either the Redis Pub/Sub message arrives (sub-ms) or the cache TTL expires (≤60s). The old WebSocket connection is actively closed via the Pub/Sub path; all new requests use the new JWT.

---

## 6. Push-Invalidation Path (O4: Redis Pub/Sub)

### Flow

After a DB transaction committing a new `valid_sessions_from`, identity-service immediately executes:

```
PUBLISH session:invalidated:<player_id> <invalidated_at_timestamp>
```

This is a direct Redis publish (not through the outbox) — it is fire-and-forget.

Every `api-gateway` instance subscribes to `PSUBSCRIBE session:invalidated:*` on startup. On receipt:
1. The node searches its in-memory WebSocket connection registry for connections belonging to `<player_id>`.
2. For each connection found: checks if its JWT `issued_at` is older than `<invalidated_at_timestamp>`.
3. If yes: closes the WebSocket connection (sends a close frame).

### Failure Semantics

| Scenario | Behavior |
|---|---|
| Redis Pub/Sub message delivered | Gateway closes old WebSocket within milliseconds |
| Message lost (Redis restart, network blip) | Old connection continues until it submits a command; gateway then rejects the JWT with `401` and disconnects |
| Gateway instance down when message arrives | That instance's connections expire naturally when it restarts; no persistent state lost |

**This is acceptable.** The DB is the source of truth for token validity. Pub/Sub is the fast-path to terminate live connections without waiting for the next command. Security is not weakened by a missed message — the worst case is the old connection persisting until it next submits a command.

### Why Redis Pub/Sub over Alternatives

Full rationale in [ADR-005](../adr/ADR-005-session-invalidation-push.md).

---

## 7. Reconnection Window

### Creation Conditions

A reconnection window is created when ALL of the following are true:
1. A session is invalidated (`Login`, `Logout`, `SuspendPlayer`, or `BanPlayer` command processed).
2. `player_active_games` lookup returns a `game_id` for the player (i.e., the player is currently in an active game).

If the player is NOT in an active game, no window is created — no Redis key, no outbox entry for `ReconnectionWindowStarted`.

### Creation Sequence (within the DB transaction)

```
BEGIN:
  UPDATE player_sessions SET valid_sessions_from = <new_timestamp>
  INSERT reconnection_windows (player_id, game_id, started_at, expires_at, closed=false)
  INSERT identity_outbox: SessionInvalidated
  INSERT identity_outbox: ReconnectionWindowStarted {player_id, game_id, expires_at}
COMMIT
```

After commit (outside the transaction):
```
SET identity:reconnect:<player_id>:<game_id> "<uuid>" PX 60000 NX
DEL identity:vsf:<player_id>                    (invalidate vsf cache)
PUBLISH session:invalidated:<player_id> <ts>    (push-invalidation fast path)
```

The UUID stored in the Redis key matches the `reconnection_windows.id` column. On expiry, the handler fetches the token from the key name embedded in the keyspace notification and validates it against the PostgreSQL row before acting.

### Crash Recovery

On `identity-service` startup, a sweep runs:

```sql
SELECT player_id, game_id, expires_at, id AS uuid
FROM reconnection_windows
WHERE closed = false AND expires_at > now()
```

For each row returned:
```
SET identity:reconnect:<player_id>:<game_id> "<uuid>" PX <(expires_at - now()) in ms> NX
```

`NX` ensures this is a no-op if the key already exists (timer is still running). This restores any timers that were set before the crash, with the remaining TTL.

### Timer Expiry

The `timer-subscription-worker` subscribes to `__keyevent@<timer-db>__:expired`. On receiving an expiry notification for a key matching `identity:reconnect:*`:

1. Parse `player_id` and `game_id` from the key.
2. `SELECT * FROM reconnection_windows WHERE player_id = $1 AND game_id = $2 AND closed = false`.
3. If no open row found → no-op (window was already closed by reconnection).
4. If open row found:
   - `BEGIN` transaction:
     - `UPDATE reconnection_windows SET closed = true WHERE player_id = $1 AND game_id = $2`
     - `INSERT identity_outbox: ReconnectionWindowExpired {player_id, game_id}`
   - `COMMIT`
5. Outbox relay publishes `ReconnectionWindowExpired` to Kafka → `identity-events` → Room Gameplay issues `PlayerForfeited`.

**Idempotency:** The `closed = false` check makes double-expiry delivery a no-op.

### Cancellation on Reconnection

When `ReconnectToGame` is processed and a valid window is found:

```
BEGIN:
  UPDATE reconnection_windows SET closed = true WHERE player_id = $1 AND game_id = $2 AND closed = false
  INSERT identity_outbox: PlayerReconnected {player_id, game_id}
COMMIT

-- After commit:
Lua conditional DEL: if GET identity:reconnect:P1:G1 == <uuid> then DEL
```

The conditional DEL (same Lua script used for all timers in this system) cancels the Redis TTL without risk of cancelling a subsequent window for the same key.

---

## 8. Transactional Outbox

Identity/Session uses the transactional outbox pattern for all Kafka events, for the same reason as Room Gameplay: a crash between DB commit and Kafka publish must never lose a critical event (`ReconnectionWindowExpired` lost = forfeit never issued; `PlayerBanned` lost = banned player stays in game).

The relay is an in-process background thread with the same poll-publish-mark loop documented in `room-gameplay.md §5`.

### PostgreSQL Schema

```sql
-- Player identity and account status
CREATE TABLE player_profiles (
    player_id       UUID PRIMARY KEY,
    username        VARCHAR(50) UNIQUE NOT NULL,
    region          TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active',  -- active | suspended | banned
    suspended_until TIMESTAMPTZ,
    stats           JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Single-active-session state
CREATE TABLE player_sessions (
    player_id             UUID PRIMARY KEY REFERENCES player_profiles(player_id),
    valid_sessions_from   TIMESTAMPTZ NOT NULL,
    current_jwt_issued_at TIMESTAMPTZ,
    latency_profile       JSONB,
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Reconnection windows (authoritative; Redis TTL is the timer flag)
CREATE TABLE reconnection_windows (
    player_id  UUID NOT NULL,
    game_id    UUID NOT NULL,
    uuid       UUID NOT NULL,              -- matches Redis TTL key value; used as idempotency fence
    started_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    closed     BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (player_id, game_id)
);

-- Derived projection: which game a player is currently in
-- Updated by game-state-projection-worker consuming game-events
CREATE TABLE player_active_games (
    player_id UUID PRIMARY KEY,
    game_id   UUID NOT NULL,
    joined_at TIMESTAMPTZ NOT NULL
);

-- Outbox for Kafka events (same pattern as Room Gameplay)
CREATE TABLE identity_outbox (
    id           BIGSERIAL PRIMARY KEY,
    player_id    UUID NOT NULL,
    event_type   TEXT NOT NULL,
    payload      JSONB NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered    BOOLEAN NOT NULL DEFAULT false,
    delivered_at TIMESTAMPTZ
);

CREATE INDEX ON identity_outbox (delivered, id) WHERE delivered = false;
```

---

## 9. Mandatory Sequence Diagram — Login on New Device (Active Game)

This diagram shows the full push-invalidation path, including the reconnection window and the deferred forfeit 60 seconds later.

```
Client              API Gateway           identity-service          PostgreSQL        Redis             identity-outbox-relay    Kafka        All Gateways   Room Gameplay
  |                      |                      |                       |                |                       |                  |                |               |
  |--POST /v1/auth/------>|                      |                       |                |                       |                  |                |               |
  |  login {creds}       |                      |                       |                |                       |                  |                |               |
  |  [unauthenticated]   |--POST /v1/auth/------>|                       |                |                       |                  |                |               |
  |                      |  login               |                       |                |                       |                  |                |               |
  |                      |                      |--SELECT player_------->|                |                       |                  |                |               |
  |                      |                      |  sessions FOR UPDATE  |                |                       |                  |                |               |
  |                      |                      |<--row locked----------|                |                       |                  |                |               |
  |                      |                      |                       |                |                       |                  |                |               |
  |                      |                      |[1. Verify credentials]|                |                       |                  |                |               |
  |                      |                      |[2. Generate JWT       |                |                       |                  |                |               |
  |                      |                      |    issued_at: T_new]  |                |                       |                  |                |               |
  |                      |                      |[3. SELECT player_     |                |                       |                  |                |               |
  |                      |                      |   active_games WHERE  |                |                       |                  |                |               |
  |                      |                      |   player_id = P1      |                |                       |                  |                |               |
  |                      |                      |   → game_id: G1 found]|                |                       |                  |                |               |
  |                      |                      |                       |                |                       |                  |                |               |
  |                      |                      |--BEGIN transaction---->|                |                       |                  |                |               |
  |                      |                      |--UPDATE player_------->|                |                       |                  |                |               |
  |                      |                      |  sessions SET         |                |                       |                  |                |               |
  |                      |                      |  valid_sessions_from  |                |                       |                  |                |               |
  |                      |                      |  = T_new              |                |                       |                  |                |               |
  |                      |                      |--INSERT reconnection  |                |                       |                  |                |               |
  |                      |                      |  windows (P1,G1,uuid) |                |                       |                  |                |               |
  |                      |                      |--INSERT identity_     |                |                       |                  |                |               |
  |                      |                      |  outbox: SessionInval.|                |                       |                  |                |               |
  |                      |                      |  {player_id:P1,       |                |                       |                  |                |               |
  |                      |                      |   invalidated_at:T_new}|               |                       |                  |                |               |
  |                      |                      |--INSERT identity_     |                |                       |                  |                |               |
  |                      |                      |  outbox: Reconn.Win.  |                |                       |                  |                |               |
  |                      |                      |  Started {P1,G1,T+60s}|                |                       |                  |                |               |
  |                      |                      |--COMMIT--------------->|                |                       |                  |                |               |
  |                      |                      |<--ok------------------|                |                       |                  |                |               |
  |                      |                      |                       |                |                       |                  |                |               |
  |                      |                      |--SET identity:reconnect:P1:G1 "uuid" PX 60000 NX------------->|                  |                |               |
  |                      |                      |--DEL identity:vsf:P1->|                |                       |                  |                |               |
  |                      |                      |  (invalidate vsf cache)|               |                       |                  |                |               |
  |                      |                      |--PUBLISH session:-----+--------------->|                       |                  |                |               |
  |                      |                      |  invalidated:P1 T_new |                |                       |                  |                |               |
  |                      |<--200 OK: {jwt}-------|                       |                |                       |                  |                |               |
  |<--200 OK: {jwt}-------|                      |                       |                |                       |                  |                |               |
  |                      |                      |                       |                |                       |                  |                |               |
  | [All gateway nodes receive Pub/Sub message via PSUBSCRIBE]          |                |  <--session:invalidated:P1 T_new-----------+--------------->|               |
  |                      |                      |                       |                |                       |                  |                |[finds P1's old  |
  |                      |                      |                       |                |                       |                  |                | WS: iat < T_new]|
  |                      |                      |                       |                |                       |                  |                |[closes old WS]  |
  |                      |                      |                       |                |                       |                  |                |               |
  |                      |                      |                       | [outbox-relay polls identity_outbox]   |                  |               |               |
  |                      |                      |                       |<--SELECT undelivered rows--------------|                  |               |               |
  |                      |                      |                       |--rows returned----------------------->|                  |               |               |
  |                      |                      |                       |                |                       |--produce-------->|               |               |
  |                      |                      |                       |                |                       |  SessionInval.   |               |               |
  |                      |                      |                       |                |                       |  Reconn.Win.     |               |               |
  |                      |                      |                       |                |                       |  Started         |               |               |
  |                      |                      |                       |                |                       |<--ACK------------|               |               |
  |                      |                      |                       |<--UPDATE delivered=true----------------|                  |               |               |
  |                      |                      |                       |                |                       |                  | SessionInv.-->|               |
  |                      |                      |                       |                |                       |                  | Reconn.Win.-->|               |
  |                      |                      |                       |                |                       |                  |               |--SessionInval.|
  |                      |                      |                       |                |                       |                  |               |  consumed     |
  |                      |                      |                       |                |                       |                  |               |-->PlayerDisconnected|
  |                      |                      |                       |                |                       |                  |               |               |
  |                      |          [60 seconds later: Redis TTL expires]                |                       |                  |               |               |
  |                      |                      |<--keyspace notification:               |                       |                  |               |               |
  |                      |                      |   identity:reconnect:P1:G1 expired     |                       |                  |               |               |
  |                      |                      |[SELECT reconnection_windows WHERE      |                       |                  |               |               |
  |                      |                      |  P1, G1, closed=false → found]         |                       |                  |               |               |
  |                      |                      |--BEGIN transaction---->|                |                       |                  |               |               |
  |                      |                      |--UPDATE reconn.win.-->|                |                       |                  |               |               |
  |                      |                      |  SET closed=true      |                |                       |                  |               |               |
  |                      |                      |--INSERT identity_outbox: ReconnWinExpired {P1,G1}              |                  |               |               |
  |                      |                      |--COMMIT--------------->|                |                       |                  |               |               |
  |                      |                      |                       |                |                       |--produce-------->|               |               |
  |                      |                      |                       |                |                       |  ReconnWin.      |               |               |
  |                      |                      |                       |                |                       |  Expired {P1,G1} |               |               |
  |                      |                      |                       |                |                       |                  | ReconnWin.--->|               |
  |                      |                      |                       |                |                       |                  | Expired       |-->PlayerForfeited|
  |                      |                      |                       |                |                       |                  |               |               |
```

**Key properties:**
- The client receives the new JWT before the old session is invalidated in Kafka — no token gap.
- The Redis Pub/Sub message closes the old WebSocket sub-millisecond after commit, before the Kafka event propagates.
- The reconnection window timer survives process crashes: the startup sweep restores the Redis TTL key from the `reconnection_windows` PostgreSQL row.
- The forfeit is guaranteed: `ReconnectionWindowExpired` is in the outbox and will be delivered at-least-once even if the service crashes at expiry time.

---

## 10. Dependencies on Other Contexts

| Dependency | Direction | Mechanism | What is delegated |
|---|---|---|---|
| API Gateway | Inbound | HTTP REST | Auth commands; JWT validation cache-miss query |
| API Gateway | Outbound HTTP (mTLS, internal) | `POST /internal/push/{player_id}` — used to deliver the session-invalidation close frame and any reconnection prompts to a specific player's live WebSocket; 404 = player not connected (no-op) | Server-initiated WebSocket push for session lifecycle events |
| Moderation | Inbound | HTTP (mTLS, internal) | `SuspendPlayer`, `BanPlayer` corrective commands |
| Room Gameplay | Outbound event | Kafka `identity-events` topic | `SessionInvalidated` → Room Gameplay emits `PlayerDisconnected`; `ReconnectionWindowExpired` → `PlayerForfeited`; `PlayerSuspended`/`PlayerBanned` → `PlayerForfeited` if in active game |
| Tournament Orchestration | Outbound event | Kafka `identity-events` topic | `SessionInvalidated`, `PlayerSuspended`, `PlayerBanned` — Tournament Orchestration tracks eliminations |
| Ranking | Outbound event | Kafka `identity-events` topic | `PlayerRegistered` → Ranking creates `EloRecord` |
| Room Gameplay | Inbound event | Kafka `game-events` topic (read-only projection) | `GameStarted`, `GameCompleted`, `PlayerForfeited` → `player_active_games` table maintained |

**Anti-corruption layer:** The `game-state-projection-worker` consumes only three event types from `game-events` and discards all others. It never writes to Room Gameplay's schema. The projection is read-only and treated as eventually consistent.
