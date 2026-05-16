# UnoArena — Architecture Documentation

This directory contains the complete microservices architecture for UnoArena, derived from the DDD design in `/design`. Every decision here is traceable to a bounded context, command, or event from that design.

---

## Document Index

| Document | Purpose |
|---|---|
| [PLAN.md](./PLAN.md) | Working plan: open decisions, resolved decisions, phase schedule |
| [CONTEXT_VIEW.md](./CONTEXT_VIEW.md) | Bounded context → service mapping; updated context map |
| [CONTAINER_VIEW.md](./CONTAINER_VIEW.md) | All deployable containers and trust boundaries |
| [INTEGRATION_VIEW.md](./INTEGRATION_VIEW.md) | Sync/async patterns; full integration table; client connection model |
| [PERSISTENCE.md](./PERSISTENCE.md) | Per-context data stores, consistency model, read paths, audit |
| [CAPACITY_SKETCH.md](./CAPACITY_SKETCH.md) | Load estimates, scaling decisions, spectator multiplier |
| **services/** | Per-service specification files (one per bounded context) |
| **adr/** | Architecture Decision Records (ADR-001 through ADR-008) |

---

## Services

| File | Context | Primary Responsibility |
|---|---|---|
| [services/room-gameplay.md](./services/room-gameplay.md) | Room Gameplay | Game state, log-before-broadcast, timers, outbox relay |
| [services/tournament.md](./services/tournament.md) | Tournament Orchestration | Tournament/round lifecycle, Bo3 match tracking, round-kickoff surge |
| [services/identity.md](./services/identity.md) | Identity / Session | Player profiles, JWT issuance, single-active-session, push invalidation |
| [services/ranking.md](./services/ranking.md) | Ranking | Elo computation, leaderboard, reversal on void |
| [services/spectator.md](./services/spectator.md) | Spectator View | Privacy-filtered live game projections, WebSocket fan-out |
| [services/analytics.md](./services/analytics.md) | Analytics / Read Models | Player stats, bracket views, standings, burst absorption |
| [services/moderation.md](./services/moderation.md) | Moderation / Admin | Audit log, corrective commands, abuse escalation, rate-limiting map |

---

## Architecture Decision Records

| ADR | Decision |
|---|---|
| [ADR-001](./adr/ADR-001-client-protocol.md) | Client realtime protocol (WebSocket) |
| [ADR-002](./adr/ADR-002-message-broker.md) | Message broker (Kafka) |
| [ADR-003](./adr/ADR-003-log-before-broadcast.md) | Log-before-broadcast mechanism (transactional outbox) |
| [ADR-004](./adr/ADR-004-timer-durability.md) | Timer durability (Redis keyspace notifications) |
| [ADR-005](./adr/ADR-005-session-invalidation-push.md) | Session invalidation push channel |
| [ADR-006](./adr/ADR-006-tournament-surge.md) | Tournament round-kickoff surge fan-out |
| [ADR-007](./adr/ADR-007-gateway-bff.md) | Gateway vs BFF (single API Gateway) |
| [ADR-008](./adr/ADR-008-spectator-scaling.md) | Spectator WebSocket fan-out |

---

## System Summary

UnoArena is a real-time multiplayer Uno platform supporting casual rooms (2–10 players) and elimination tournaments of up to 1,000,000 players. The first tournament round generates up to 100,000 simultaneous matches — the dominant scaling challenge driving most architectural choices.

**Seven bounded contexts** each map to one deployable service. A single **API Gateway** fronts all traffic, terminating both REST and WebSocket connections. **Kafka** is the async backbone for all cross-context event delivery. **Redis** provides fast shared state (timers, caches, leaderboards, pub/sub). **PostgreSQL** is the primary durable store for all write-side aggregates.

Key architectural invariants:

- **Log-before-broadcast**: every game state change is written to PostgreSQL (aggregate row + event log + outbox) in a single transaction before being relayed to Kafka and broadcast to clients.
- **Single-active-session**: the API Gateway subscribes to Redis Pub/Sub and closes old WebSocket connections immediately on session invalidation.
- **Per-game serialization**: commands for the same `game_id` are serialized via PostgreSQL row-level locks — no distributed coordination needed.
- **Surge isolation**: the `GameCompleted` spike at round end is absorbed by dedicated Analytics consumer groups that are independent of Room Gameplay writers.
- **Privacy enforcement**: Spectator View applies a strict whitelist filter at event consumption — the read model never contains hand data.
