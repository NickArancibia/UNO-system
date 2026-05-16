# UnoArena — Capacity Sketch

Order-of-magnitude reasoning for peak load at first-round tournament surge (the highest-throughput event in the system). All numbers are upper-bound estimates for infrastructure sizing, not guaranteed SLAs.

---

## 1. Peak Concurrent Matches

**First-round surge:** 1,000,000 confirmed players → 100,000 rooms (max 10 players each). At round start, all 100,000 rooms transition to `in_progress` within seconds.

**Sustained gameplay (after surge):**
- Average game duration: ~3–5 minutes per casual game, ~10–15 minutes per tournament Bo3 match.
- At any point during active play: up to 100,000 concurrent games in round 1, declining as players are eliminated.
- By round 3 (< 1,000 rooms), concurrent games are ~1,000.

For sizing, plan for **100,000 concurrent games** as the design ceiling.

---

## 2. Concurrent Players and Spectators

| Metric | Estimate | Rationale |
|---|---|---|
| Active players at surge | 1,000,000 | All confirmed players in games simultaneously |
| WebSocket connections (players) | 1,000,000 | One WS per active player |
| Spectator ratio | 10:1 (spectators per active player) | Plausible for a global tournament with bracket viewership |
| Spectator WebSocket connections | 10,000,000 | At 10:1 ratio at surge peak |
| Total concurrent WebSocket connections | ~11,000,000 | Players + spectators combined |
| Sustained concurrent connections (post-surge) | ~500,000–2,000,000 | Declining as rounds advance; casual play ongoing |

**Gateway sizing:** A single API Gateway instance handles ~50K–100K concurrent WebSocket connections. At surge peak: 110 gateway instances. Sustained: 5–20 instances. Use horizontal auto-scaling with connection count as the scaling metric.

---

## 3. Event and Command Rates

### 3.1 Game commands (room-gameplay-service)

| Metric | Estimate | Rationale |
|---|---|---|
| Commands per game per second (active play) | 2–5 | PlayCard, DrawCard, CallUno, ChallengeUno; a turn takes ~5–15s with 1–3 commands per turn |
| Peak command rate | 100,000 × 3 ≈ 300K commands/s | All games active simultaneously (upper bound) |
| Realistic sustained rate | 100,000 × 1 ≈ 100K commands/s | Average 1 command/s per game after initial burst |

Each command = one PostgreSQL row lock acquisition + transaction commit + Redis idempotency check + Redis timer set/reset. The PostgreSQL write path is the bottleneck (see §5).

### 3.2 Kafka event rates

| Topic | Peak rate | Sustained rate | Partition count |
|---|---|---|---|
| `game-events` | ~300K events/s | ~100K events/s | 100 (by `game_id`) |
| `tournament-events` | ~1K events/s (surge) | ~100 events/s | 10 (by `tournament_id`) |
| `tournament-kickoff` | 1K events/s (burst over ~100s) | N/A (burst only) | ≥100 (by `room_id`) |
| `identity-events` | ~5K events/s (login surge) | ~500 events/s | 10 (by `player_id`) |
| `ranking-events` | ~100K events/s (round-end burst) | ~10K events/s | 20 (by `player_id`) |

**Kafka broker sizing:** A 3-node Kafka cluster sustains ~300K messages/s per broker with standard hardware. At peak (`game-events` + `ranking-events` + `identity-events` running concurrently), total throughput is ~400K messages/s. A 5-broker cluster provides comfortable headroom (1.5M messages/s aggregate). Partition assignment: `game-events` gets 100 partitions (the dominant topic); others get 10–20 partitions each.

---

## 4. Component Scalability Profile

| Component | Horizontal? | Bottleneck | Sizing at 100K games |
|---|---|---|---|
| **API Gateway** | Yes (stateless per-request; in-memory WS registry per instance) | WebSocket connection count | 110 instances at surge; 5–20 sustained |
| **room-gameplay-service** | Yes (per-game row-lock serialization) | PostgreSQL write TPS | 50–100 pods × 2–5 partitions each (see §5) |
| **tournament-service** | Yes (per-match row-lock) | PostgreSQL write TPS | 5–10 pods (far fewer concurrent operations) |
| **identity-service** | Yes (per-player row-lock) | PostgreSQL read/write TPS | 5–10 pods (login surge is brief) |
| **spectator-service** | Yes (no sticky routing; reads from shared Redis Streams) | Redis Streams XREAD throughput | 50–100 pods at peak; 5–10 sustained |
| **ranking-service** | Yes (Kafka consumer group parallelism) | PostgreSQL write TPS (row-lock per player) | 20 pods (partitioned by `player_id`; 20 partitions) |
| **analytics-worker** | Yes (dedicated consumer group) | ClickHouse insert throughput | 20 pods × 5 partitions each |
| **moderation-service** | Singleton acceptable | — | 1–2 pods (low throughput) |

---

## 5. Gameplay PostgreSQL — Sharding Strategy

### 5.1 The Bottleneck

The `game_sessions` table is the highest-write table in the system. At 100K concurrent games with ~1 command per second per game:

**~100,000 TPS** on `game_sessions` (each command acquires a `SELECT FOR UPDATE` row lock, updates state, inserts `game_events` rows, and inserts `outbox` rows — all in one transaction).

A single unsharded PostgreSQL instance on commodity hardware handles ~10K–30K TPS for row-lock-heavy write workloads. At 100K TPS, the gameplay database is the primary bottleneck.

### 5.2 Sharding by game_id

The gameplay database is sharded by `game_id % N` where **N = 16** (a power of two for even distribution; chosen to provide headroom above the sustained rate).

| Shard | Tables owned | Connection routing |
|---|---|---|
| shard_0 … shard_15 | `game_sessions`, `game_events`, `outbox`, `rooms` (filtered by game_id prefix / room_id prefix) | API Gateway or service-level router routes each request based on提取 `game_id` from URL path |

**Routing:** Each `room-gameplay-service` pod connects to all 16 shards but processes a given game on exactly one shard (determined by `game_id % 16`). The `game_id` is included in every command URL (`POST /v1/games/{game_id}/commands/play-card`), so the Gateway or an internal routing layer can hash-route the request to any pod — any pod can reach any shard.

**Connection pooling:** Each pod maintains a connection pool of 16 sub-pools (one per shard). At 50 pods, each shard sees ~50 connections, well within PostgreSQL's connection limit.

**Per-shard TPS:** 100,000 / 16 ≈ 6,250 TPS per shard. This is within a single PostgreSQL instance's capacity for write-heavy workloads (a well-tuned PostgreSQL 15+ instance handles ~10K writes/s with SSD-backed storage).

**Idempotency keys** (`gameplay:idem:<game_id>:<key>`) are stored in Redis, not PostgreSQL, and are not affected by sharding.

**Outbox relay:** Each shard has its own `outbox` table. The in-process relay worker polls all 16 shards (or one relay per shard). This is a configuration detail, not a schema change.

**Tournament rooms:** The `rooms` table is also sharded by `room_id` (derived from `game_id` or assigned deterministically). The `matchmaking_queue` table remains unsharded (single-table, low write volume; can be on any shard or a dedicated small instance).

**Migration path:** Start with N=4 shards. Scale to N=8, then N=16 as concurrent game count grows. Resharding requires a brief downtime window for data movement but no schema changes (all queries already include `game_id` / `room_id`).

### 5.3 Other PostgreSQL Instances

| Database | Estimate TPS | Sharding? | Sizing |
|---|---|---|---|
| Gameplay (sharded) | ~100K TPS (distributed across 16 shards) | Yes — by `game_id % 16` | 16 instances; each ~6K TPS |
| Identity | ~5K TPS (login surge) | No | Single instance; read-heavy (JWT validation hits Redis cache) |
| Tournament + Ranking | ~10K TPS (round-end burst) | No | Single instance; scaling via row-lock isolation |
| Spectator (PostgreSQL) | ~1K TPS (append-only logs) | No | Single instance; append-only workload |

---

## 6. Redis Instance Sizing

| Instance | Peak memory | Peak TPS | Sizing |
|---|---|---|---|
| **cache** (`allkeys-lfu`) | ~2 GB (1M players × ~2 KB VSF cache entries + idempotency keys) | ~200K reads/s (VSF) + ~100K writes/s (idempotency) | Single instance with Sentinel; 4 GB allocated |
| **timer** (`noeviction`) | ~50 MB (100K games × 1–3 timer keys × ~200 bytes each) | ~200K writes/s (timer set/reset at command rate) | Single instance with Sentinel; 1 GB allocated |
| **leaderboard** (`noeviction`) | ~50 MB (1M players × ~50 bytes each × 2 sorted sets) | ~100K writes/s (Elo updates at round end) + ~10K reads/s (leaderboard queries) | Single instance with Sentinel; 1 GB allocated |
| **session-invalidation** (Pub/Sub) | Negligible (no persistence) | ~1K publishes/s (login/logout events) | Single instance with Sentinel; 256 MB allocated |
| **spectator-streams** (`noeviction`) | **~6 GB** (100K games × ~60 KB per game stream) | ~300K XADD/s + ~1M XREAD/s (spectators reading streams) | **Dedicated instance** with Sentinel; 8 GB allocated; consider Redis Cluster for this tier only |
| **rate-limit** | ~500 MB (1M users × sliding window ZSET) | ~200K reads/s + ~100K writes/s | Single instance with Sentinel; 1 GB allocated |

**Total Redis memory:** ~10 GB across all instances. Each instance runs with Sentinel for HA. The spectator-streams instance is the largest and benefits from Redis Cluster (or a dedicated 3-node cluster) for memory distribution.

---

## 7. Analytics — ClickHouse Burst

At round end, ~100,000 `GameCompleted` events arrive within ~60 seconds:

| Metric | Value |
|---|---|
| Burst rate | ~1,666 events/s sustained over 60s |
| Peak batch insert rate | ~1,666 rows/s (each GameCompleted = 1 row in `game_results`) |
| ClickHouse capacity | 100K+ rows/s per node (well above burst) |
| Sizing | 2-node ClickHouse cluster with replication; 1 shard sufficient for this volume |

**No sharding needed for ClickHouse.** The burst is absorbable by a single node with batch inserts every 500ms.

---

## 8. Network Bandwidth Estimates

| Path | Peak bandwidth | Rationale |
|---|---|---|
| Client ↔ Gateway (incoming) | ~300 MB/s | 1M players × ~300 bytes/command avg |
| Gateway ↔ room-gameplay-service | ~500 MB/s | Commands + 200 OK responses |
| room-gameplay-service ↔ Kafka | ~600 MB/s | 300K events/s × ~2 KB avg event payload |
| spectator-service ↔ Redis Streams | ~2 GB/s | 10M spectators × ~200 bytes/event × 3 events/s per game |
| ranking-service ↔ PostgreSQL | ~50 MB/s | 100K Elo writes × ~500 bytes each |

These are burst estimates. Sustained rates are ~20–30% of peak.

---

## 9. Horizontal vs. Singleton Components

| Component | Scaling model | Rationale |
|---|---|---|
| API Gateway | Horizontal (auto-scale by connection count) | Stateless per-request; in-memory WS registry per instance |
| room-gameplay-service | Horizontal (auto-scale by Kafka partition or request rate) | Per-game serialization via PostgreSQL row lock; sharding distributes DB load |
| tournament-service | Horizontal (limited scale-out) | Per-match row locks; only ~100K matches at peak but ~1 command/s each |
| identity-service | Horizontal | Per-player row locks; reads cached in Redis |
| spectator-service | Horizontal (auto-scale by WS connection count) | No sticky routing; reads from shared Redis Streams |
| ranking-service | Horizontal (Kafka consumer group) | Scales with partition count |
| analytics-worker | Horizontal (Kafka consumer group) | Scales with partition count |
| moderation-service | **Singleton** | Very low throughput; no benefit to horizontal scaling; admin-only endpoints |

---

## 10. Spectator Multiplier Analysis

The 10:1 spectator-to-player ratio means:

- At 100K active games with 1M players, there are up to 10M spectator connections.
- Each spectator receives ~2–5 game events per second per game they're watching (filtered through `spectator:stream:{game_id}`).
- The spectator-service fan-out is the most connection-intensive component. It is designed to be stateless (no sticky routing) with all live state in Redis Streams, enabling horizontal scaling.
- At 10M connections, a CDN/edge layer (e.g., Cloudflare Workers, regional edge proxies) is recommended to terminate a large fraction of connections before they reach the spectator-service instances. The architecture supports this: the spectator-service pushes to Redis Streams; edge nodes can subscribe to the same streams and push to locally-connected spectators. This is an optimization for >5M connections and is not required at lower scale.

**Capping:** If edge infrastructure is unavailable, the spectator-service can cap at ~5M connections with ~50–100 instances at ~100K connections each. Beyond this, spectators experience queueing or are served from cached BracketView read models rather than live streams.