# UnoArena — Container View

This document describes every runnable component (container) in the UnoArena system, their primary responsibilities, technology choices, trust boundaries, and ownership. It is the authoritative reference for what gets deployed — all per-service specs must be consistent with the containers named here.

All decisions are traceable to the plan in [PLAN.md](./PLAN.md) and the resolved decisions table therein.

---

## 1. Container Diagram

```
╔══════════════════════════════════════════════════════════════════════════════════════╗
║  PUBLIC INTERNET                                                                      ║
║                                                                                       ║
║   Browsers / Mobile Clients                                                           ║
║        │   WebSocket (wss://)         REST (https://)                                ║
╚════════╪═══════════════════════════════════════════════╪════════════════════════════╝
         │                                               │
         ▼                                               ▼
╔══════════════════════════════════════════════════════════════════════════════════════╗
║  DMZ / Edge                                                                           ║
║                                                                                       ║
║  ┌───────────────────────────────────────────────────────────────────────────────┐   ║
║  │                           API Gateway                                          │   ║
║  │  • Terminates TLS                                                              │   ║
║  │  • Terminates WebSocket connections (active players + spectators)             │   ║
║  │  • Verifies JWT signature locally (public key loaded at startup)              │   ║
║  │  • Validates valid_sessions_from via Redis (Cache-Aside)                      │   ║
║  │  • Per-IP rate limiting (Redis INCR fixed-window, fail-open)                 │   ║
║  │  • Per-user rate limiting (Redis ZSET sliding-window)                         │   ║
║  │  • Subscribes to Redis Pub/Sub session:invalidated:* → closes stale WS       │   ║
║  │  • Routes REST commands to downstream services (HTTP/1.1 with circuit breaker)│   ║
║  │  • Routes WebSocket messages to Room Gameplay service                         │   ║
║  │  • Emits ActionRateLimitExceeded events to identity-events topic              │   ║
║  │  Tech: custom service (e.g., Go or Java) or configurable gateway (e.g., Kong) │   ║
║  └───────────────────────────────────────────────────────────────────────────────┘   ║
╚══════════════════════════════════════════════════════════════════════════════════════╝
         │  HTTP (internal, mTLS)             │  Redis commands (internal)
         ▼                                    ▼
╔══════════════════════════════════════════════════════════════════════════════════════╗
║  INTERNAL SERVICES TIER                                                               ║
║                                                                                       ║
║  ┌──────────────────────────┐  ┌─────────────────────────────────────────────────┐  ║
║  │  identity-service        │  │  room-gameplay-service                           │  ║
║  │  (Identity / Session)    │  │  (Room Gameplay)                                 │  ║
║  │                          │  │                                                  │  ║
║  │  • Register / Login /    │  │  • Accepts game commands over WebSocket         │  ║
║  │    Logout                │  │    (forwarded by Gateway)                       │  ║
║  │  • Issues JWTs           │  │  • Enforces state_version + legal-play rules    │  ║
║  │  • Manages               │  │  • Transactional: state + game_events +         │  ║
║  │    valid_sessions_from   │  │    outbox in single PostgreSQL transaction      │  ║
║  │  • Creates               │  │  • Per-game serialization via PG row lock       │  ║
║  │    ReconnectionWindow    │  │  • Manages turn timers + challenge windows      │  ║
║  │    (Redis TTL)           │  │    (Redis TTL + keyspace notifications)         │  ║
║  │  • Publishes             │  │  • Distributed lock on lobby start (Redis SETNX)│  ║
║  │    session:invalidated   │  │  • Exposes game log read API (admin + audit)    │  ║
║  │    to Redis Pub/Sub      │  │  Tech: JVM or Go service + PostgreSQL           │  ║
║  │  Tech: JVM or Go service │  └──────────────┬──────────────────────────────────┘  ║
║  └──────────────┬───────────┘                 │ outbox relay (internal process)      ║
║                 │                             ▼                                      ║
║                 │                  ┌────────────────────────┐                       ║
║                 │                  │  outbox-relay-worker    │                       ║
║                 │                  │  (internal to           │                       ║
║                 │                  │   room-gameplay-service)│                       ║
║                 │                  │                         │                       ║
║                 │                  │  • Polls outbox table   │                       ║
║                 │                  │  • Publishes to Kafka   │                       ║
║                 │                  │    with idempotent      │                       ║
║                 │                  │    producer             │                       ║
║                 │                  │  • Marks rows delivered │                       ║
║                 │                  └───────────┬─────────────┘                      ║
║                 │                              │                                     ║
║  ┌──────────────┼──────────────────────────────┤                                     ║
║  │              │                              │                                     ║
║  │  ┌───────────┴────────────────────────────────────────────────────────────────┐  ║
║  │  │                          Kafka Broker (cluster)                             │  ║
║  │  │                                                                              │  ║
║  │  │  game-events          — partitioned by game_id (≥100 partitions)           │  ║
║  │  │  tournament-events    — partitioned by tournament_id                       │  ║
║  │  │  tournament-kickoff   — partitioned by room_id (≥100 partitions);          │  ║
║  │  │                          TournamentRoomAssigned only; produced by           │  ║
║  │  │                          tournament-service; consumed by Room Gameplay      │  ║
║  │  │                          workers (surge fan-out at round kickoff)           │  ║
║  │  │  identity-events      — partitioned by player_id                           │  ║
║  │  │  ranking-events       — partitioned by player_id                           │  ║
║  │  │  moderation-events    — partitioned by player_id or game_id                │  ║
║  │  │                                                                              │  ║
║  │  │  Retention: 7 days (game-events, tournament-kickoff);                       │  ║
║  │  │             30 days (tournament-events/identity/ranking/moderation)         │  ║
║  │  └───────────┬────────────────────────────────────────────────────────────────┘  ║
║  │              │                                                                    ║
║  │  ┌───────────┼────────────────────────────────────────────────────────────────┐  ║
║  │  │           │   DOWNSTREAM CONSUMERS                                          │  ║
║  │  │           │                                                                  │  ║
║  │  │  ┌────────▼────────┐  ┌──────────────────┐  ┌──────────────────────────┐  │  ║
║  │  │  │ tournament-     │  │ ranking-service   │  │ spectator-service        │  │  ║
║  │  │  │ service         │  │ (Ranking)         │  │ (Spectator View)         │  │  ║
║  │  │  │                 │  │                   │  │                          │  │  ║
║  │  │  │ Consumes:       │  │ Consumes:         │  │ Consumes: game-events,   │  │  ║
║  │  │  │ game-events     │  │ game-events       │  │ tournament-events,       │  │  ║
║  │  │  │ (GameCompleted) │  │ (GameCompleted),  │  │ ranking-events           │  │  ║
║  │  │  │                 │  │ tournament-events │  │                          │  │  ║
║  │  │  │ Owns: Match Bo3 │  │ (TournamentComp.) │  │ Applies privacy          │  │  ║
║  │  │  │ state, round    │  │                   │  │ whitelist at consumption │  │  ║
║  │  │  │ advancement     │  │ Owns: EloRecord   │  │                          │  │  ║
║  │  │  │                 │  │                   │  │ Holds spectator WS       │  │  ║
║  │  │  │ Issues:         │  │ Produces:         │  │ connections (via Gateway)│  │  ║
║  │  │  │ CreateRoom cmds │  │ ranking-events    │  │                          │  │  ║
║  │  │  │ to Room Gameplay│  │ (EloUpdated)      │  │ Stores: PublicGameView   │  │  ║
║  │  │  │                 │  │                   │  │ (Redis), PublicGameLog,  │  │  ║
║  │  │  │ Tech: JVM/Go +  │  │ Tech: JVM/Go +   │  │ BracketView (PG + Redis) │  │  ║
║  │  │  │ PostgreSQL      │  │ PostgreSQL        │  │ Tech: JVM/Go + Redis/PG  │  │  ║
║  │  │  └─────────────────┘  └──────────────────┘  └──────────────────────────┘  │  ║
║  │  │                                                                              │  ║
║  │  │  ┌──────────────────────────────────────────┐  ┌──────────────────────┐   │  ║
║  │  │  │ analytics-worker (N instances)           │  │ moderation-service   │   │  ║
║  │  │  │ + analytics-service                      │  │ (Moderation / Admin) │   │  ║
║  │  │  │ (Analytics / Read Models)                │  │                      │   │  ║
║  │  │  │                                          │  │ Consumes: all topics  │   │  ║
║  │  │  │ Dedicated consumer group per topic       │  │ (for escalation)     │   │  ║
║  │  │  │ N workers × M partitions                 │  │                      │   │  ║
║  │  │  │ Absorbs GameCompleted burst at round end │  │ Issues corrective    │   │  ║
║  │  │  │                                          │  │ commands: HTTP to    │   │  ║
║  │  │  │ analytics-service: read-only query API   │  │ Identity, events to  │   │  ║
║  │  │  │                                          │  │ Kafka                │   │  ║
║  │  │  │ Tech: JVM/Go workers + ClickHouse (TBD)  │  │                      │   │  ║
║  │  │  └──────────────────────────────────────────┘  │ Tech: JVM/Go + PG   │   │  ║
║  │  │                                                  └──────────────────────┘   │  ║
║  │  └────────────────────────────────────────────────────────────────────────────┘  ║
║  │                                                                                    ║
║  └────────────────────────────────────────────────────────────────────────────────┘  ║
╚══════════════════════════════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════════════════════════════╗
║  DATA TIER                                                                            ║
║                                                                                       ║
║  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐    ║
║  │ PostgreSQL   │  │ PostgreSQL   │  │ PostgreSQL   │  │ Redis (cluster)      │    ║
║  │ (identity)   │  │ (gameplay)   │  │ (tournament  │  │                      │    ║
║  │              │  │              │  │  + ranking   │  │ Cache DB (TTL)       │    ║
║  │ player_      │  │ game_        │  │  + spectator │  │ Timer DB (keyspace   │    ║
║  │ profiles     │  │ sessions     │  │  + moderat.) │  │  notifications)      │    ║
║  │ player_      │  │ game_events  │  │              │  │ Leaderboard DB       │    ║
║  │ sessions     │  │ rooms        │  │ tournaments  │  │  (noeviction)        │    ║
║  │              │  │ outbox       │  │ matches      │  │ Pub/Sub channel      │    ║
║  │              │  │              │  │ elo_records  │  │  (session inval.)    │    ║
║  │              │  │              │  │ admin_actions│  │                      │    ║
║  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────────────┘    ║
║  ┌──────────────┐  ┌──────────────────────┐                                        ║
║  │ PostgreSQL   │  │ ClickHouse           │                                        ║
║  │ (analytics)  │  │ (analytics)          │                                        ║
║  │              │  │                      │                                        ║
║  │ tournament_  │  │ game_events_raw      │                                        ║
║  │ bracket      │  │ game_results         │                                        ║
║  │              │  │ player_stats_mv      │                                        ║
║  │              │  │ tournament_bracket_mv│                                        ║
║  └──────────────┘  └──────────────────────┘                                        ║
║                                                                                       ║
║  Note: PostgreSQL instances may be separate servers or logically separate schemas    ║
║  on one server. Tournament, Ranking, Spectator, and Moderation share one            ║
║  PostgreSQL cluster for infrastructure economy; each context uses a dedicated        ║
║  schema and a schema-scoped connection user — cross-schema SELECT/INSERT is         ║
║  prohibited at the database permission level. No service queries another            ║
║  service's schema.                                                                   ║
╚══════════════════════════════════════════════════════════════════════════════════════╝
```

---

## 2. Container Inventory

### 2.1 API Gateway

| Property | Value |
|---|---|
| **Name** | `api-gateway` |
| **Context** | Cross-cutting (not owned by any single bounded context) |
| **Technology** | Custom Go/Java service, or configurable gateway (Kong + custom plugin for WebSocket session management) |
| **Primary responsibility** | Single entry point for all client traffic; TLS termination; JWT verification; rate limiting; WebSocket lifecycle management; per-game sticky routing (load balancer hashes on `game_id`); session-invalidation push path |
| **Instances** | Horizontally scalable; stateless per request (session state in Redis) |
| **Trust boundary** | Public-facing; all input must be treated as untrusted |
| **Owns** | WebSocket connection registry (in-memory per instance, keyed by `player_id`); no durable state |

**Interfaces:**
- Inbound: HTTPS/WSS from clients
- Outbound: HTTP to `identity-service` (cache miss), `room-gameplay-service` (game commands), `tournament-service`, `moderation-service`
- Inbound (internal, mTLS): `POST /internal/push/{player_id}` — server-initiated WebSocket push from any backend service (room-gameplay-service, identity-service). The gateway looks up the player's connection in its in-memory registry and writes the payload to the WebSocket. Returns `200 OK` if delivered, `404` if no live connection for that player (caller treats 404 as a no-op — the player is not connected).
- Redis: reads `identity:vsf:<player_id>` (cache-aside), writes `ratelimit:ip:*` and `ratelimit:user:*`, subscribes to `session:invalidated:*` Pub/Sub

---

### 2.2 identity-service

| Property | Value |
|---|---|
| **Name** | `identity-service` |
| **Context** | Identity / Session |
| **Technology** | JVM or Go service; PostgreSQL (`identity` schema); Redis (Pub/Sub publisher, timer TTL for reconnection windows) |
| **Primary responsibility** | Player registration/login/logout; JWT issuance; `valid_sessions_from` management; single-active-session enforcement; reconnection window creation |
| **Instances** | Horizontally scalable |
| **Owns** | `player_profiles`, `player_sessions` tables in PostgreSQL |

**Interfaces:**
- Inbound: HTTP REST from API Gateway (`/v1/auth/*`, `/v1/players/*`)
- Inbound: HTTP from `moderation-service` (`SuspendPlayer`, `BanPlayer` commands)
- Outbound: `PUBLISH session:invalidated:<player_id>` to Redis Pub/Sub
- Outbound: `SET identity:reconnect:<player_id>:<game_id>` with 60s TTL to Redis
- Outbound: produces `identity-events` Kafka topic (`PlayerRegistered`, `SessionCreated`, `SessionInvalidated`, `ReconnectionWindowStarted`, `ReconnectionWindowExpired`, `PlayerSuspended`, `PlayerBanned`)

---

### 2.3 room-gameplay-service

| Property | Value |
|---|---|
| **Name** | `room-gameplay-service` |
| **Context** | Room Gameplay |
| **Technology** | JVM or Go service; PostgreSQL (`gameplay` schema, sharded ×16 by `game_id % 16`; see CAPACITY_SKETCH.md §5); Redis (timer TTLs, distributed lock, idempotency cache) |
| **Primary responsibility** | All in-game logic, state version enforcement, legal play validation, log-before-broadcast via transactional outbox |
| **Instances** | Horizontally scalable; per-game serialization via PostgreSQL row-level lock (not sticky routing); each pod connects to all 16 shards and routes by `game_id % 16` |
| **Owns** | `game_sessions`, `game_events`, `rooms`, `matchmaking_queue`, `outbox` tables |

**Interfaces:**
- Inbound: WebSocket messages forwarded by API Gateway (game commands)
- Inbound: HTTP from `tournament-service` (`CreateRoom`, `AssignPlayersToRoom`, `ForceCompleteGame`)
- Outbound: PostgreSQL transaction (state + events + outbox in one commit)
- Outbound: Redis timer keys (`gameplay:turn-timer:<game_id>`, `gameplay:challenge:<game_id>:<ver>`)
- Subscribes: Redis keyspace notifications for timer expiry

---

### 2.4 outbox-relay-worker

| Property | Value |
|---|---|
| **Name** | `outbox-relay-worker` |
| **Context** | Room Gameplay (internal process) |
| **Technology** | Same JVM/Go process as `room-gameplay-service`, or a companion sidecar process sharing the same PostgreSQL shards |
| **Primary responsibility** | Read undelivered outbox rows from all 16 shards, publish to Kafka with `enable.idempotence=true`, mark rows delivered |
| **Instances** | One relay thread per shard (16 relay threads per pod); each thread polls its shard's `outbox` table independently |
| **Owns** | No additional storage; reads/writes the `outbox` table owned by `room-gameplay-service` |

---

### 2.5 tournament-service

| Property | Value |
|---|---|
| **Name** | `tournament-service` |
| **Context** | Tournament Orchestration |
| **Technology** | JVM or Go service; PostgreSQL (`tournament` schema); Redis (match timeout TTL, distributed lock for match start) |
| **Primary responsibility** | Tournament/round lifecycle, Bo3 match tracking, round-kickoff fan-out (up to 100K room creations), match timeout enforcement |
| **Instances** | Horizontally scalable; per-match serialization via PostgreSQL row-level lock |
| **Owns** | `tournaments`, `tournament_rounds`, `matches` tables |

**Interfaces:**
- Inbound: HTTP REST from API Gateway (tournament registration, admin tournament management)
- Inbound: HTTP from `moderation-service` (`CancelTournament` command)
- Consumes: `game-events` Kafka topic (consumer group `tournament-cg`) for `GameCompleted`, `PlayerForfeited`
- Consumes: `identity-events` Kafka topic for `PlayerSuspended`, `PlayerBanned`
- Outbound: HTTP to `room-gameplay-service` (`CreateRoom`, `AssignPlayersToRoom`, `ForceCompleteGame`)
- Produces: `tournament-events` Kafka topic

---

### 2.6 ranking-service

| Property | Value |
|---|---|
| **Name** | `ranking-service` |
| **Context** | Ranking |
| **Technology** | JVM or Go service; PostgreSQL (`ranking` schema); Redis (leaderboard sorted sets) |
| **Primary responsibility** | Elo computation, `EloRecord` management, leaderboard maintenance, reversal on void/cancel |
| **Instances** | Horizontally scalable; per-player serialization via PostgreSQL row-level lock |
| **Owns** | `elo_records` table; `ranking:leaderboard:casual` and `ranking:leaderboard:tournament` Redis sorted sets (noeviction policy) |

**Interfaces:**
- Consumes: `game-events` Kafka topic (consumer group `ranking-cg`) for `GameCompleted`
- Consumes: `tournament-events` Kafka topic (consumer group `ranking-tournament-cg`) for `TournamentCompleted`, `TournamentCancelled`
- Consumes: `moderation-events` Kafka topic (consumer group `ranking-moderation-cg`) for `GameResultVoided`
- Consumes: `identity-events` Kafka topic (consumer group `ranking-identity-cg`) for `PlayerRegistered`
- Produces: `ranking-events` Kafka topic (`EloUpdated`, `TournamentEloUpdated`, `EloReverted`)

---

### 2.7 spectator-service

| Property | Value |
|---|---|
| **Name** | `spectator-service` |
| **Context** | Spectator View |
| **Technology** | JVM or Go service; Redis (Streams per `game_id`, PublicGameView hash, LeaderboardView sorted sets); PostgreSQL (PublicGameLog sealed post-game, BracketView persistent) |
| **Primary responsibility** | Privacy-filtered live game projection; holds the application-level spectator WebSocket connection (the API Gateway proxies the WS upgrade to this service; spectator-service reads Redis Streams directly and writes frames to the proxied connection); reconnection snapshots from Stream + Hash |
| **Instances** | Horizontally scalable; no sticky routing required — the API Gateway's WS proxy routes new spectator upgrades to any available instance, and Redis Streams provide shared event history accessible from any instance |
| **Owns** | `public_game_logs`, `bracket_views` PostgreSQL tables; `spectator:stream:<game_id>` Redis Streams; `spectator:gameview:<game_id>` Redis Hashes; `spectator:roomlist:<room_id>` Redis Hashes; `spectator:leaderboard:*` Redis Sorted Sets |

**Interfaces:**
- Inbound: WebSocket connections from API Gateway (spectator streams)
- Inbound: HTTP from API Gateway (game log query, bracket query, leaderboard query)
- Consumes: `game-events` Kafka topic (consumer group `spectator-game-cg`) — applies privacy whitelist at consumption before any data enters read model
- Consumes: `tournament-events` Kafka topic (consumer group `spectator-tournament-cg`)
- Consumes: `ranking-events` Kafka topic (consumer group `spectator-ranking-cg`) for `EloUpdated`
- Consumes: `moderation-events` Kafka topic (consumer group `spectator-moderation-cg`) for `GameFlagged`
- Outbound: WebSocket push to connected spectators; `XADD spectator:stream:<game_id>` (filtered events); `HSET spectator:gameview:<game_id>` (snapshot fields)

---

### 2.8 analytics-service + analytics-worker

| Property | Value |
|---|---|
| **Name** | `analytics-service` (query API) + `analytics-worker` (N consumer instances) |
| **Context** | Analytics / Read Models |
| **Technology** | Workers: JVM or Go; Store: ClickHouse 23+ (columnar, analytics-native; O8 decision); Bracket store: PostgreSQL (`analytics` schema); Query service: JVM/Go |
| **Primary responsibility** | Burst-absorbing projection of all `GameCompleted` events at round end; player stats; bracket/standings views; leaderboard display copies |
| **Instances** | Workers: N instances (e.g., 20 workers × 5 partitions each = 100 partitions coverage); analytics-service: horizontally scalable read API |
| **Owns** | `player_statistics`, `tournament_bracket`, `round_standings`, `game_history`, `leaderboard_display` tables |

**Interfaces:**
- Workers consume: `game-events` (consumer group `analytics-game-cg`), `tournament-events` (consumer group `analytics-tournament-cg`), `ranking-events` (consumer group `analytics-ranking-cg`), `moderation-events` (consumer group `analytics-moderation-cg`)
- `analytics-service`: read-only HTTP API from API Gateway; no commands accepted

---

### 2.9 moderation-service

| Property | Value |
|---|---|
| **Name** | `moderation-service` |
| **Context** | Moderation / Admin |
| **Technology** | JVM or Go service; PostgreSQL (`moderation` schema) |
| **Primary responsibility** | Audit log, admin commands, abuse escalation, corrective command dispatch |
| **Instances** | Single instance sufficient (low traffic); can scale horizontally |
| **Owns** | `admin_actions` table (append-only audit log) |

**Interfaces:**
- Inbound: HTTP REST from API Gateway (admin-authenticated endpoints only)
- Outbound: HTTP to `identity-service` (`SuspendPlayer`, `BanPlayer`)
- Outbound: HTTP to `tournament-service` (`CancelTournament`)
- Produces: `moderation-events` Kafka topic (`GameResultVoided`, `GameFlagged`)
- Consumes: `identity-events` Kafka topic (consumer group `moderation-cg`) for `ActionRateLimitExceeded`

---

## 3. Trust Boundaries

| Boundary | Description |
|---|---|
| **Public Internet → DMZ** | TLS termination at API Gateway. All traffic authenticated via JWT (except registration/login). Source IPs rate-limited. |
| **DMZ → Internal Services Tier** | Internal mTLS between API Gateway and services. API Gateway is the only component with a public interface. |
| **Internal Services → Data Tier** | Services access only their own PostgreSQL schema/instance. No cross-service DB access. Redis accessed by all services but with key-prefix namespacing (`identity:*`, `gameplay:*`, etc.) |
| **Kafka** | Internal broker; services authenticate with SASL/TLS. Each service has producer/consumer permissions scoped to its own topics. |

---

## 4. Cross-Cutting Infrastructure Summary

| Component | Technology | Purpose | Eviction policy |
|---|---|---|---|
| Redis cache instance | Redis 7+ (standalone or Sentinel pair) | `valid_sessions_from` cache, idempotency caches | `allkeys-lfu` |
| Redis timer instance | Redis 7+ (standalone or Sentinel pair) | Turn timers, challenge windows, reconnection windows, match timeouts, AFK counters, distributed locks | `noeviction` (timers must not be silently evicted) |
| Redis leaderboard instance | Redis 7+ (standalone or Sentinel pair) | Casual + tournament Elo leaderboards | `noeviction` (leaderboard must not lose entries) |
| Redis session-invalidation instance | Redis 7+ (standalone or Sentinel pair) | `session:invalidated:*` Pub/Sub channel | N/A (fire-and-forget; eviction irrelevant) |
| Redis spectator-streams instance | Redis 7+ (standalone or Sentinel pair; sized for ~6GB at 100K games) | `spectator:stream:{game_id}` — privacy-filtered game event fan-out with MAXLEN ~200 history; XREAD BLOCK for live delivery; EXPIRE on GameCompleted + 24h | `noeviction` (streams must not be evicted mid-game; deleted via EXPIRE) |

> **Note on Redis Cluster:** Redis Cluster supports only logical DB 0; multiple logical databases (SELECT N) are not available in cluster mode. Each functional Redis tier is therefore a **separate standalone instance or Sentinel-managed pair**, not a shared cluster with multiple logical DBs. Key-prefix namespacing (`identity:*`, `gameplay:*`, etc.) is still applied within each instance to aid observability but is not relied on for isolation — isolation is physical (separate instances). Redis Cluster may be used within each individual instance group for intra-instance HA but is not used to share a single cluster across tiers.

| Kafka | Apache Kafka (or Confluent) | All async cross-context event delivery | Per-topic retention policies |
| PostgreSQL | PostgreSQL 15+ | All durable aggregate state and immutable logs | N/A (durable) |
| ClickHouse | ClickHouse 23+ | Analytics burst-absorbing columnar store; 100K+ rows/s batch insert; materialized views for aggregations | N/A (append-only) |
