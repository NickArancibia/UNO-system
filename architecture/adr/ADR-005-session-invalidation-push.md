# ADR-005 — Session Invalidation Push Path

**Status:** Accepted  
**Context:** Identity / Session service → API Gateway  
**Decided:** Phase 2

---

## Context

When a player logs in from a new device (or is suspended/banned), the `valid_sessions_from` timestamp is updated in PostgreSQL and the old JWT is immediately invalid for any **new** request. The API Gateway verifies JWTs against this record on every authenticated request — so any new command from the old device is rejected and the old connection is dropped then.

However, the old device's existing WebSocket connection is already authenticated. It holds no pending requests. The Gateway will not re-check the JWT until the old device submits its next command. If the player is in a game, the old connection can continue to receive events and submit commands indefinitely until:
- It submits a command (gateway revalidates → rejected → disconnect), or
- The connection drops naturally.

For the **single-active-session invariant** to hold at the connection level — not just the command level — the system must actively terminate the old WebSocket connection promptly. This requires a signal from Identity/Session to the specific gateway node(s) holding the old connection.

This ADR records why Redis Pub/Sub was chosen over the two alternatives.

---

## Options Considered

### Option A — Redis Pub/Sub (selected)

Identity/Session publishes `PUBLISH session:invalidated:<player_id> <invalidated_at_timestamp>` after the DB commit. Every api-gateway instance subscribes to `PSUBSCRIBE session:invalidated:*`. On receipt, each node closes any WebSocket connections it holds for `<player_id>` whose JWT `issued_at` is older than `<invalidated_at_timestamp>`.

**Latency:** Sub-millisecond from publish to gateway receipt (Redis in-process pub/sub).  
**Delivery:** Fire-and-forget (at-most-once). If Redis restarts or the message is missed, the old connection persists until it submits a command.  
**Fan-out:** Redis handles fan-out to all subscribed gateway instances natively — no consumer groups, no partition assignment, no rebalancing.  
**Infrastructure:** Redis is already in the stack for `valid_sessions_from` caching. No new component required.

---

### Option B — Kafka consumer group (broadcast)

Identity/Session emits `SessionInvalidated` on the `identity-events` Kafka topic (which already exists for downstream consumers such as Room Gameplay). Every api-gateway instance subscribes to this topic under a consumer group configured in **broadcast mode** (each instance in its own consumer group, or each instance reading all partitions).

**Latency:** ~50–300ms (Kafka end-to-end latency including consumer poll interval).  
**Delivery:** At-least-once. Durable — the event is retained in Kafka even if a gateway instance is down at publish time.  
**Fan-out:** More complex. Requires either (a) each gateway instance in its own consumer group (one consumer group per running instance — scales poorly), or (b) a shared group where only one instance receives each event (misses the rest).  
**Infrastructure:** Reuses existing Kafka broker.

**Problem:** For a live WebSocket that may be submitting commands every second (during active gameplay), the 50–300ms latency is immaterial — the session is already invalid and the next command will be rejected. But the consumer group topology is operationally awkward: gateway instances are ephemeral and autoscale, so per-instance consumer groups accumulate stale groups and require active cleanup.

---

### Option C — Internal gRPC/HTTP call from Identity/Session to the gateway

Identity/Session maintains a registry of which gateway node holds each player's WebSocket connection (stored in Redis as `gateway:connection:<player_id> → <gateway_node_id>`). On session invalidation, it calls that specific gateway node directly via gRPC or HTTP to close the connection.

**Latency:** Sub-millisecond (direct call).  
**Delivery:** Synchronous — confirmation received.  
**Infrastructure:** Requires a connection registry (Redis keys) and a service discovery mechanism (Identity/Session must know the network address of each gateway node).

**Problem:** This creates tight coupling between Identity/Session and the internal address space of the Gateway tier. Gateway instances are stateless and ephemeral; their addresses change on scale events and restarts. Maintaining an accurate connection registry under concurrent new connections, reconnections, and WS drops is complex and failure-prone. If the registry is stale, the call fails silently.

---

## Decision

**Use Redis Pub/Sub.**

---

## Rationale

The fire-and-forget delivery model is acceptable for this use case because the DB is the authoritative source of truth for JWT validity. Redis Pub/Sub is only the **fast-path** — it minimizes the window in which the old connection can still submit game commands. The fallback is not a security hole: the gateway will catch the stale JWT on the next command and disconnect then.

The specific reasons for preferring Pub/Sub over Kafka:

1. **Latency is order-of-magnitude better.** The 5-second Uno! challenge window requires real-time responsiveness. A stale connection submitting a `ChallengeUno` 200ms after the window closed due to session invalidation could cause an incorrect game state if not caught by the per-game state version check. The state version check IS the correctness fence; the session invalidation push is a defense-in-depth measure to eliminate the ambiguity window.

2. **Fan-out is simpler.** Redis Pub/Sub naturally delivers to all subscribers simultaneously. With Kafka, achieving true broadcast requires one consumer group per gateway instance — operationally messy for an autoscaling fleet.

3. **No new infrastructure.** Redis is already deployed for `valid_sessions_from` caching, timer TTLs, rate limiting, and leaderboards. Adding a Pub/Sub channel requires no new components.

4. **Option C rejected on coupling grounds.** A connection registry creates bidirectional coupling between Identity/Session and Gateway internals, violating the context boundary established in `CONTEXT_VIEW.md`.

---

## Consequences

- **Message loss is possible but acceptable.** If a gateway instance misses the Pub/Sub message (e.g., Redis restart), it will disconnect the old session on the next command (JWT validation). The maximum exposure window is bounded by how quickly the old device submits a command.

- **Gateway must maintain an in-memory connection registry** keyed by `player_id` → `[]WebSocket`, so that on Pub/Sub receipt, it can efficiently find all connections for a given player. This registry is per-instance and in-memory only — it is not persisted or shared.

- **Redis Pub/Sub channel never carries sensitive data.** The published value is `<invalidated_at_timestamp>` — a timestamp. No JWT content or credentials are transmitted.

- **eviction policy:** The Pub/Sub channel is fire-and-forget. No TTL, no storage. This is distinct from the leaderboard and timer Redis databases that use `noeviction` policy.

- **Monitoring.** The number of Pub/Sub subscribers on `session:invalidated:*` should equal the number of running gateway instances. An alert on subscriber count ≠ expected gateway replicas indicates a gateway instance lost its Redis subscription.
