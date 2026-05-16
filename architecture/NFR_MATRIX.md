# UnoArena — Non-Functional Requirements Matrix

This document defines the latency budgets, throughput targets, availability targets, and recovery objectives for every major service and cross-cutting flow. All figures are at **peak load** (first tournament round: 100K concurrent matches, 1M active players).

---

## 1. Latency Budgets

### 1.1 Active Player Game Command (End-to-End P99)

The hot path: Player sends `PlayCard` → receives acknowledgment with updated state.

| Step | Budget | Notes |
|---|---|---|
| Client → API Gateway (TLS + WebSocket frame parse) | 5ms | Local network + crypto overhead |
| Gateway JWT validation (Redis cache hit) | 2ms | Redis RTT ~1ms; cache-aside miss adds ~10ms (rare) |
| Gateway → room-gameplay-service (HTTP POST, mTLS) | 3ms | Intra-cluster |
| room-gameplay-service: row lock acquisition | 10ms | Contention if game is hot; target P50 < 2ms, P99 < 10ms |
| room-gameplay-service: command validation + DB write (PostgreSQL, local) | 15ms | Includes `game_sessions` update + `game_events` + `outbox` in one transaction |
| room-gameplay-service → Gateway (HTTP response) | 3ms | |
| Gateway → Client (WebSocket frame push) | 5ms | |
| **Total (hot path, P99)** | **~43ms** | Target: < 100ms P99 |

**Target:** P50 < 30ms, P99 < 100ms, P999 < 300ms for the full round-trip.

### 1.2 Session Invalidation Push (Old Connection Close)

| Step | Budget | Notes |
|---|---|---|
| Identity/Session: DB commit + Redis PUBLISH | 5ms | |
| Redis Pub/Sub delivery to all gateway instances | 1ms | Sub-ms under normal Redis load |
| Gateway: registry scan + WebSocket close frame | 1ms | O(1) hash lookup by `player_id` |
| **Total** | **~7ms** | Target: < 50ms for old connection to be terminated |

### 1.3 Challenge Window Event Delivery (Spectator Path)

The 5-second challenge window requires spectators to see `ChallengeWindowOpened` quickly enough to understand the state.

| Step | Budget | Notes |
|---|---|---|
| room-gameplay-service commit + outbox relay → Kafka | 10ms | Outbox relay reads and publishes; Kafka ACK |
| Kafka → spectator-game-consumer-worker (consumer poll) | 10ms | Kafka default poll interval 500ms is too slow; configure `max.poll.interval.ms = 50ms` for spectator consumer |
| consumer-worker: filter + XADD to Redis Stream | 2ms | |
| Redis Stream → spectator WebSocket (XREAD BLOCK wakes) | 1ms | |
| **Total** | **~23ms** | Spectators see the challenge window event within ~25ms of the player playing the card; well within the 5-second window |

### 1.4 Elo Update After Game Completion (Eventual)

| Step | Target | Notes |
|---|---|---|
| `GameCompleted` → Kafka | < 100ms | Outbox relay |
| Kafka → ranking-service | < 2s (P99) | Consumer lag under normal load |
| Ranking: Elo computation + DB write + `EloUpdated` event | < 500ms | Row lock per player (not hot under casual load) |
| `EloUpdated` → Redis leaderboard | < 100ms | Outbox relay + consumer |
| **Leaderboard visible to players** | **< 5s (P99)** | Acceptable for rankings (eventual consistency) |

---

## 2. Throughput Targets

### 2.1 Game Commands

| Metric | Target | Basis |
|---|---|---|
| Peak commands/second (Room Gameplay ingest) | 50,000 cmd/s | 100K rooms × 10 players × 3 cmd/min/player ÷ 60s, with 2× headroom |
| PostgreSQL writes/second (Room Gameplay) | 150,000 rows/s | ~3 rows per command (state + events + outbox) |
| Kafka events/second (`game-events` topic) | 200,000 events/s | Multi-event commands (PlayCard → up to 5 events) × 50K cmd/s |
| `GameCompleted` burst (round end) | 100,000 events in ≤ 60s | ~1,667 events/s sustained for 60s; well within Kafka capacity |

### 2.2 WebSocket Connections

| Component | Peak connection count | Notes |
|---|---|---|
| API Gateway (active players) | 1,000,000 | 1 connection per active player |
| API Gateway (spectators) | up to 10,000,000 | 10:1 spectator ratio; likely regional edge required above 5M |
| room-gameplay-service (HTTP connections from gateway) | Stateless HTTP; connection pool of ~1,000 per service pod | HTTP/2 multiplexing reduces connection count |

### 2.3 Analytics Write Throughput

| Metric | Target |
|---|---|
| ClickHouse batch inserts (steady state) | 10,000 rows/s (batch every 500ms) |
| ClickHouse burst (round end, 100K events/60s) | 100,000 rows in 60s ≈ 1,667 rows/s; well within ClickHouse capacity (100K+ rows/s rated) |

---

## 3. Availability Targets

| Service | Target SLA | Justification |
|---|---|---|
| API Gateway | 99.95% | Single entry point; gateway downtime = full outage |
| room-gameplay-service | 99.9% | Per-game failures are isolated; game state recoverable from PostgreSQL |
| identity-service | 99.9% | Login unavailability blocks new connections; cached `vsf` values protect existing sessions |
| tournament-service | 99.5% | Tournament management is lower frequency; round kickoff is a coordinated batch operation |
| ranking-service | 99.5% | Elo updates are eventual; brief unavailability causes consumer lag, not data loss |
| spectator-service | 99.9% | Spectator disconnections are non-critical for game integrity |
| analytics-service | 99.0% | Analytics lag is acceptable; no player-visible impact |
| moderation-service | 99.5% | Admin operations; human retry is acceptable |
| Kafka cluster | 99.95% | Backbone for all async delivery; 3-broker cluster with replication factor 3 |
| Redis (per instance) | 99.9% | Timer, cache, and leaderboard data. Sentinel-managed pairs per instance. |
| PostgreSQL (per service) | 99.95% | Primary write store per context. Managed with streaming replication + automated failover. |

### 3.1 Recovery Objectives

| Tier | RTO | RPO | Notes |
|---|---|---|---|
| API Gateway pod failure | < 30s | 0 (stateless) | Load balancer health check removes pod within 15s; new pod starts within 15s |
| room-gameplay-service pod failure | < 60s | 0 (state in PostgreSQL) | Active games continue after pod replacement; Redis timers continue firing |
| Redis timer instance failure | < 120s | < 10s (AOF) | Timer keys restored from AOF; reconciliation sweeps cover the gap |
| Kafka broker failure (1 of 3) | < 30s | 0 (replicated) | Partition leader re-election; at-least-once delivery continues |
| PostgreSQL primary failure | < 60s | < 1s (streaming replication) | Automated failover via pgBouncer + repmgr or managed DB failover |

---

## 4. Scalability Model

### 4.1 Stateless Horizontal Scale

The following services scale by adding pods with no state coordination:

- **API Gateway** — connection registry is per-pod; Redis Pub/Sub fan-out covers all pods for session invalidation.
- **room-gameplay-service** — stateless HTTP; PostgreSQL row-locking serializes per-game commands; any pod can process any game command.
- **ranking-service** — stateless consumer; PostgreSQL row-locking serializes per-player Elo updates.
- **spectator-service** — stateless consumer + WebSocket relay; Redis Streams allow any pod to serve any game stream.
- **analytics-service** — stateless consumer; ClickHouse scales independently.

### 4.2 Partitioned (Kafka-bounded) Scale

| Service | Scaling bound | Current target |
|---|---|---|
| room-gameplay-service (tournament-kickoff consumer) | ≤ `tournament-kickoff` partition count | 100 partitions → 100 pods maximum |
| spectator-game-consumer-worker | ≤ `game-events` partition count | 100 partitions → 100 consumer pods |
| analytics-game-worker | ≤ `game-events` partition count | 100 partitions; running 20 pods × 5 partitions |
| ranking-service | ≤ `game-events` partition count | 10 pods sufficient at expected Elo update rate |

### 4.3 Intentionally Singleton or Lightly Scaled

| Component | Why not fully scaled out |
|---|---|
| identity-service outbox relay | Single relay thread per pod; single pod is sufficient (low write volume: ~1K logins/s) |
| moderation-service | Admin operations are low frequency; 2–3 pods sufficient |
| tournament-service orchestration worker | Bo3 state updates are serialized per `match_id`; scale to ≤ Kafka partition count for `game-events` |

---

## 5. Latency Budget for the 5-Second Challenge Window

This window is the tightest time constraint in the system. The full path from `PlayCard` decision to challenge window expiry enforces:

| Event | Deadline from card play |
|---|---|
| `UnoCallMissed` (player didn't call Uno!) detected | Immediate (during PlayCard command processing) |
| `ChallengeWindowOpened` committed to `game_events` | < 50ms |
| `ChallengeWindowOpened` delivered to active players (WebSocket) | < 100ms |
| `ChallengeWindowOpened` delivered to spectators | < 250ms |
| Challenge window timer set in Redis | < 50ms (SET within same request handler after DB commit) |
| `ChallengeWindowExpired` fires (Redis keyspace notification) | T + 5,000ms ± 10ms |
| `ChallengeWindowExpired` processed by timer worker | T + 5,000ms + 50ms max |

**Conclusion:** The end-to-end budget is comfortably within the 5-second window. Spectators see the window open within 250ms and closed within 5.1 seconds. The 2-second reconciliation sweep catches any missed expiry notifications before the next turn event would conflict.
