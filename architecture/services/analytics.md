# Analytics / Read Models Service

**Bounded Context:** Analytics / Read Models  
**Status:** Phase 4 — complete  
**Decisions applied:** O8 (ClickHouse), R3 (eventual consistency), CQRS (read-side only)

---

## 1. Purpose and Scope

Analytics is a **pure read-side context**. It accepts no commands from clients and issues no commands to other services. All writes are driven by Kafka event consumption.

**Owns:**
- `player_statistics` — per-player aggregate stats (games played, win rate, card burden, tournament placements).
- `tournament_bracket` — full bracket structure with room assignments and match results.
- `round_standings` — per-round player rankings within a tournament.
- `game_history` — per-player list of completed games with outcome and Elo delta.
- `leaderboard_display` — display copy of Elo leaderboard, refreshed from `ranking-events`.

**Does NOT own:**
- `GameSession` or game write state (owned by Room Gameplay).
- `EloRecord` (owned by Ranking); leaderboard here is a display copy.
- Tournament lifecycle decisions (owned by Tournament Orchestration).
- Spectator projection read models (owned by Spectator View).

**Key constraint:** Analytics consumers must absorb the burst of ~100,000 `GameCompleted` events at tournament round end without creating backpressure on Room Gameplay writers.

---

## 2. Containers

### 2.1 `analytics-game-worker` (N instances)

| Property | Value |
|---|---|
| **Consumer group** | `analytics-game-cg` |
| **Topic** | `game-events` |
| **Instances** | 20 workers (each owns ~5 partitions of the 100-partition `game-events` topic) |
| **Primary responsibility** | Absorb `GameCompleted` burst; batch-insert into ClickHouse; update player_statistics |

Each worker accumulates incoming events in an in-memory buffer and flushes to ClickHouse in batches every **500ms** (or when the buffer reaches 1,000 events, whichever comes first). This decouples ClickHouse insert throughput from Kafka delivery cadence and amortizes the per-insert overhead into bulk operations.

**Idempotency:** `game_id` is the dedup key. ClickHouse tables use `ReplacingMergeTree` engine; duplicate inserts with the same `game_id` are collapsed on merge. Workers also maintain a local in-memory bloom filter per batch to skip obvious duplicates before insertion.

### 2.2 `analytics-tournament-worker` (M instances)

| Property | Value |
|---|---|
| **Consumer group** | `analytics-tournament-cg` |
| **Topic** | `tournament-events` |
| **Instances** | 10 workers |
| **Primary responsibility** | Update `tournament_bracket` and `round_standings` on `MatchCompleted`, `RoundCompleted`, `TournamentCompleted` |

### 2.3 `analytics-ranking-worker` (K instances)

| Property | Value |
|---|---|
| **Consumer group** | `analytics-ranking-cg` |
| **Topic** | `ranking-events` |
| **Instances** | 5 workers |
| **Primary responsibility** | Update `leaderboard_display` and `game_history.elo_delta` on `EloUpdated`, `TournamentEloUpdated`, `EloReverted` |

### 2.4 `analytics-service`

| Property | Value |
|---|---|
| **Technology** | JVM or Go service; Primary store: ClickHouse 23+ (columnar, analytics-native; O8 decision); Bracket store: PostgreSQL (`analytics` schema) for relational tree queries |
| **Primary responsibility** | Read-only query API for all analytics read models |
| **Instances** | Horizontally scalable; stateless |

**Interfaces (inbound):**
- REST (HTTP from API Gateway; all endpoints read-only):
  - `GET /v1/analytics/players/{player_id}/stats` — lifetime stats
  - `GET /v1/analytics/players/{player_id}/history?page=N` — paginated game history
  - `GET /v1/analytics/tournaments/{tournament_id}/bracket` — full bracket tree
  - `GET /v1/analytics/tournaments/{tournament_id}/rounds/{round_number}/standings` — round standings
  - `GET /v1/analytics/leaderboard?type=casual|tournament&limit=N` — leaderboard display
  - `GET /v1/analytics/games/{game_id}/summary` — post-game summary (aggregate stats; not the authoritative game log — see Spectator View for that)

All endpoints are **admin or public read**. No mutations accepted. Tournament bracket and leaderboard are publicly accessible. Player stats are accessible to the player themselves and to admins; rate-limited per IP and per user via API Gateway.

---

## 3. Spike Absorption

### 3.1 The Problem

At tournament round end, up to 100,000 `GameCompleted` events arrive within ~60 seconds (all rooms completing at roughly the same time). This is a ~1,666 events/second burst, sustained for ~60 seconds. Ranking, Spectator View, Tournament Orchestration, and Analytics all consume the same events from `game-events`.

**Critical requirement:** Analytics consumption lag must not create backpressure on Room Gameplay writers. Kafka guarantees this by design — each consumer group reads independently. A slow Analytics consumer only affects its own consumer group lag; Room Gameplay writers are unaffected.

### 3.2 Consumer Group Isolation

```
game-events topic (100 partitions)
    │
    ├── consumer group: tournament-cg        (Tournament Orchestration)
    ├── consumer group: ranking-cg            (Ranking)
    ├── consumer group: spectator-game-cg     (Spectator View)
    └── consumer group: analytics-game-cg     (Analytics — this context)
```

Each consumer group maintains its own offset per partition. Analytics can be 10 minutes behind on `game-events` without affecting the other groups.

### 3.3 Worker Scaling for the Burst

With 100 partitions on `game-events` and 20 `analytics-game-worker` instances, each worker owns 5 partitions. Each partition delivers events for a subset of games (partitioned by `game_id`).

At peak burst (100,000 `GameCompleted` events in 60s ≈ 1,666/s total, 16.7/s per partition):
- 20 workers × 5 partitions each: each worker processes ~83 events/second at burst peak.
- ClickHouse bulk insert: 1,000-event buffer fills in ~12 seconds; flushes automatically at the 500ms timer for smaller batches.
- ClickHouse sustained insert throughput: 100K+ rows/s per node. The 1,666/s burst is well within capacity.

After the burst, consumer lag naturally drains. Ops monitoring: `analytics-game-cg` consumer lag per partition is a primary dashboard metric.

### 3.4 Backpressure Boundary

ClickHouse insert failures (e.g., node overload) cause the worker to pause and retry with exponential backoff (up to 30s). During this time, Kafka offsets are not committed and consumer lag grows. This is acceptable — the lag will drain when ClickHouse recovers. Room Gameplay is unaffected.

If ClickHouse is unavailable for >5 minutes, `analytics-game-worker` pauses consumption and alerts. Analytics read models become stale but no data is lost (Kafka retention = 7 days for `game-events`).

---

## 4. Persistence: ClickHouse

### 4.1 Why ClickHouse (O8)

| Criterion | ClickHouse | PostgreSQL (read-optimized) |
|---|---|---|
| Insert throughput (burst) | 100K+ rows/s columnar batch | ~10K rows/s with concurrent query load |
| Query pattern | Aggregations (SUM, COUNT, AVG) over millions of rows | Good for indexed lookups; slower on full scans |
| Schema flexibility | Schema migrations are online (no locks on columnar tables) | ALTER TABLE locks can be costly at scale |
| Materialized views | Native, incremental, updated on insert | Require explicit REFRESH; costly under write load |
| Update / DELETE | Not supported (append-only) | Fully supported |
| Operational complexity | Separate cluster (additional ops burden) | Already operated (shared infra with other contexts) |

The append-only workload (events never update; stats are recomputed from new events) maps exactly to ClickHouse's design. The inability to do UPDATE or DELETE is a strength, not a limitation: compensation events (`EloReverted`, `GameResultVoided`) append corrective rows; queries SUM over all rows to produce the current value.

### 4.2 ClickHouse Tables

**`game_results`** — one row per `GameCompleted` event:
```sql
CREATE TABLE game_results (
  game_id           UUID,
  match_id          UUID,
  tournament_id     UUID,
  game_type         Enum8('casual' = 1, 'tournament' = 2),
  completed_at      DateTime,
  duration_seconds  UInt32,
  player_results    Array(Tuple(
    player_id       UUID,
    placement       UInt8,      -- 1 = first out, N = last remaining
    cards_remaining UInt8,
    forfeited       Bool,
    elo_delta       Float32     -- populated after EloUpdated consumed
  )),
  schema_version    UInt8 DEFAULT 1
) ENGINE = ReplacingMergeTree(completed_at)
  ORDER BY (game_id)
  PARTITION BY toYYYYMM(completed_at);
```

**`player_stats_mv`** — materialized view over `game_results`:
```sql
CREATE MATERIALIZED VIEW player_stats_mv
ENGINE = AggregatingMergeTree()
ORDER BY (player_id, game_type)
AS SELECT
  pr.player_id,
  game_type,
  countState()         AS games_played,
  sumState(if(pr.forfeited = false AND pr.placement = 1, 1, 0)) AS wins,
  sumState(pr.cards_remaining)  AS total_cards_remaining,
  sumState(pr.elo_delta)        AS total_elo_delta
FROM game_results
ARRAY JOIN player_results AS pr
GROUP BY pr.player_id, game_type;
```

The query API runs `SELECT ... FINAL` on the materialized view for low-latency per-player lookups.

**`elo_history`** — one row per `EloUpdated` event (appended by `analytics-ranking-worker`):
```sql
CREATE TABLE elo_history (
  player_id     UUID,
  game_id       UUID,
  elo_before    Float32,
  elo_after     Float32,
  delta         Float32,
  recorded_at   DateTime,
  reverted      Bool DEFAULT false    -- set true by EloReverted row
) ENGINE = MergeTree()
  ORDER BY (player_id, recorded_at);
```

**`tournament_bracket`** — one row per match result (PostgreSQL; small data, relational structure preferred):

This table is stored in **PostgreSQL** (not ClickHouse) because it has a relational tree structure (rounds → rooms → matches → games) better suited to relational queries. `analytics-tournament-worker` writes here directly.

```sql
CREATE TABLE tournament_bracket (
  id                BIGSERIAL PRIMARY KEY,
  tournament_id     UUID NOT NULL,
  round_number      INT NOT NULL,
  room_id           UUID NOT NULL,
  match_id          UUID,
  player_results    JSONB,   -- [{player_id, match_wins, outcome}]
  completed_at      TIMESTAMPTZ
);
```

### 4.3 Idempotency in ClickHouse

ClickHouse's `ReplacingMergeTree` deduplicates on `ORDER BY` key at merge time (background, asynchronous). For the query layer, `SELECT ... FINAL` forces deduplication at query time. Workers also skip known-processed `game_id`s using an in-memory bloom filter per batch window.

---

## 5. Events Consumed

### 5.1 From `game-events` (consumer group `analytics-game-cg`)

| Event | Action |
|---|---|
| `GameCompleted` | INSERT into `game_results` (batch buffer → ClickHouse every 500ms) |
| `PlayerForfeited` | Carried in `GameCompleted.forfeited`; no separate action |

All other `game-events` event types are ignored by Analytics. The `GameCompleted` payload is the authoritative summary of the game.

### 5.2 From `tournament-events` (consumer group `analytics-tournament-cg`)

| Event | Action |
|---|---|
| `TournamentStarted` | Initialize `tournament_bracket` rows for round 1 structure |
| `TournamentRoomAssigned` | Insert room-to-bracket mapping |
| `MatchCompleted` | Update match result in `tournament_bracket` (PostgreSQL UPSERT by `match_id`) |
| `RoundCompleted` | Mark round complete; compute round standings snapshot |
| `TournamentCompleted` | Mark tournament complete; seal bracket |
| `TournamentCancelled` | Mark tournament cancelled in bracket |

### 5.3 From `ranking-events` (consumer group `analytics-ranking-cg`)

| Event | Action |
|---|---|
| `EloUpdated` | INSERT into `elo_history`; update `leaderboard_display` Redis sorted set |
| `TournamentEloUpdated` | INSERT into `elo_history` (tournament variant) |
| `EloReverted` | INSERT corrective row into `elo_history` (`reverted = true`); update leaderboard sorted set |

### 5.4 From `moderation-events` (consumer group `analytics-moderation-cg`)

| Event | Action |
|---|---|
| `GameResultVoided` | Mark game row as voided in `game_results` (append corrective row with `voided = true`) |
| `GameFlagged` | INSERT flag event into `game_flags` ClickHouse table (for admin dashboards) |

---

## 6. Query API

All endpoints are **read-only**. No mutations accepted. All responses include a `data_as_of` timestamp (last Kafka event processed) so callers can assess freshness.

### 6.1 Player Statistics

```
GET /v1/analytics/players/{player_id}/stats

Response:
{
  "player_id": "...",
  "casual": {
    "games_played": 142,
    "wins": 48,
    "win_rate": 0.338,
    "current_elo": 1523.0,
    "avg_cards_remaining": 2.1
  },
  "tournament": {
    "games_played": 37,
    "wins": 15,
    "tournament_placements": [...]
  },
  "data_as_of": "2026-05-16T10:22:00Z"
}
```

### 6.2 Game History

```
GET /v1/analytics/players/{player_id}/history?type=casual&page=1&limit=20

Response:
{
  "games": [
    {
      "game_id": "...",
      "completed_at": "...",
      "placement": 1,
      "players": 6,
      "elo_delta": +14.2,
      "forfeited": false
    }
  ],
  "page": 1,
  "total": 142
}
```

### 6.3 Tournament Bracket

```
GET /v1/analytics/tournaments/{tournament_id}/bracket

Response: full bracket tree with round-by-round results.
Suitable for frontend bracket visualization.
```

### 6.4 Round Standings

```
GET /v1/analytics/tournaments/{tournament_id}/rounds/{round_number}/standings

Response: ordered list of players with match results within the round.
```

### 6.5 Leaderboard Display

```
GET /v1/analytics/leaderboard?type=casual&limit=100

Response: top-N players by Elo with rank and score.
Data source: Redis ZRANGE ... REV WITHSCORES on analytics:leaderboard:casual.
```

---

## 7. Failure Handling

| Failure | Behavior |
|---|---|
| ClickHouse node down | Workers buffer in-memory and retry with exponential backoff; Kafka offsets not committed; consumer lag grows; alert at >5min lag |
| Worker pod crash | Kafka rebalances partitions to surviving workers; processing resumes from last committed offset; possible duplicate events on restart (idempotent by game_id) |
| ClickHouse duplicate insert | `ReplacingMergeTree` deduplicates at merge; `SELECT FINAL` forces dedup at query time; bloom filter minimizes in-batch duplicates |
| Slow ClickHouse merge | Queries use `FINAL` modifier; slightly slower queries acceptable (analytics is not latency-critical) |
| Consumer lag spike at burst | By design — consumer lag grows during the 100K GameCompleted burst and drains afterward; dashboards show expected spike; SLO is data freshness within 10 minutes post-round |

---

## 8. Dependencies on Other Contexts

| Upstream context | Dependency | Pattern |
|---|---|---|
| Room Gameplay | `game-events` Kafka topic (read-only) | Async event consumption; no sync calls |
| Tournament Orchestration | `tournament-events` Kafka topic (read-only) | Async event consumption |
| Ranking | `ranking-events` Kafka topic (read-only) | Async event consumption |

**No synchronous dependencies** on any other service. Analytics is fully decoupled from all write-side contexts.
