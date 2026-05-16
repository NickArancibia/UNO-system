# ADR-002 — Message Broker Selection

**Status:** Accepted  
**Context:** All cross-context async event delivery (game-events, tournament-events, identity-events, moderation-events, ranking-events, tournament-kickoff)  
**Decided:** Phase 0

---

## Context

UnoArena requires an asynchronous event delivery backbone for all cross-context communication. The broker must:

- **Fan out** a single event (e.g., `GameCompleted`) to multiple independent consumer groups (Ranking, Spectator View, Tournament Orchestration, Analytics) without any consumer blocking another.
- **Preserve per-game ordering.** Events for the same `game_id` must be delivered in commit order to all consumers. This is required for spectator accuracy and tournament match-state consistency.
- **Absorb the 100K `GameCompleted` burst** at tournament round end without becoming a bottleneck. Analytics must be able to lag behind without blocking Ranking or Spectator consumers.
- **Guarantee at-least-once delivery** with idempotent consumers (not exactly-once at the broker level).
- **Scale to ~30,000–50,000 events/second** at peak (100K rooms × 2–3 commands/min × 10 players, amplified by multi-event commands).
- Support **partitioning by `game_id`** so that per-game ordering is preserved and consumer scaling is partition-based.
- Support the **transactional outbox** relay pattern: the broker must accept idempotent producer writes (at-least-once with no duplicates on the Kafka side).

---

## Options Considered

### Option A — RabbitMQ (AMQP)

A mature message broker with queues, exchanges, and routing keys.

**Strengths:** Simple to operate at moderate scale; good client library support; low latency for point-to-point delivery.

**Weaknesses:**
- **No fan-out to independent consumer groups with per-group lag isolation.** RabbitMQ queues are consumed by competing consumers — each message is delivered to exactly one consumer. Separate queues per consumer (Ranking queue, Spectator queue, etc.) require the producer to publish to each queue independently. This is a manual fan-out, not native broker fan-out.
- **Message retention is not native.** Once a consumer ACKs a message, it is gone. Replaying from a position (e.g., reconnecting a failed Analytics consumer and catching up) requires external dead-letter management.
- **No native partition-based ordering.** Message ordering per routing key is provided only if there is a single consumer on that queue; with competing consumers, ordering is not guaranteed.
- **Throughput ceiling.** At 50K messages/second sustained, RabbitMQ requires significant tuning and clustering; it is not designed for this throughput out of the box.

**Verdict:** Rejected. Fan-out semantics, partition-based ordering, and replay capability are all gaps that require workarounds.

---

### Option B — Redis Streams (per-topic Streams)

Redis Streams (`XADD`/`XREADGROUP`) provide an ordered, consumer-group-based log.

**Strengths:** Already required for the spectator fan-out path (see ADR-008); no new infrastructure for some use cases. Low latency.

**Weaknesses:**
- **Memory-bounded.** Redis is an in-memory data structure store. At 50K events/second × 1KB average payload, the streams would consume 50MB/s continuously. Without aggressive MAXLEN trimming, streams grow unboundedly; with aggressive trimming, slow consumers (Analytics catching up after a restart) lose events.
- **No partitioned consumption across multiple instances.** Redis Streams consumer groups assign pending entries to consumers within the group, but there is no partition key routing equivalent to Kafka's partitioner. Per-game ordering requires manual stream-per-game routing, resulting in up to 100K streams at peak — impractical for Redis keyspace management.
- **Not designed as a durable log.** Redis persistence (RDB + AOF) adds disk I/O but is not a substitute for Kafka's log storage. Event replay after a node failure requires careful AOF configuration and does not match Kafka's segment-based retention.

**Verdict:** Rejected as the primary broker. Redis Streams are retained for the spectator fan-out path (within-service, bounded per game, short TTL) but are not suitable as the cross-context event backbone.

---

### Option C — Apache Kafka (selected)

A distributed, partitioned, replicated commit log. Industry standard for high-throughput event streaming.

**Strengths:**
- **Native fan-out via consumer groups.** Each consumer context (Ranking, Spectator View, Tournament Orchestration, Analytics) maintains its own consumer group. All groups read from the same topic; they advance their offsets independently. One consumer group lagging does not affect any other.
- **Partition-based ordering.** Events partitioned by `game_id` (using `game_id` as the partition key) are delivered in commit order to any consumer. With 100+ partitions on the `game-events` topic, consumer groups can scale horizontally up to the partition count.
- **Durable log with configurable retention.** Events are stored on disk (Kafka segment files) with configurable retention (e.g., 7 days for `game-events`). A slow consumer (Analytics restarting after a failure) replays from its last committed offset without any data loss.
- **Idempotent producer.** `enable.idempotence=true` on the Kafka producer guarantees exactly-once writes to Kafka from the outbox relay, preventing duplicate events on relay retry.
- **Throughput.** Kafka is proven at millions of messages/second per cluster. 50K messages/second is well within a modest 3-broker cluster capacity.
- **`tournament-kickoff` topic.** A dedicated topic with 100+ partitions allows the round-kickoff fan-out to distribute 100K room assignments across N Room Gameplay consumer workers naturally, with backpressure via consumer lag.

**Weaknesses:**
- **Operational complexity.** Kafka requires a ZooKeeper ensemble (or KRaft mode in Kafka 3.x). This is additional infrastructure to operate compared to RabbitMQ or Redis-only.
- **Latency.** Kafka's default end-to-end latency is 1–10ms (producer → consumer). This is acceptable for cross-context event delivery (the latency-sensitive path — game command response to the active player — bypasses Kafka entirely via the synchronous HTTP response).

**Verdict:** Selected.

---

## Decision

**Use Apache Kafka (KRaft mode, Kafka 3.x+) as the cross-context message broker for all domain event delivery.**

### Topic topology (O9 resolution)

One topic per producing context:

| Topic | Producers | Primary consumers | Partition key | Partitions |
|---|---|---|---|---|
| `game-events` | room-gameplay-service outbox relay | tournament-service, spectator-service, ranking-service, analytics-service | `game_id` | 100+ |
| `tournament-events` | tournament-service outbox relay | ranking-service, spectator-service, analytics-service | `tournament_id` | 20+ |
| `identity-events` | identity-service outbox relay | room-gameplay-service, moderation-service | `player_id` | 20+ |
| `moderation-events` | moderation-service outbox relay | ranking-service, spectator-service | `game_id` or `player_id` | 10+ |
| `ranking-events` | ranking-service outbox relay | spectator-service (leaderboard), analytics-service | `player_id` | 20+ |
| `tournament-kickoff` | tournament-service kickoff relay | room-gameplay-service (`tournament-kickoff-consumer-worker`) | `room_id` | 100+ |

Event type is carried as a Kafka message header (`event-type: GameCompleted`), not encoded in the partition key. Consumers filter by header. This approach reduces topic count (no proliferation of one-topic-per-event-type) while preserving consumer group isolation between contexts.

---

## Rationale

1. **Consumer group independence is load-critical.** The 100K `GameCompleted` burst at round end must not cause the Analytics consumer (processing 100K ClickHouse writes) to create backpressure on Ranking (which must update Elo promptly) or Spectator View. Kafka consumer groups are the correct primitive for this isolation.

2. **Partition-based ordering is correctness-critical.** Spectator View must receive events for a given game in commit order. Kafka's partition ordering guarantee, combined with per-game partitioning, provides this without any application-level sequencing logic.

3. **Durable replay protects against Analytics outages.** Analytics may restart after an outage (e.g., ClickHouse maintenance window) and replay missed events from Kafka without data loss. RabbitMQ cannot provide this without external dead-letter stores.

4. **Idempotent producer closes the outbox relay window.** The transactional outbox relay retries Kafka publishes until ACK. Without idempotent producer mode, retries would produce duplicates. With `enable.idempotence=true`, the broker deduplicates retries within the producer session window (5 minutes by default).

---

## Consequences

- **Kafka cluster required.** Minimum 3-broker cluster in KRaft mode. Production: 5 brokers for the `game-events` topic (100 partitions × replication factor 3 = 300 partition replicas; 60 per broker).
- **`game-events` topic must not use `cleanup.policy=compact`.** The game log is an event stream, not a KV store; compaction would lose events for the same `game_id`. Use `delete` policy with a 7-day retention.
- **Consumer groups must commit offsets after processing**, not before. Pre-commit offsets lose events on consumer crash; post-commit ensures at-least-once delivery with idempotent consumer logic.
- **Schema evolution:** Event payloads carry a `schema_version` field. Consumers must tolerate unknown fields (forward compatibility). Breaking changes require a new event type rather than modifying the existing one.
