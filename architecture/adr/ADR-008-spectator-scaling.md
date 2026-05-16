# ADR-008 — Spectator Fan-Out: Redis Streams over Pub/Sub

**Status:** Accepted  
**Context:** Spectator View → WebSocket fan-out to spectators  
**Decided:** Phase 4

---

## Context

The Spectator View service must deliver privacy-filtered game events to all spectators watching a given game in near-real time. The scale constraint is severe: at the first-round surge, up to 100,000 simultaneous games with a 10:1 spectator ratio implies up to 1,000,000 concurrent spectator connections. Within each game, events arrive at 2–10/second; spectators need events within ~200ms of Room Gameplay committing the action.

The key design challenge is how to fan-out events from the Kafka consumer (`spectator-game-cg`) to the potentially many WebSocket connections watching each game, across multiple `spectator-service` instances.

This ADR records why **Redis Streams per game_id** was chosen over **Redis Pub/Sub per game_id**.

---

## Options Considered

### Option A — Redis Pub/Sub per game_id (rejected)

Each `spectator-game-consumer-worker` publishes filtered events to a Redis Pub/Sub channel named `spectator:game:{game_id}`. Every `spectator-service` instance subscribes to the channels corresponding to games it has active spectators for. Events are forwarded from Redis to the WebSocket connection.

**Strengths:**
- Simple push model: publish once, every subscriber receives.
- Low-latency delivery: Pub/Sub messages are delivered sub-millisecond.
- Stateless from the publisher's perspective.

**Weaknesses:**

1. **Fire-and-forget / no message history.** Redis Pub/Sub delivers to currently subscribed clients only. A spectator that disconnects for 200ms (mobile network hiccup) misses all events published during the gap. On reconnect, the only recovery is a full snapshot from `PublicGameView` Redis Hash. But there is a race window between reading the snapshot and re-subscribing — events published between those two operations are silently lost. Closing this race correctly requires careful coordination logic (subscribe first, then snapshot, then replay events from snapshot timestamp) which effectively re-implements a message-history mechanism on top of Pub/Sub.

2. **No catch-up for late-joining spectators.** A spectator who joins mid-game receives a snapshot of current state, but has no access to the event stream history. They can observe current state but not "replay" recent events. For a game client that wants to show recent history (e.g., the last 10 cards played), this is a gap.

3. **100K channel pattern-subscription cost.** If a `spectator-service` instance uses `PSUBSCRIBE spectator:game:*` to receive all game events at once (to route to connected clients without per-game subscriptions), Redis evaluates the pattern against every published message across all channels. With 100K active game channels, this becomes an O(channels × messages) evaluation. At 10 events/second per game × 100K games = 1M events/second, pattern-matching overhead becomes significant. Per-channel `SUBSCRIBE` avoids pattern matching but requires 100K `SUBSCRIBE` calls per instance if each instance potentially serves spectators from any game.

4. **Reconnection handling complexity.** Pub/Sub is inherently stateless: there is no per-channel offset or last-delivered-message concept. All reconnection and catch-up logic must be built on top (snapshot + timestamp coordination), essentially duplicating the problem Redis Streams solves natively.

---

### Option B — Redis Streams per game_id (selected)

The `spectator-game-consumer-worker` appends each privacy-filtered event to a Redis Stream keyed by `spectator:stream:{game_id}` using `XADD`. Each `spectator-service` instance holds WebSocket connections and reads from the corresponding streams using `XREAD BLOCK 0`.

**Stream configuration:**
- MAXLEN: `~200` (approximate trimming via `XADD ... MAXLEN ~ 200`). Keeps the last ~200 events in memory; sufficient for catch-up after short disconnects.
- TTL: `EXPIRE spectator:stream:{game_id} 86400` issued on `GameCompleted` consumption. Stream is retained 24h after game end for late spectators.
- Entry format: `{event_type, payload (privacy-filtered JSON), sequence_number, ts}`.

**Producer:** `spectator-game-consumer-worker` — one `XADD` per event after the privacy filter.

**Consumer:** Each `spectator-service` instance runs one long-lived `XREAD BLOCK 0 STREAMS spectator:stream:{game_id} {last_id}` loop per active game. On new entries, events are forwarded to all WebSocket connections watching that game on this instance.

**Strengths:**

1. **Message history for catch-up.** On spectator reconnect, `XREAD COUNT 200 STREAMS spectator:stream:{game_id} {last_client_id}` retrieves all events since the client's last-seen stream ID. No gap, no race condition. The client tracks its last-received stream ID; reconnect means `XREAD` from that ID.

2. **No race between snapshot and live events.** When a new spectator joins mid-game, the protocol is: (a) read snapshot from `spectator:gameview:{game_id}`, (b) note the snapshot's `state_version`, (c) `XREAD` from `$` (newest) to start live. There is no gap because the snapshot and stream are written by the same consumer in order; the snapshot state is always at or behind the latest stream entry. The client can correlate `state_version` to know which stream events are already covered by the snapshot.

3. **No pattern-matching overhead.** Each `spectator-service` instance subscribes only to the streams of games it has active spectators for. A Redis Stream `XREAD BLOCK` is a point read on a single key. Multiple instances can concurrently `XREAD BLOCK` from the same stream key without coordination — Redis Streams fan-out natively to unlimited readers.

4. **Backpressure-friendly.** If `spectator-service` is slow to process, it simply reads fewer stream entries per `XREAD` call. The stream accumulates entries (up to MAXLEN). This provides natural flow control without requiring explicit ack.

**Weaknesses:**

1. **Memory cost.** Each active game has a stream in Redis memory. At MAXLEN 200, a typical stream entry is ~300 bytes, so 200 entries = ~60KB per game. At 100K concurrent games: 100K × 60KB = ~6GB of Redis memory for streams alone. This is significant but manageable with a dedicated Redis cluster sized for this workload. Streams are deleted after game end.

2. **Per-instance XREAD thread/goroutine per game.** Each `spectator-service` instance must maintain one blocking read loop per active game it has spectators for. In the worst case (every instance has spectators from every game), this is 100K concurrent `XREAD BLOCK` connections per instance — far too many. In practice, spectators for a given game cluster on a small number of instances (via consistent gateway routing or any-instance routing with Redis fan-out). With 50 `spectator-service` instances and 1M spectators, each instance serves ~20K spectator connections across many games, but a given game has spectators on ~5–10 instances. Each instance maintains `XREAD` loops only for the games it has spectators from. This is the correct operational model.

3. **No "push" from Redis.** Unlike Pub/Sub, Streams use a pull model (`XREAD BLOCK`). The blocking wait is efficient (Redis suspends the connection until data arrives), but the architecture is technically a long-poll rather than a true server push. In practice the latency difference is negligible (<1ms for the Redis server to unblock a waiting `XREAD`).

---

## Decision

**Use Redis Streams per game_id.**

---

## Rationale

### Correct Reconnection Semantics

The primary motivation is reconnection correctness. In a mobile-heavy spectator audience, brief disconnects (1–10 seconds) are common. With Pub/Sub, each disconnect requires a full snapshot re-fetch to re-establish state, which is expensive and introduces a race window. With Streams, reconnect is a cheap `XREAD` from the client's last ID — no snapshot needed for short gaps.

### Elimination of Snapshot-Pub/Sub Race

With Pub/Sub, the gap between "subscribe to channel" and "read current snapshot" is a coordination problem. Events published during this window are silently lost. Eliminating this race requires publishing into the snapshot timestamp, which is exactly what Streams provide for free via the stream ID ordering guarantee.

### Scale at 100K Concurrent Games

The Pub/Sub pattern-subscription option scales poorly with 100K channels. Per-channel `SUBSCRIBE` avoids pattern-matching but creates a management problem: each gateway pod must track which game channels to subscribe to based on which players/spectators it's serving. Redis Streams make this simpler: each `spectator-service` instance reads only the streams it has active WebSocket connections for, with no Redis-side subscription management.

### Memory Trade-off is Acceptable

The ~6GB Redis memory cost for 100K game streams at MAXLEN 200 is a known trade-off. It is managed by:
- Approximate MAXLEN trimming (Redis periodically trims; real memory is slightly above 200 entries per stream).
- Immediate `EXPIRE` on `GameCompleted` to free memory within 24h.
- Sizing the Redis cluster appropriately (this is a documented capacity input in CAPACITY_SKETCH.md).

---

## Consequences

- **`spectator-game-consumer-worker`** performs `XADD` after the privacy filter before committing the Kafka offset. The `spectator:gameview:{game_id}` Redis Hash and the Stream are updated in the same consumer iteration (not the same Redis transaction — acceptable; Hash update idempotent, Stream entry may duplicate on crash but clients deduplicate by `sequence_number`).
- **`spectator-service`** instances run one `XREAD BLOCK` goroutine/thread per active game they have spectators from. Each instance scales to ~10K concurrent XREAD connections (Redis supports this via multiplexed pipelining).
- **Memory:** ~6GB Redis for 100K concurrent game streams. Separate Redis instance (or cluster) from the timer DB and cache DB; eviction policy `noeviction` (streams must not be silently evicted mid-game). See CAPACITY_SKETCH.md.
- **Reconnect protocol:** client sends `?last_id={stream_id}` on WebSocket reconnect; `spectator-service` calls `XREAD COUNT 200 ...` for catch-up, then resumes `XREAD BLOCK`. If `last_id` is older than MAXLEN retains (very rare, implies >game-duration disconnect), falls back to full snapshot.
- **Stream lifecycle:** created on `GameStarted`; `EXPIRE 86400` set on `GameCompleted`.

---

## Stream vs. Pub/Sub Comparison Summary

| Property | Redis Pub/Sub | Redis Streams |
|---|---|---|
| Message history | None | Up to MAXLEN entries |
| Reconnect catch-up | Requires full snapshot | `XREAD` from last ID |
| Snapshot race condition | Present (subscribe → read → gap) | Absent (ordering guaranteed) |
| Memory per game | Negligible | ~60KB (MAXLEN 200) |
| 100K channel overhead | Pattern-match or per-channel subscribe cost | Per-stream XREAD BLOCK (point read) |
| Producer simplicity | Simple PUBLISH | XADD (nearly as simple) |
| Consumer fan-out | Native (all subscribers receive) | Native (multiple XREAD readers) |
| Fire-and-forget on drop | Yes (message lost if no subscriber) | No (message stays in stream) |
