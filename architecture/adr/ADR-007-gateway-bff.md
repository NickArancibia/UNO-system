# ADR-007 — API Gateway vs. Game BFF

**Status:** Accepted  
**Context:** Client connection termination; WebSocket lifecycle; session invalidation push path  
**Decided:** Phase 0 (O1)

---

## Context

UnoArena serves three distinct client audiences:

1. **Active players** — bidirectional WebSocket for game commands and event pushes. Requires sub-second latency, session-invalidation push, per-room ordered event delivery, and reconnection snapshot delivery.
2. **Spectators** — WebSocket for read-only game event stream. Privacy-filtered; may exceed 10M concurrent connections at peak.
3. **REST clients** — registration, login, tournament management, analytics queries, admin actions. Standard HTTPS request/response.

The question is whether to deploy:
- **Option A:** A single API Gateway that handles all three client types.
- **Option B:** A dedicated Game BFF (Backend for Frontend) for active players + spectators, sitting alongside a REST API Gateway.

---

## Options Considered

### Option A — Dedicated Game BFF + REST Gateway

A **Game BFF** owns all WebSocket connections (active players and spectators). The BFF handles per-room WebSocket ordering, session-invalidation push, and reconnection snapshots. A separate **REST Gateway** handles registration, login, tournament management, and admin.

**Strengths:**
- Clear separation of concerns: long-lived stateful connections vs. stateless HTTP.
- The BFF can be optimized exclusively for WebSocket fan-out (e.g., different connection limits, different TLS termination config).
- REST Gateway can be scaled independently (e.g., spike during tournament registration vs. gameplay peak).

**Weaknesses:**
- **Two components to operate and maintain.** Separate deployments, separate routing rules, separate TLS certificate management, separate observability pipelines.
- **Duplicated cross-cutting concerns.** JWT validation, rate limiting, and session-invalidation pub/sub subscription must be implemented in both components.
- **Login flow complexity.** A player who logs in via the REST Gateway and then connects via the Game BFF must have their session state available to both. This is already handled by the Redis `valid_sessions_from` cache, so it is not a correctness issue — but it adds a mental model overhead for operators.
- **Tournament kickoff path.** When a tournament round starts, the BFF must receive connection notifications from identity-events to know which player is on which BFF instance. This is already needed in the single-gateway model — adding a BFF does not simplify it.

**Verdict:** Not selected. The operational overhead of two gateway components is not justified by the separation-of-concerns benefit, given that the cross-cutting concerns (JWT, rate limiting, session invalidation) are already implemented as Redis-based policies applicable to both connection types.

---

### Option B — Single API Gateway (selected)

One API Gateway handles all three client types:
- WebSocket connections for active players (routed to room-gameplay-service via HTTP POST per frame).
- WebSocket connections for spectators (routed to spectator-service).
- HTTPS requests for REST operations.

The gateway maintains a single in-memory registry of `player_id → WebSocket` for all active connections (both player and spectator roles).

**Strengths:**
- **One component.** Single deployment, single TLS termination, single JWT validation path, single rate-limiting Redis instance, single `PSUBSCRIBE session:invalidated:*` subscription.
- **Unified session-invalidation push path.** All WebSocket connections (player or spectator) are in one registry. On `SessionInvalidated`, the gateway scans the unified registry and closes all stale connections — both gameplay and spectator connections for the same `player_id`.
- **Simpler horizontal scaling.** Each gateway pod is identical; load balancer distributes connections across pods. No need to route login traffic to one component and WebSocket traffic to another.
- **Consistent observability.** All client connections are logged, metered, and traced by the same gateway pod. Correlation between a REST login and a subsequent WebSocket command is trivially available in the same log stream.

**Weaknesses:**
- **Heterogeneous connection types on one component.** WebSocket connection state (in-memory registry) and stateless HTTP routing coexist in the same process. This is well-supported by modern reverse proxies (Envoy, nginx) and application frameworks with WebSocket support.
- **Spectator scale pressure.** At 10M concurrent spectator connections, the single gateway tier is the largest scaling challenge. However, this is a connection-level problem that applies equally to a dedicated spectator BFF — adding a separate component does not reduce the total number of connections.

**Verdict:** Selected.

---

## Decision

**Deploy a single API Gateway** that terminates all client connections (active player WebSocket, spectator WebSocket, REST HTTPS). No separate Game BFF.

### Gateway responsibilities

| Responsibility | Mechanism |
|---|---|
| TLS termination | TLS at the load balancer or gateway pod |
| JWT validation | Local signature verification + Redis `identity:vsf:<player_id>` cache-aside |
| Per-IP rate limiting | Redis `ratelimit:ip:<ip>:<bucket>` fixed-window |
| Per-user rate limiting | Redis `ratelimit:user:<player_id>` sliding-window ZSET |
| WebSocket upgrade for active players | Upgrade on `wss://.../v1/games/{game_id}/connect`; forward frames as HTTP POST to room-gameplay-service |
| WebSocket upgrade for spectators | Upgrade on `wss://.../v1/spectator/games/{game_id}`; subscribe to `spectator:stream:{game_id}` Redis Stream |
| Session-invalidation push | `PSUBSCRIBE session:invalidated:*`; on receipt, close stale WebSocket connections |
| Reconnect snapshot delivery | Receives `POST /internal/push/{player_id}` from room-gameplay-service; looks up WebSocket in registry; delivers snapshot |
| Routing REST requests | Proxies to identity-service, tournament-service, ranking-service, moderation-service, analytics-service |

### Per-room ordering guarantee

All game events for a given `game_id` are produced to the `game-events` Kafka topic partitioned by `game_id`. The active player's connection receives events via the synchronous command response (not via Kafka), so ordering is preserved by the request/response cycle. The gateway pushes events in the order it receives them from room-gameplay-service; within the synchronous path, no reordering is possible.

---

## Rationale

1. **Operational simplicity at the stated scale.** UnoArena's scale (1M concurrent players, 10M spectators) is challenging at the connection tier regardless of decomposition. A single gateway component is easier to operate, monitor, and scale horizontally than two separately deployed components with duplicated cross-cutting logic.

2. **Session-invalidation push is simpler with a unified registry.** The `PSUBSCRIBE session:invalidated:*` subscription and the in-memory `player_id → WebSocket` registry are both present on every gateway pod. There is no need to route the Pub/Sub event to a specific pod based on which component holds the connection — every pod simply closes the matching connection if it holds one, and ignores the event otherwise.

3. **Rate limiting and JWT validation apply uniformly.** A single gateway enforces per-IP and per-user rate limits consistently across REST and WebSocket traffic. A BFF + REST gateway split would require coordinating shared rate-limit counters in Redis between two separate deployable components — which is what we already do, but now across two different codebases.

---

## Consequences

- **Gateway pods must support WebSocket + HTTP simultaneously.** Modern frameworks (e.g., nginx with upstream WebSocket proxying, Envoy with WebSocket extension) support this natively.
- **Spectator connection scaling.** If 10M spectator connections exceed the capacity of the gateway tier, a regional edge layer (e.g., Cloudflare Workers) may be introduced in front of the gateway. This does not change the gateway's design — it changes the load balancer layer above it.
- **Connection registry is in-memory per pod.** A gateway pod crash causes all connections on that pod to drop. Clients reconnect via the standard reconnect path. No connection state is lost from the system's perspective (game state is in PostgreSQL; spectator stream is in Redis Streams).
- **No sticky sessions required for correctness.** The Redis-based session-invalidation fan-out and the `POST /internal/push/{player_id}` push endpoint mean the gateway does not need to route commands or events to a specific pod. Any pod can receive any command and look up the push target in the in-memory registry (no-op if the connection is on another pod).
