# UnoArena — Persistence Layer

This document specifies the primary data store, consistency model, read models, retention policy, and read-path access controls for each bounded context. No context accesses another context's database directly.

---

## Guiding Principles

- **Database per context.** Each bounded context owns its schema. No cross-context joins or shared connection pools.
- **PostgreSQL as the default write-side store.** Chosen for ACID transactions, row-level locking, JSONB flexibility, and operational familiarity. Redis is a supporting layer (cache, timers, leaderboards, streams), never a primary source of truth.
- **Eventual consistency across contexts** via Kafka at-least-once delivery with idempotent consumers.
- **Strong consistency within a context** via PostgreSQL transactions and row-level locking.
- **Append-only logs are immutable.** `game_events` and `admin_actions` tables are never updated or deleted after insertion.

---

## 1. Room Gameplay

### 1.1 Primary Store

**PostgreSQL** (dedicated schema: `gameplay`).

| Table | Purpose | Consistency |
|---|---|---|
| `game_sessions` | Current aggregate state per game. Stores `game_id`, `room_id`, `match_id` (nullable), `status`, `state_version`, `state` (JSONB), `timer_token` (UUID), `created_at`, `updated_at`. | Strong — row-level lock acquired on every command (`SELECT … FOR UPDATE`). |
| `game_events` | Immutable game log. Append-only. `(game_id, state_version)` is the primary key. Each row records the event type, payload (JSONB), and `created_at`. | Strong — written in the same transaction as the state update. Never deleted. |
| `outbox` | Transactional outbox for Kafka delivery. Columns: `id`, `topic`, `partition_key`, `payload` (JSONB), `created_at`, `delivered_at` (nullable). | Strong — written in the same transaction as `game_events`. The relay marks `delivered_at` after Kafka ACK. |
| `rooms` | Room aggregate: `room_id`, `status`, `owner_player_id`, `max_players`, `current_players`, `room_type` (`casual` | `tournament`), `lobby_started_at`, `locked` (bool). | Strong — `SELECT … FOR UPDATE` on matchmaking path. |
| `matchmaking_queue` | Pending queue entries: `player_id`, `queued_at`, `room_preference`. Consumed by `SELECT … FOR UPDATE SKIP LOCKED`. | Strong (row-level lock). |

**Log-before-broadcast guarantee:** Every accepted game command executes a single PostgreSQL transaction that writes to `game_sessions`, `game_events`, and `outbox` atomically. The relay worker reads `outbox` and publishes to Kafka only after the transaction commits. The `200 OK` response to the client is sent after `COMMIT`, ensuring the log is durable before any broadcast.

### 1.2 Supporting Stores (Redis — timer instance)

| Key | Purpose | TTL |
|---|---|---|
| `gameplay:turn-timer:<game_id>` | Turn timer (45s). Token fence via UUID. | 45s |
| `gameplay:challenge:<game_id>:<state_version>` | Challenge window (5s, scoped to state version). | 5s |
| `gameplay:idem:<game_id>:<idempotency_key>` | Idempotency cache for game commands. | game duration + 24h |
| `gameplay:lobby-lock:<room_id>` | Distributed lock for lobby start (prevent double-start). | 10s |
| `gameplay:afk:<game_id>` | Hash: `<player_id>` → AFK event count. | game duration |

### 1.3 Transactional Boundary

One `BEGIN … COMMIT` per accepted command:
1. `SELECT … FOR UPDATE` on `game_sessions` row (serializes commands per game).
2. Validate state version and preconditions.
3. `UPDATE game_sessions` (new state JSONB, incremented `state_version`).
4. `INSERT INTO game_events` (one or more rows).
5. `INSERT INTO outbox` (one or more rows, one per downstream event).
6. `COMMIT`.

Commands that fail validation (version mismatch, illegal play) are rolled back and never written to the log.

### 1.4 Read Models

| Model | Store | How built | Staleness |
|---|---|---|---|
| In-game state for active player | Returned in the `200 OK` command response (from `game_sessions` state JSONB) | Synchronous — always current | Zero (read from the same transaction) |
| PublicGameView for spectators | Redis Hash `spectator:gameview:<game_id>` | Built by `spectator-game-consumer-worker` consuming `game-events` | Seconds (Kafka consumer lag) |
| PublicGameLog (post-game audit) | PostgreSQL `spectator` schema | Sealed on `GameCompleted`; assembled from `game_events` rows | Immutable after sealing |

### 1.5 Retention and Audit

- `game_events` rows are **retained indefinitely** (immutable game log). Archival to cold storage after 90 days is an operational option but is not required for correctness.
- `game_sessions` rows may be archived (status = `completed` or `cancelled`) after 30 days.
- `outbox` rows are deleted once `delivered_at` is set and the row is older than 48 hours.
- PII in `game_events`: player IDs are stored in event payloads. Card identities in player hands are part of the game state JSONB (not in `game_events` which only records played/drawn cards). PII redaction from cold archives follows the platform's data-retention policy.

### 1.6 Game Log Read Path

The immutable game log (`game_events`) is accessible via:

| Accessor | Purpose | Authorization |
|---|---|---|
| **Active player** | View own hand history post-game | JWT-authenticated; `GET /v1/games/{game_id}/log`. Service verifies `player_id` is a participant of `game_id`. |
| **Spectator (post-game)** | View full public game log | JWT-authenticated (or unauthenticated for public tournaments); served from `PublicGameLog` (private hand data excluded). |
| **Tournament Orchestration** (internal) | Match result verification | mTLS internal call; `GET /v1/internal/games/{game_id}/result`. Returns outcome fields only, not full event stream. |
| **Moderation** (admin) | Dispute resolution; voiding a result | Admin JWT with `role: admin`; `GET /v1/admin/games/{game_id}/log`. Full event stream including hand data (for dispute review). Rate-limited per admin. |
| **Analytics** | Aggregate analysis | Reads from ClickHouse read model, not directly from `game_events`. Analytics does not have DB access to Room Gameplay's schema. |

---

## 2. Tournament Orchestration

### 2.1 Primary Store

**PostgreSQL** (dedicated schema: `tournament`).

| Table | Purpose | Consistency |
|---|---|---|
| `tournaments` | Lifecycle state: `tournament_id`, `status`, `format`, `max_players`, `current_round`, `created_at`. | Strong |
| `tournament_rounds` | Per-round metadata: `round_id`, `tournament_id`, `round_number`, `status`, `qualifier_pool_size`, `phase_start_threshold`. | Strong |
| `matches` | Bo3 match state: `match_id`, `room_id`, `round_id`, `player_ids[]`, `game_sequence`, `match_wins` (JSONB), `status`, `timed_out`. Row locked on `GameCompleted` processing. | Strong — `SELECT … FOR UPDATE` per `match_id` when processing `GameCompleted`. |
| `match_games` | Individual game outcomes within a match: `match_id`, `game_id`, `sequence_number`, `winner_player_id`, `placements` (JSONB). | Strong — written on `GameCompleted`. |
| `kickoff_outbox` | Transactional outbox for `tournament-kickoff` Kafka topic. Same relay pattern as Room Gameplay. | Strong — written in same transaction as round kickoff. |
| `registrations` | Player registrations: `tournament_id`, `player_id`, `registered_at`, `status`. | Strong |

### 2.2 Supporting Stores (Redis — timer instance)

| Key | Purpose | TTL |
|---|---|---|
| `tournament:match-timeout:<match_id>` | 20-minute match timeout timer. | 1200s |
| `tournament:match-lock:<match_id>` | Distributed lock for match start. | 10s |

### 2.3 Transactional Boundary

- **Round kickoff:** One transaction per round writes all room assignments to `kickoff_outbox` (up to 100K rows in batches). The relay reads and publishes to the `tournament-kickoff` Kafka topic.
- **GameCompleted processing:** `SELECT … FOR UPDATE` on `matches` row → update `match_wins`, `match_games` insert, `kickoff_outbox` insert (if next game starts) or `TournamentRound` update (if match complete). All in one transaction.

### 2.4 Read Models

| Model | Store | How built | Staleness |
|---|---|---|---|
| BracketView | Redis Hash (hot) + PostgreSQL (persistent) | Updated by `tournament-service` on `MatchCompleted`, `AdvancementResolved` | Seconds |
| Round standings snapshot | PostgreSQL `tournament` schema | Updated on round completion | Consistent at round end |

### 2.5 Retention and Audit

- Tournament records are retained indefinitely (audit, dispute, ranking reference).
- `kickoff_outbox` cleaned after relay delivers; rows older than 48h and delivered are deleted.

---

## 3. Identity / Session

### 3.1 Primary Store

**PostgreSQL** (dedicated schema: `identity`).

| Table | Purpose | Consistency |
|---|---|---|
| `player_profiles` | `player_id`, `username`, `email_hash`, `status` (`active` | `suspended` | `banned`), `created_at`. | Strong |
| `player_sessions` | `session_id`, `player_id`, `valid_sessions_from` (timestamp), `created_at`, `device_fingerprint`. | Strong |
| `reconnection_windows` | `player_id`, `game_id`, `opened_at`, `expires_at`, `closed_at` (nullable). | Strong |
| `identity_outbox` | Transactional outbox for `identity-events` Kafka topic. | Strong |

### 3.2 Supporting Stores (Redis — cache instance + timer instance)

| Key | Instance | Purpose | TTL |
|---|---|---|---|
| `identity:vsf:<player_id>` | Cache | `valid_sessions_from` timestamp (JWT validation fast path) | 60s ± 5s jitter |
| `identity:reconnect:<player_id>:<game_id>` | Timer | Reconnection window timer flag | 60s |
| `identity:idem:<player_id>:<idempotency_key>` | Cache | Idempotency cache for session commands | 24h |

### 3.3 Transactional Boundary

- **Login:** One transaction: update `valid_sessions_from` in `player_sessions`, insert `identity_outbox` rows (`SessionCreated`, `SessionInvalidated`). After commit: DELETE `identity:vsf:<player_id>` from Redis cache; publish to `session:invalidated:<player_id>` Redis Pub/Sub.
- **Reconnect window open:** One transaction: insert `reconnection_windows` row, insert `identity_outbox` row (`ReconnectionWindowStarted`), `SET identity:reconnect:<player_id>:<game_id> NX PX 60000`.

### 3.4 Read Models

| Model | Store | How built | Staleness |
|---|---|---|---|
| `valid_sessions_from` (gateway validation) | Redis cache | Cache-aside on first miss; deleted on new login | Up to 60s stale (acceptable by design; see ADR-005) |
| Player status (active/suspended/banned) | Redis cache (same key as VSF; status field in JSONB) or direct PostgreSQL | Read on JWT validation | Same as above |

### 3.5 Retention and Audit

- `player_profiles` and `player_sessions` are retained per GDPR-equivalent policy; email is stored hashed only.
- `reconnection_windows` cleaned after 7 days.
- PII deletion: on account deletion, `email_hash` is cleared; `player_id` is retained in game logs as a pseudonym.

---

## 4. Ranking

### 4.1 Primary Store

**PostgreSQL** (dedicated schema: `ranking`).

| Table | Purpose | Consistency |
|---|---|---|
| `elo_records` | One row per player: `player_id`, `casual_elo`, `tournament_elo`, `casual_games_played`, `last_casual_game_id`, `last_tournament_id`. | Strong — row-level lock on update (`SELECT … FOR UPDATE`). |
| `elo_deltas` | Audit: each Elo change event: `player_id`, `game_id` or `tournament_id`, `delta`, `reason`, `applied_at`. Append-only. | Strong |

### 4.2 Transactional Boundary

One transaction per `GameCompleted` (casual) or `TournamentCompleted`:
1. `SELECT … FOR UPDATE` on each `elo_records` row for all players in the game/tournament.
2. Compute pairwise Elo deltas.
3. Update `casual_elo` / `tournament_elo`.
4. Insert `elo_deltas` rows (audit).
5. Insert `ranking_outbox` rows (`EloUpdated` events).
6. `COMMIT`.

Idempotency: before step 2, check `last_casual_game_id = game_id` (or `last_tournament_id`); if already applied, skip and return (no-op).

### 4.3 Supporting Store (Redis — leaderboard instance)

| Key | Purpose | TTL |
|---|---|---|
| `ranking:leaderboard:casual` | Sorted Set, score = casual Elo | No TTL (`noeviction` policy) |
| `ranking:leaderboard:tournament` | Sorted Set, score = tournament Elo | No TTL |

Updated via `ZADD` after each `COMMIT`. The leaderboard Redis instance uses `noeviction` — data must not be silently evicted.

### 4.4 Read Models

| Model | Store | Staleness |
|---|---|---|
| Leaderboard top-100 | Redis Sorted Set (`ZRANGE … REV`) | Seconds (updated after each game) |
| Player rank (`ZRANK`) | Redis Sorted Set | Same |
| Elo history | PostgreSQL `elo_deltas` | Consistent |

### 4.5 Retention and Audit

- `elo_records` are retained indefinitely (required for ranking).
- `elo_deltas` are retained indefinitely (dispute resolution, regulatory audit).
- On `GameResultVoided` or `TournamentCancelled`: `EloReverted` deltas are inserted as negative entries (append-only reversal, never delete prior rows).

---

## 5. Spectator View

### 5.1 Primary Store

**Dual-store:** Redis (hot read models) + PostgreSQL (sealed logs).

| Store | Data | Lifecycle |
|---|---|---|
| Redis Hash `spectator:gameview:<game_id>` | `PublicGameView` — current public state snapshot | Created on `GameStarted`; updated per event; deleted after `GameCompleted` + 24h buffer |
| Redis Hash `spectator:roomlist:<room_id>` | Active rooms list | Created on `RoomCreated`; updated on `RoomStatusChanged`; deleted on `RoomClosed` |
| Redis Stream `spectator:stream:<game_id>` | Privacy-filtered event stream for live WebSocket delivery | MAXLEN ~200; TTL = game duration + 24h |
| PostgreSQL `spectator` schema | `public_game_logs` (sealed, immutable after `GameCompleted`), `bracket_views` (persistent) | `public_game_logs` written once on `GameCompleted`; never modified |

### 5.2 Consistency Model

- Hot read models (Redis) are **eventually consistent**: consumer lag may be seconds.
- Sealed logs (PostgreSQL) are **strongly consistent** within the Spectator context: written transactionally on `GameCompleted`.
- No write-side access to Room Gameplay's schema.

### 5.3 Privacy Enforcement at Persistence Layer

The `spectator-game-consumer-worker` applies the privacy whitelist filter before any `XADD` or `HSET` call. The PostgreSQL `public_game_logs` table schema has no columns for hand card identities — they are structurally excluded from the persistence model.

### 5.4 Retention

- Redis hot models: TTL-bounded (game duration + 24h).
- `public_game_logs`: retained indefinitely for audit and replay.
- `bracket_views`: retained per tournament lifecycle + 1 year.

---

## 6. Analytics

### 6.1 Primary Store

**ClickHouse** (dedicated cluster, `analytics` database).

| Table | Purpose | Insert pattern |
|---|---|---|
| `game_events_raw` | Append-only raw event log: `game_id`, `event_type`, `player_id`, `tournament_id` (nullable), `payload` (JSON), `occurred_at`. | Batch INSERT every 500ms from consumer workers. |
| `game_results` | Flattened game outcomes: `game_id`, `winner_player_id`, `duration_seconds`, `player_count`, `game_type`, `tournament_id`, `round_id`. | Derived from `GameCompleted`; batch insert. |
| `player_stats_mv` | ClickHouse Materialized View: win rate, games played, cumulative points per `player_id`. | Maintained automatically on insert to `game_events_raw`. |
| `tournament_bracket_mv` | ClickHouse Materialized View: round-by-round advancement tree. | Updated as `MatchCompleted` events arrive. |

### 6.2 Consistency Model

**Eventual.** The analytics pipeline is a downstream read model with no influence on write-side consistency. At burst (100K `GameCompleted` at round end), ClickHouse batch inserts may lag seconds behind real-time; this is acceptable for analytics use cases.

### 6.3 Spike Absorption

- **Dedicated consumer group** (`analytics-game-cg`): isolated from Ranking, Spectator, and Tournament consumer groups. Kafka consumer lag in analytics does not affect other consumers.
- **Batch insert:** Workers buffer events for 500ms and issue a single ClickHouse `INSERT … VALUES (…)` with up to 1,000 rows. This amortizes ClickHouse write overhead across the burst.
- **20 consumer workers × 5 partitions each** for the `game-events` topic during peak round.

### 6.4 Retention

ClickHouse TTL: `game_events_raw` rows older than 2 years are dropped (configurable). `game_results` retained indefinitely. PII: `player_id` is a pseudonym; no email or personal data in analytics.

---

## 7. Moderation

### 7.1 Primary Store

**PostgreSQL** (dedicated schema: `moderation`).

| Table | Purpose | Consistency |
|---|---|---|
| `admin_actions` | Append-only audit log: `action_id`, `admin_id`, `action_type`, `target_entity_id`, `payload` (JSONB), `issued_at`. | Strong — written before any corrective command is issued. |
| `abuse_escalations` | Per-player escalation state: `player_id`, `violation_count`, `warning_count`, `last_violation_at`, `suspension_until`. | Strong |
| `moderation_outbox` | Transactional outbox for `moderation-events` Kafka topic. | Strong |

### 7.2 Write-Before-Effect Ordering

Every corrective action (VoidGameResult, CancelTournament, SuspendPlayer, BanPlayer) is written to `admin_actions` and `moderation_outbox` in the same PostgreSQL transaction **before** any downstream call (HTTP or Kafka). The downstream effect cannot precede the audit record.

### 7.3 Consistency Model

Strong within context. Downstream effects (Elo reversal, tournament cancellation) are eventual via Kafka events from `moderation_outbox`.

### 7.4 Retention

- `admin_actions` is retained indefinitely (regulatory audit; dispute resolution).
- `abuse_escalations` cleaned after 90 days of inactivity.

---

## 8. Why No Shared Database

Each bounded context has a different consistency requirement and a different data lifecycle:

| Context | Consistency need | Eviction / lifecycle |
|---|---|---|
| Room Gameplay | Per-game row lock; high write throughput | Game rows archived after 30 days |
| Tournament | Per-match row lock; moderate write | Retained per tournament lifecycle |
| Identity | Low write volume; strong (session token) | Retention per GDPR policy |
| Ranking | Moderate write; strong (Elo atomic) | Retained indefinitely |
| Spectator | High read; eventual | Hot data TTL-bounded; logs immutable |
| Analytics | Very high write burst; eventual | 2-year TTL on raw events |
| Moderation | Low write; audit-critical | Indefinite |

A shared database would couple schema migrations across all contexts, force a single eviction policy, and create cross-context query paths that bypass the domain model's invariants. Each context's schema is owned exclusively by that context's service and evolved independently.
