# Moderation / Admin Service

**Bounded context:** Moderation / Admin  
**Status:** Phase 5  
**Dependencies:** [PLAN.md](../PLAN.md); [design/COMMANDS_EVENTS.md](../../design/COMMANDS_EVENTS.md) §1.5; [specs/CONSTRAINTS.md](../../specs/CONSTRAINTS.md) §10

---

## 1. Purpose and Scope

Moderation owns the admin audit log and issues corrective commands to upstream contexts. It does not own player state, game state, or tournament state — it triggers changes in those contexts via authorized commands and events.

**Owns:**
- `AdminAction` aggregate — immutable audit log of every admin action taken
- `AbuseRecord` value object — tracks escalation state per player (violation counts, warnings, suspensions)
- Corrective command dispatch (suspend, ban, cancel tournament, void game result, flag game)
- Abuse escalation policy (rate-limit violation → automatic warning → suspension → admin review)

**Does NOT own:**
- Player profiles or sessions (owned by Identity/Session; Moderation issues corrective commands)
- Game state (owned by Room Gameplay; Moderation can request `ForceCompleteGame` but does not modify state directly)
- Tournament lifecycle (owned by Tournament Orchestration; Moderation can request `CancelTournament`)
- Elo records (owned by Ranking; Moderation triggers `EloReverted` via `GameResultVoided` event)

**Key constraint:** All admin endpoints require a JWT with an `admin` role claim. Every action is durably logged to the `admin_actions` audit table **before** the corrective command is dispatched (write-before-effect). The audit row is committed in its own transaction so no PostgreSQL lock is held during the HTTP call. A second transaction updates the row to `completed` or `failed` after the call returns. If the corrective command fails, the audit row is marked `failed` and the admin is notified.

---

## 2. Containers

| Container | Type | Responsibility |
|---|---|---|
| `moderation-service` | Long-running HTTP service (JVM or Go) | Admin command endpoints; FlagGame endpoint; abuse escalation; audit log; corrective command dispatch |
| `moderation-events-consumer-worker` | In-process background thread | Consumes `identity-events` for `ActionRateLimitExceeded` escalation |
| `moderation-outbox-relay-worker` | In-process background thread | Reads undelivered outbox rows, publishes to `moderation-events` Kafka topic, marks rows delivered |

All three run in the same deployed container. A single instance is sufficient for typical traffic (admin actions are low-frequency). Horizontal scaling is possible but rarely needed.

---

## 3. Public Synchronous Interfaces

All admin endpoints require a JWT with `role: admin`. Exposed via the API Gateway with admin JWT validation. The FlagGame endpoint is available to any authenticated player or spectator.

### 3.1 Player Moderation Commands

| Command | Method + Path | Notes |
|---|---|---|
| `SuspendPlayer` | `POST /v1/admin/players/{player_id}/suspend` | `{suspended_until, reason}`; idempotent by `(player_id, suspended_until)`; calls Identity/Session via HTTP mTLS |
| `BanPlayer` | `POST /v1/admin/players/{player_id}/ban` | `{reason}`; idempotent by `player_id`; calls Identity/Session via HTTP mTLS |

On success, the admin action is logged and forwarded to Identity/Session. Identity/Session invalidates the session, creates a reconnection window if the player is in an active game, and emits `PlayerSuspended`/`PlayerBanned` to `identity-events`.

### 3.2 Tournament Moderation Commands

| Command | Method + Path | Notes |
|---|---|---|
| `CancelTournament` | `POST /v1/admin/tournaments/{tournament_id}/cancel` | `{reason}`; idempotent by `tournament_id`; calls Tournament Orchestration via HTTP mTLS |

On success, Tournament Orchestration cancels the tournament, marks all active matches as cancelled, and emits `TournamentCancelled` to `tournament-events`. Ranking consumes `TournamentCancelled` and reverses any Elo updates.

### 3.3 Game Result Correction Commands

| Command | Method + Path | Notes |
|---|---|---|
| `VoidGameResult` | `POST /v1/admin/games/{game_id}/void` | `{reason}`; marks game result as voided in audit log; produces `GameResultVoided` on `moderation-events` |

### 3.4 Game Flagging (Player-Facing)

| Command | Method + Path | Notes |
|---|---|---|
| `FlagGame` | `POST /v1/games/{game_id}/flag` | Any authenticated player or spectator may flag a completed game for admin review. Rate-limited to 5 flags/hour per user (enforced at API Gateway, see §8). Idempotent by `(game_id, player_id)`. Produces `GameFlagged` on `moderation-events`. Precondition: game must be `completed`. Rejection: game not completed; already flagged by this user; rate limit exceeded. |

### 3.5 Admin Query Endpoints

| Query | Method + Path | Notes |
|---|---|---|
| `GetAdminActions` | `GET /v1/admin/actions?page=N&limit=50` | Paginated audit log; filterable by `player_id`, `admin_id`, `action_type` |
| `GetRateLimitViolations` | `GET /v1/admin/violations?player_id={player_id}` | Returns recent rate-limit violations for a player (sourced from `ActionRateLimitExceeded` events) |

---

## 4. Public Asynchronous Interfaces

### 4.1 Events Produced on `moderation-events` topic

**Partitioned by:** `player_id` (for player-level events) or `game_id` (for game-level events)  
**Produced via:** transactional outbox relay  
**Schema version:** `schema_version: 1` on all events

| Event | Idempotency key | Primary consumers |
|---|---|---|
| `GameResultVoided` | `game_id` | Ranking (Elo reversal), Spectator View |
| `GameFlagged` | `game_id + player_id` | Analytics (flag tracking) |

### 4.2 Events Consumed from `identity-events`

Consumer group: `moderation-events-cg`

| Event | Idempotency key | Action |
|---|---|---|
| `ActionRateLimitExceeded` | `player_id + action_type + timestamp` | Log the violation in `rate_limit_violations`. Evaluate abuse escalation thresholds (see §5). |

---

## 5. Abuse Escalation Policy

Per [`specs/CONSTRAINTS.md`](../../specs/CONSTRAINTS.md) §10.

### 5.1 Rate-Limit Escalation Chain

The API Gateway emits `ActionRateLimitExceeded` events (injected via the gateway's producer to the `identity-events` topic). Moderation consumes these events.

```
[Rate limit violation detected by API Gateway]
  → ActionRateLimitExceeded emitted to identity-events
  → Moderation consumes and logs violation
  → [5 violations within 10 min] PlayerAbuseWarningIssued
      → [3 warnings within 24 hours] PlayerSessionSuspended (15-minute cooldown)
          → SessionInvalidated → [if in game] ReconnectionWindowStarted
          → [after 15-min cooldown] suspension lifts automatically
          → [repeated suspensions within 7 days] flagged for admin review → potential PlayerBanned
```

| Check | Threshold | Action | Mechanism |
|---|---|---|---|
| Per-user rate limit exceeded | 5 violations in 10 minutes | `PlayerAbuseWarningIssued` event; player notified via WebSocket | Moderation produces event to `moderation-events`; API Gateway pushes notification to player |
| Per-user rate limit exceeded | 3 warnings in 24 hours | Auto-suspend for 15 minutes (`SuspendPlayer` with `suspended_until = now() + 15min`) | Moderation calls Identity/Session HTTP endpoint; Identity/Session emits `PlayerSuspended` |
| Per-IP rate limit exceeded | 5 different users from same IP in 1 hour | Flag IP for admin review | Logged to `rate_limit_violations`; admin dashboard alert |

The escalation policy is configurable via environment variables, not hardcoded.

### 5.2 Write-Before-Effect Invariant

Every admin action that dispatches an HTTP corrective command follows a **two-transaction** sequence so that no PostgreSQL lock is held during a network call:

1. **BEGIN** first transaction.
2. **INSERT** into `admin_actions` (audit row with `status = 'dispatching'`).
3. **COMMIT** — the audit row is durable before any downstream call.
4. **HTTP call** to the upstream service (outside any transaction): Identity/Session, Tournament Orchestration, or Room Gameplay.
5. **BEGIN** second transaction.
6. **UPDATE** `admin_actions` SET `status = 'completed'` / `'failed'`, `completed_at = now()`.
7. **COMMIT**.

If the service crashes between steps 3 and 6, the row remains with `status = 'dispatching'`. A background sweep (every 60s) queries `admin_actions WHERE status = 'dispatching' AND created_at < now() - INTERVAL '5 minutes'` and alerts the on-call operator to review and manually complete or void the action.

**For `GameResultVoided` and `GameFlagged`** (internal Kafka events): the audit row and the outbox row are written in a **single** transaction (no HTTP call, so no lock-duration issue). The `status` goes directly from `'dispatching'` to `'completed'` in the same commit.

The corrective command is **never** dispatched without the audit row being durably written first.

**For FlagGame (player-facing):** the same write-before-effect pattern applies — the flag is written to the `game_flags` table before the `GameFlagged` outbox row is inserted, both in the same transaction.

### 5.3 Admin Action Failure Handling

If a corrective HTTP command to Identity/Session or Tournament Orchestration fails (timeout, 5xx):

1. The moderation service retries up to 3 times with exponential backoff (1s, 2s, 4s).
2. If all retries fail, the action is logged in `admin_actions` with `status = 'failed'` and the admin is notified (dashboard alert or notification).
3. The admin can manually retry the action.

**Circuit breaker:** Moderation applies a circuit breaker on the HTTP client to each upstream service. If Identity/Session or Tournament Orchestration is down, the circuit breaker opens after 5 consecutive failures and closes after a 30s cooldown.

---

## 6. Persistence

### 6.1 PostgreSQL Schema (`moderation` schema)

```sql
CREATE TABLE admin_actions (
    id              BIGSERIAL PRIMARY KEY,
    admin_id        UUID NOT NULL,
    action_type     TEXT NOT NULL,     -- 'suspend_player', 'ban_player', 'cancel_tournament', 'void_game_result', 'flag_game'
    target_id       UUID NOT NULL,      -- player_id or tournament_id or game_id
    target_type     TEXT NOT NULL,      -- 'player', 'tournament', 'game'
    reason          TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'dispatching',  -- 'dispatching' | 'completed' | 'failed'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX ON admin_actions (admin_id, created_at DESC);
CREATE INDEX ON admin_actions (target_id, action_type);
CREATE INDEX ON admin_actions (status, created_at DESC);

CREATE TABLE game_flags (
    id              BIGSERIAL PRIMARY KEY,
    game_id         UUID NOT NULL,
    player_id       UUID NOT NULL,
    reason          TEXT,
    flagged_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(game_id, player_id)  -- idempotency: one flag per player per game
);

CREATE INDEX ON game_flags (game_id, flagged_at DESC);

CREATE TABLE rate_limit_violations (
    id              BIGSERIAL PRIMARY KEY,
    player_id       UUID NOT NULL,
    ip_address      INET,
    action_type     TEXT NOT NULL,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ON rate_limit_violations (player_id, occurred_at DESC);
CREATE INDEX ON rate_limit_violations (ip_address, occurred_at DESC);

CREATE TABLE moderation_outbox (
    id              BIGSERIAL PRIMARY KEY,
    event_type      TEXT NOT NULL,
    payload         JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered       BOOLEAN NOT NULL DEFAULT false,
    delivered_at    TIMESTAMPTZ
);

CREATE INDEX ON moderation_outbox (delivered, id) WHERE delivered = false;
```

**Consistency:** Strong (single PostgreSQL instance, append-only for audit and flag tables). The `admin_actions` row is written before the corrective command is dispatched (write-before-effect), in the same transaction for internal events (e.g., `GameResultVoided`) or with immediate dispatch + status update for HTTP calls.

---

## 7. Rate Limiting Map

Per [`specs/CONSTRAINTS.md`](../../specs/CONSTRAINTS.md) §10 and [PLAN.md](../PLAN.md) Redis/Rate Limiter section.

| Layer | Enforced by | Scope | Principal source | Limit |
|---|---|---|---|---|
| Per-IP | API Gateway | All traffic (unauthenticated + authenticated) | Source IP from TCP connection | 60 req/min (unauthenticated); 120 req/min (authenticated) |
| Per-user (general) | API Gateway | All authenticated requests | `player_id` from validated JWT | 30 game-action commands/min; 10 queue join/leave/min |
| Per-user (flag) | API Gateway | `FlagGame` endpoint only | `player_id` from validated JWT | 5 flags/hour per user (`ratelimit:user:<player_id>:flag:<bucket>`) |
| Per-game-action | Room Gameplay service | `PlayCard`, `DrawCard`, `JumpIn`, `CallUno`, `ChallengeWildDrawFour` | `player_id + game_id` from JWT + path | Domain-level limit (1 action per turn, 1 challenge per window) |
| Per-tournament-action | Tournament Orchestration | `RegisterForTournament`, `WithdrawFromTournament` | `player_id` from JWT | Domain-level limit (registration window restrictions) |
| Per-admin-action | Moderation service | Admin command endpoints | `admin_id` from JWT | Standard authenticated rate limit; no special limit needed |

**Redis key patterns (see PLAN.md Redis Usage Map):**

| Pattern | Redis structure | TTL |
|---|---|---|
| `ratelimit:ip:<ip>:<window_bucket>` | String + INCR | 60s (per window) |
| `ratelimit:user:<player_id>` | Sorted Set (sliding window ZSET) | 60s (refreshed on each request) |
| `ratelimit:user:<player_id>:flag:<bucket>` | String + INCR | 3600s (1 hour window) |
| `ratelimit:game:<player_id>:<action>:<bucket>` | String + INCR | 60s |

**Fail-open policy:** If Redis is unavailable, the API Gateway switches per-IP and per-user limits to a small local in-memory counter per gateway pod for up to 5 minutes (`player_id` / IP → fixed 60s bucket). This protects a single pod from obvious floods but does not coordinate globally, so the blast radius is bounded by the number of gateway pods an attacker can reach. If local memory pressure rises or the outage exceeds 5 minutes, limits fully fail open for availability and Moderation treats the Redis outage as an abuse-observability gap. Per-game-action domain limits are still enforced in Room Gameplay and do not depend on Redis.

---

## 8. Dependencies on Other Contexts

| Dependency | Direction | Mechanism | What is delegated |
|---|---|---|---|
| Identity/Session | Outbound command (HTTP, mTLS) | `SuspendPlayer`, `BanPlayer` | Player session invalidation and suspension enforcement |
| Tournament Orchestration | Outbound command (HTTP, mTLS) | `CancelTournament` | Tournament cancellation enforcement |
| Room Gameplay | Outbound command (HTTP, mTLS) | `ForceCompleteGame` (rare; primarily used by Tournament for match timeout) | Game resolution for admin-ordered game cancellation |
| API Gateway | Inbound | Admin JWT validation; rate-limit violation events forwarded; rate limit enforcement at edge | Authentication and rate limiting |
| Identity/Session | Inbound event | Consumes `identity-events` Kafka topic: `ActionRateLimitExceeded` | Abuse escalation input |
| Ranking | Outbound event (via `moderation-events`) | `GameResultVoided` | Elo reversal trigger for voided game results |
| Spectator View | Outbound event (via `moderation-events`) | `GameFlagged` | Flag visibility in spectator read model |

**No direct database access to other contexts.** All corrective actions are issued as commands to the owning context. The moderation audit log is the sole source of truth for what actions were taken, when, and by whom. Event production uses the transactional outbox pattern (same pattern as Room Gameplay, Identity/Session, and Tournament Orchestration) to ensure write-before-broadcast.
