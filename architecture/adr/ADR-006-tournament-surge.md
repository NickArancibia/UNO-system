# ADR-006 — Tournament Round-Kickoff Surge Architecture

**Status:** Accepted  
**Context:** Tournament Orchestration → Room Gameplay  
**Decided:** Phase 3

---

## Context

At `StartTournament`, up to 1,000,000 confirmed players must be placed into approximately 100,000 rooms simultaneously. All rooms must be created, players assigned, and lobby timers started within a short window (design target: all rooms accepting players within ≤120 seconds of kickoff). This is the highest-throughput coordinated write in the entire system.

The core challenge is **fan-out at scale**: Tournament Orchestration must distribute 100K room-creation workloads to Room Gameplay without:
1. Overwhelming Room Gameplay's PostgreSQL with a thundering herd of concurrent inserts.
2. Creating a bottleneck in Tournament Orchestration itself.
3. Losing room assignments if either service crashes mid-surge.

This ADR records why Kafka partitioned fan-out with a dedicated `tournament-kickoff` topic was chosen over an internal PostgreSQL work queue.

---

## Options Considered

### Option A — Kafka Partitioned Fan-out (selected)

Tournament Orchestration publishes one `TournamentRoomAssigned` event per room to a dedicated `tournament-kickoff` topic, partitioned by `room_id`. Room Gameplay instances subscribe as a consumer group, each owning a partition subset. Room creation is driven by event consumption.

**Producer:** `kickoff-outbox-relay-worker` in tournament-service drains the `kickoff_outbox` table at ≤1,000 rooms/s using a rate-limited relay loop.

**Consumer:** `tournament-kickoff-consumer-worker` in each room-gameplay-service pod. With 100 partitions and 50 pods (2 partitions each), up to 50 rooms are created concurrently. At ~10ms per room (PostgreSQL insert), this yields ~5,000 rooms/s — well above the 1,000/s producer rate.

**Backpressure:** Kafka consumer lag is the natural signal. If Room Gameplay workers fall behind, lag grows but workers are never overwhelmed — they only process events as fast as their PostgreSQL can absorb. The producer rate limit (~1,000/s) ensures steady input regardless of consumer pace.

**Failure:** At-least-once delivery with idempotent room creation (deterministic UUID5 room IDs). Failed rooms after N retries go to `tournament-kickoff-dlq` topic; tournament-service DLQ consumer handles recovery.

---

### Option B — Internal PostgreSQL Work Queue

Tournament Orchestration writes 100K room assignments to a local `room_kickoff_queue` table. A pool of worker threads (within tournament-service) reads from this table using `SELECT FOR UPDATE SKIP LOCKED` and calls `POST /v1/internal/rooms` on Room Gameplay via HTTP.

**Rate limiting:** Enforced at the HTTP layer — tournament-service workers throttle their call rate to avoid overwhelming Room Gameplay.

**Failure:** If a worker crashes mid-call, the queue row remains unlocked (after lock timeout) and another worker retries. Idempotent room IDs still apply.

**Strengths:** No new Kafka topic. No change to Room Gameplay's consumer infrastructure. Simpler operational topology.

**Weaknesses:**
- Backpressure is explicit HTTP rate-limiting rather than natural queue lag — harder to tune under variable Room Gameplay throughput.
- HTTP call latency (round-trip per room) bounds throughput more tightly than Kafka batch delivery.
- Tournament Orchestration must maintain its own thread pool sized for the surge; this pool is otherwise idle between tournaments.
- Room Gameplay's HTTP layer becomes a synchronous bottleneck: a slow response from Room Gameplay blocks the caller thread, potentially reducing throughput during the surge.
- The work queue (PostgreSQL) and the Room Gameplay write path are separate systems with no natural backpressure connection.

---

## Decision

**Use Kafka partitioned fan-out with a dedicated `tournament-kickoff` topic.**

---

## Rationale

### Natural Backpressure

Kafka consumer lag is a first-class observable: if Room Gameplay is struggling, the lag metric grows and alerts fire before any work is dropped. With the HTTP approach, backpressure must be engineered explicitly (retry queues, circuit breakers, caller throttle). At 100K rooms, an HTTP-layer design under load is prone to thundering-herd retry storms even with careful implementation.

### Decoupling of Producer and Consumer Throughput

The Kafka approach decouples the *rate at which Tournament Orchestration generates assignments* from the *rate at which Room Gameplay creates rooms*. The producer drains its kickoff_outbox at a steady 1,000/s; consumers scale independently. This means Room Gameplay can be scaled (adding pods) to absorb the surge without any change to tournament-service.

### Idempotency is the Same Either Way

Both options require idempotent room creation by pre-assigned deterministic room IDs. The Kafka option does not add idempotency complexity.

### No New Dependency at Room Gameplay HTTP Layer

With Option B, Room Gameplay's internal HTTP endpoint (`POST /v1/internal/rooms`) becomes a surge target — all 50 tournament-service worker threads hammer it simultaneously. With Option A, Room Gameplay's Kafka consumer processes events at its own pace. The HTTP endpoint (`POST /v1/internal/rooms`) is retained only for non-surge use cases (e.g., the FinalRoom creation when ≤10 players remain).

### Operational Observability

Kafka consumer lag on `tournament-kickoff` is a direct, quantifiable measure of kickoff progress. At 1,000 rooms/s production and 5,000 rooms/s consumption capacity, the entire 100K-room queue drains in ~100 seconds. Ops can watch lag decrease to zero as confirmation that all rooms were created.

---

## Consequences

- **New `tournament-kickoff` topic** must be provisioned with ≥100 partitions to support 50–100 Room Gameplay consumer pods.
- **Room Gameplay gains a new consumer worker** (`tournament-kickoff-consumer-worker`) — this is an in-process thread in the same pod; no new deployment.
- **`tournament-kickoff` topic retention** is set to 7 days (same as `game-events`). Under normal operation, messages are consumed within minutes; the retention is a safety net.
- **Kickoff outbox isolation:** The `kickoff_outbox` table in tournament-service is separate from the main `tournament_outbox` so that the rate-limited relay does not interfere with normal tournament event delivery.
- **DLQ consumer added:** tournament-service adds a consumer for `tournament-kickoff-dlq` to handle rooms that repeatedly fail creation. This is a low-frequency path (expected zero failures under normal conditions).
- **Monitoring:** Key metrics: `tournament-kickoff` consumer lag per consumer group, `kickoff_outbox.delivered = false` row count (should approach zero within 120s of kickoff), `room_kickoff_failures` table size.

---

## Tournament-Kickoff Topic Specification

| Property | Value |
|---|---|
| Topic name | `tournament-kickoff` |
| Partition key | `room_id` |
| Partition count | ≥100 (one Room Gameplay pod per 1–2 partitions at scale) |
| Replication factor | 3 |
| Retention | 7 days |
| Producer | tournament-service `kickoff-outbox-relay-worker` (idempotent producer, `acks=all`) |
| Consumer group | `room-gameplay-kickoff-cg` (Room Gameplay pods) |
| DLQ topic | `tournament-kickoff-dlq` (3 retries before routing) |
| DLQ consumer | tournament-service `tournament-dlq-cg` |
