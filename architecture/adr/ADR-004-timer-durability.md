# ADR-004 — Timer Durability Mechanism

**Status:** Accepted  
**Context:** Room Gameplay service (turn timer, challenge windows); Identity/Session (reconnection window); Tournament Orchestration (match timeout)  
**Decided:** Phase 1 (O3)

---

## Context

Several domain rules are enforced by server-side timers:

| Timer | Duration | Enforced by |
|---|---|---|
| Turn timer | 45s | Room Gameplay |
| Uno! challenge window | 5s | Room Gameplay |
| WD4 challenge window | 5s | Room Gameplay |
| Reconnection window | 60s | Identity/Session |
| Match timeout | 20 min | Tournament Orchestration |

Each timer must:
- **Survive a process crash** — if the owning node dies, the timer must still fire.
- **Be idempotent on expiry** — if the expiry notification is delivered twice (e.g., two nodes both receive the keyspace event), only one side effect must occur.
- **Be cancellable early** — when the condition resolves before the timer fires (e.g., a player plays their card before the turn timer expires), the timer must be cancelled without a spurious side effect.
- **Be set atomically** — starting the same timer twice (e.g., during a partition recovery) must not result in two independent countdowns.

---

## Options Considered

### Option A — In-process timers (e.g., `ScheduledExecutorService`, `time.AfterFunc`)

A timer is an in-memory scheduled task created at runtime.

**Problem:** When the process crashes, all in-memory timers are lost. A new process has no record of running timers. A game could be stuck indefinitely because no TurnTimedOut is ever triggered after a crash.

**Verdict:** Rejected. Does not meet crash-survival requirement.

---

### Option B — PostgreSQL-backed timer table with polling worker

A `timers` table stores `(timer_id, fires_at, context_type, context_id)`. A polling worker runs `SELECT ... WHERE fires_at <= now() AND fired = false FOR UPDATE SKIP LOCKED` on a short interval (e.g., 1s).

**Strengths:** Durable; survives crashes; no additional infrastructure.

**Weaknesses:**
- Polling at 1s intervals adds up to 1s jitter to a 5s challenge window — 20% of the window. Polling at 100ms adds significant DB load at scale (100K concurrent games = 100K timer rows polled 10×/s).
- The 5-second Uno! challenge window requires sub-second precision. A polling-based approach cannot reliably fire within the required accuracy window without hammering the database.

**Verdict:** Rejected for real-time game timers. Acceptable only for coarse timers (match timeout at 20 min), but using one mechanism for all timers simplifies operations.

---

### Option C — Kafka delayed messages (scheduled delivery)

Produce a Kafka message with a target delivery timestamp; a Kafka Streams time-based window or external scheduler delays delivery.

**Strengths:** Reuses existing Kafka infrastructure.

**Weaknesses:**
- Kafka has no native delayed-message semantics. Implementing a delay requires a Kafka Streams topology with a time-based store or an external scheduler service — significant additional infrastructure.
- Cancelling a scheduled message is non-trivial: the timer-cancel event must overtake the delayed message in processing order, requiring a "cancelled" state check at consumption time.
- Adds ~100–500ms latency for very short timers (5s challenge window) due to Kafka poll intervals.

**Verdict:** Rejected. The operational complexity and latency characteristics make this a poor fit for sub-10-second game timers.

---

### Option D — Redis String with TTL + keyspace notifications (selected)

Each timer is stored as a Redis String key with a hard TTL:

```
SET gameplay:turn-timer:G1 "<uuid-token>" PX 45000 NX
```

Redis fires a keyspace expiry notification (`__keyevent@<db>__:expired`) when the key expires. All `room-gameplay-service` instances subscribe to these notifications. The first instance to process the notification handles the side effect.

The UUID token stored in the key is also persisted in the `game_sessions` JSONB state. On expiry, the handler:
1. Acquires the row lock on `game_sessions`.
2. Reads the current `timer_token` field from the state.
3. Compares it with the token from the expired-key notification.
4. If they match: the timer is still relevant → issue the side-effect command.
5. If they don't match: the timer was already superseded (turn advanced, game ended) → no-op.

Early cancellation uses a Lua script for conditional deletion (avoids race between check and delete):

```lua
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
else
  return 0
end
```

---

## Decision

**Use Redis String keys with hard TTLs and keyspace expiry notifications.**

---

## Rationale

1. **Crash-safe by design:** The timer lives in Redis, independent of the application process. If the owning node crashes, Redis continues the countdown. When the key expires, any living node receives the notification and handles it.

2. **Precision for short windows:** Redis TTL resolution is milliseconds. A 5-second challenge window can be set to ±10ms accuracy — far better than polling.

3. **Natural cancellation semantics:** Deleting the key (with the Lua conditional) is an O(1) operation that atomically cancels the timer without the possibility of a stale expiry firing.

4. **No-infrastructure delta:** Redis is already required for idempotency caches, leaderboards, and session invalidation. Using it for timers adds no new infrastructure.

5. **Idempotency via token fence:** The UUID token pattern ensures that even if two nodes both receive an expiry notification (can happen under Redis replication lag or network anomalies), only one can pass the token validation inside the row lock. The second is a no-op.

---

## Consequences

- **Redis must have keyspace notifications enabled:** `notify-keyspace-events KEA` in the Redis configuration. This has a small CPU cost but is well within operational norms.
- **Timer database eviction policy:** The Redis instance used for timers must have `noeviction` policy — a silently evicted timer key would mean the turn never times out. The timer database is separate from the cache database (which uses `allkeys-lfu`).
- **Notification delivery is best-effort:** Redis Pub/Sub (including keyspace notifications) is at-most-once. If all subscribed nodes are briefly disconnected when a key expires, the notification is lost. Two separate reconciliation sweeps compensate:

  **Turn-timer sweep (every 60s):** queries `game_sessions WHERE status = 'in_progress' AND (state->>'turn_started_at')::timestamptz < now() - INTERVAL '45s'` and no live `gameplay:turn-timer:<game_id>` key in Redis. Any matching game issues a synthetic `TurnTimedOut` command (same handler, same token fence).

  **Challenge-window sweep (every 2s):** queries `game_sessions WHERE status = 'in_progress' AND (state->>'challenge_window_opened_at')::timestamptz < now() - INTERVAL '5s' AND state->>'challenge_window_status' = 'open'`. Any matching game issues a synthetic `ChallengeWindowExpired` command. The 2-second sweep interval is necessary because a missed 5-second notification cannot be recovered by a 60-second sweep — the window would extend from 5s to 60s, violating the game rule. The sweep is cheap: it only touches games that have an open challenge window, which is a small subset of active games at any moment. The PostgreSQL query is indexed by `(status, challenge_window_status)` in the JSONB state or via a separate `challenge_windows_open` boolean column on `game_sessions`.
- **Redis restart:** On Redis restart, all timer keys and their TTLs are lost (unless AOF persistence is enabled). With AOF enabled (`appendfsync everysec`), timer keys survive most restarts. The reconciliation sweep handles any remaining gaps.
- **Token storage:** The timer token field is part of the `game_sessions` JSONB state. It is updated whenever a new timer is started and cleared when the game ends. No additional table is needed.

---

## Timer Lifecycle Summary

```
[TurnAdvanced event committed to PostgreSQL]
       │
       ▼
SET gameplay:turn-timer:G1 "uuid-xyz" PX 45000 NX
       │
   ┌───┴──────────────────────────────────────┐
   │ Player plays card before 45s             │ Timer fires at T+45s
   ▼                                          ▼
Lua conditional DEL                  Redis fires:
(cancel timer)                       __keyevent__:expired
                                     → gameplay:turn-timer:G1

                                     Handler (any living node):
                                     1. Acquire row lock on game_sessions G1
                                     2. Read timer_token from state JSONB
                                     3. Compare: "uuid-xyz" == "uuid-xyz" ✓
                                     4. Issue TurnTimedOut command
                                        → PlayerForfeited (or turn skip)
                                        → game_events + outbox appended
                                        → COMMIT
                                        → new turn timer SET for next player
```
