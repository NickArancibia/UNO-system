# Ranking Service

**Bounded context:** Ranking  
**Status:** Phase 5  
**Dependencies:** [PLAN.md](../PLAN.md) resolved decisions R3, R6; [CAPACITY_SKETCH.md](../CAPACITY_SKETCH.md); [design/DOMAIN_MODEL.md](../../design/DOMAIN_MODEL.md) §1.9; [design/COMMANDS_EVENTS.md](../../design/COMMANDS_EVENTS.md); [specs/CONSTRAINTS.md](../../specs/CONSTRAINTS.md) §5.2

---

## 1. Purpose and Scope

Ranking owns the `EloRecord` aggregate — the authoritative source of player Elo ratings. It consumes game and tournament completion events, computes Elo deltas, and publishes ranking update events.

**Owns:**
- `EloRecord` aggregate — one row per player; casual Elo updated per `GameCompleted`, tournament Elo updated per `TournamentCompleted`
- Casual leaderboard (`ranking:leaderboard:casual` — Redis Sorted Set)
- Tournament leaderboard (`ranking:leaderboard:tournament` — Redis Sorted Set)

**Does NOT own:**
- Game state or game outcomes (owned by Room Gameplay)
- Tournament lifecycle state (owned by Tournament Orchestration)
- Player identity (owned by Identity/Session)
- Elo display copies served to spectators and analytics (those are read models in Spectator View and Analytics)

**Key constraints:**
1. Casual Elo is applied per `GameCompleted` (game_type = `casual`) only. Tournament games (`game_type = tournament`) do **not** trigger casual Elo updates.
2. Tournament Elo is applied once per `TournamentCompleted`; never mid-tournament.
3. Abandoned casual games (where all remaining active players forfeited) do **not** trigger Elo updates — no winner was determined.
4. Forfeiting players who are **not** the entire field are assigned rank N (last place) before delta computation — no special case needed.
5. On `GameResultVoided`, the Elo delta from that game is reversed atomically; reversal is idempotent, keyed by `game_id`.
6. On `TournamentCancelled`, all Elo deltas accrued within that tournament are reversed; reversal is idempotent, keyed by `tournament_id`.

---

## 2. Containers

| Container | Type | Responsibility |
|---|---|---|
| `ranking-service` | Long-running service (JVM or Go) | Consumes game and tournament events, computes Elo, updates PostgreSQL and Redis leaderboards |
| `ranking-game-consumer-worker` | In-process background thread | Consumes `game-events` Kafka topic (consumer group `ranking-cg`) for `GameCompleted` |
| `ranking-tournament-consumer-worker` | In-process background thread | Consumes `tournament-events` Kafka topic (consumer group `ranking-tournament-cg`) for `TournamentCompleted`, `TournamentCancelled` |
| `ranking-moderation-consumer-worker` | In-process background thread | Consumes `moderation-events` Kafka topic (consumer group `ranking-moderation-cg`) for `GameResultVoided` |
| `ranking-outbox-relay-worker` | In-process background thread | Reads undelivered outbox rows, publishes to `ranking-events` Kafka topic, marks rows delivered |

All five run in the same deployed container.

---

## 3. Public Synchronous Interfaces

Ranking has no client-facing synchronous endpoints. All data is served to downstream consumers (Spectator View, Analytics) via Kafka events, and to players via the Spectator View or Analytics read model APIs.

Internal query (for admin/debugging only):

| Query | Method + Path | Notes |
|---|---|---|
| Get player Elo | `GET /v1/internal/ranking/players/{player_id}` | Returns `{player_id, casual_elo, tournament_elo}`. mTLS required. |

---

## 4. Public Asynchronous Interfaces

### 4.1 Events Produced on `ranking-events` topic

**Partitioned by:** `player_id`  
**Produced via:** transactional outbox relay  
**Schema version:** `schema_version: 1` on all events

| Event | Idempotency key | Primary consumers |
|---|---|---|
| `EloUpdated` | `player_id + game_id` | Spectator View (leaderboard), Analytics |
| `TournamentEloUpdated` | `player_id + tournament_id` | Spectator View (leaderboard), Analytics |
| `EloReverted` | `player_id + game_id` (casual) or `player_id + tournament_id` (tournament) | Spectator View, Analytics |

### 4.2 Events Consumed from `game-events`

Consumer group: `ranking-cg`  
Topic partitioned by `game_id`; 100 partitions; 20 consumer instances.

| Event | Idempotency key | Action |
|---|---|---|
| `GameCompleted` | `game_id` | If `game_type = 'casual'` AND `outcome = 'completed'`: compute casual Elo delta for all players (forfeited players receive rank N — last place). If `game_type = 'casual'` AND `outcome = 'abandoned'`: skip Elo entirely (no winner was determined). Tournament games (`game_type = 'tournament'`) do **not** trigger casual Elo updates regardless of `outcome`. |
| `GameResultVoided` | `game_id` | Reverse the Elo delta applied for this game. Emit one `EloReverted` per affected player. Idempotent: if `game_id` was already reversed, skip. |
| `PlayerRegistered` | `player_id` | Initialize `EloRecord` with starting Elo (1,000) for the new player. |

### 4.3 Events Consumed from `tournament-events`

Consumer group: `ranking-tournament-cg`

| Event | Idempotency key | Action |
|---|---|---|
| `TournamentCompleted` | `tournament_id` | Compute tournament Elo for all players in the tournament: each player's `tournament_elo` is updated based on their final placement. Emit `TournamentEloUpdated` per player. |
| `TournamentCancelled` | `tournament_id` | Reverse any Elo updates already applied for this tournament. Emit `EloReverted` per affected player (idempotent by `tournament_id`). |

### 4.4 Events Consumed from `moderation-events`

Consumer group: `ranking-moderation-cg`

| Event | Idempotency key | Action |
|---|---|---|
| `GameResultVoided` | `game_id` | Reverse the Elo delta applied for this game. Look up original delta from `elo_processing_log`. Emit `EloReverted` per affected player. Skip if `game_id` already flagged as voided. |

---

## 5. Elo Computation

### 5.1 Casual Elo

Placement-based multi-player Elo, per [`specs/CONSTRAINTS.md`](../../specs/CONSTRAINTS.md) §5.2.

**Step 1 — Ranking:**

Forfeited players are assigned rank N (last place) regardless of their standing at the time of forfeit. The winner (rank 1) always has the fewest remaining points (0 points in standard UNO scoring). If all remaining active players forfeited (abandoned game), **no Elo update is applied**.

**Step 2 — Actual score:**

```
S_i = (N − rank_i) / (N − 1)
```

Where `N` is the total number of players in the game and `rank_i` is player i's placement (1 = winner, N = last).

**Step 3 — Expected score (pairwise):**

```
P(i beats j) = 1 / (1 + 10^((R_j − R_i) / 400))
E_i = [ Σ_{j≠i} P(i beats j) ] / (N − 1)
```

Each player's expected score is the average pairwise win probability against every other player, using their current casual Elo.

**Step 4 — Elo delta:**

```
ΔR_i = K × (S_i − E_i)
```

**K-factor tiers (casual):**

| Games played (casual) | K | Tier name |
|---|---|---|
| < 20 | 32 | Provisional |
| 20–99 | 16 | Established |
| 100+ | 12 | Veteran |

**Step 5 — Performance bonus:**

The Elo delta for a player whose absolute card-value deficit is ≤ 80% of the room's average absolute deficit (i.e., they performed at least 20% better than average) receives a +3 bonus. The winner (0 points) always qualifies as long as the room average is negative.

```
if |player_deficit| ≤ 0.8 × room_avg_absolute_deficit:
    ΔR_i += 3
```

**Abandoned games:** If `GameCompleted.outcome = 'abandoned'` (set by Room Gameplay when all remaining active players forfeited with no winner determined), **no Elo update is applied**. The `outcome` field is the authoritative signal; Ranking does not re-derive this from the `forfeited` list. This prevents exploitation via forced abandonment and prevents disconnected players from unfairly losing Elo.

**Forfeit-as-last-place:** A single forfeited player (or a subset of forfeited players) is assigned rank N (or N, N−1, ... for multiple forfeits) before the Elo formula is applied. No special logic is needed beyond assigning the lowest rank(s) — the formula handles it naturally.

**Concurrency:** All `EloRecord` rows for a game are locked in a single query (`SELECT FOR UPDATE WHERE player_id = ANY($1) ORDER BY player_id`) before any delta is computed. The `ORDER BY player_id` clause is mandatory: PostgreSQL acquires row locks in physical tuple order if the ORDER BY is omitted, which can differ between two concurrent transactions locking overlapping player sets and cause a deadlock. Sorting by `player_id` ascending gives a global, consistent acquisition order. This serializes Elo updates within a game but allows games with disjoint player sets to proceed concurrently.

### 5.2 Tournament Elo

Computed once per tournament at `TournamentCompleted`:

```
Tournament_Elo_new = Tournament_Elo_old + K_tournament × (W − E_expected)
```

Where:
- `K_tournament = 40` (higher K reflects tournament stakes).
- Only the final placement in the tournament bracket is used, not individual game outcomes.
- Tournament Elo (`tournament_elo` field) is a separate rating from casual Elo (`casual_elo` field). They never cross-contaminate.

**Reversal on cancellation:** `TournamentCancelled` triggers `EloReverted` for every player whose Elo was updated by the tournament. The reversal decrements by the exact delta previously applied (idempotent: if `EloReverted` for this `tournament_id` was already processed, it is a no-op). The `tournament_elo_applied` table tracks which tournaments have been processed to ensure exactly-once application.

### 5.3 Game Result Voiding

On `GameResultVoided` (consumed from `moderation-events`):

1. Look up the `game_id` in the processing log. If already voided → idempotent no-op.
2. For each player in the original game, reverse the casual Elo delta applied: `casual_elo = casual_elo − original_delta`.
3. Delete the corresponding `EloUpdated` entries from the processing log.
4. Emit `EloReverted` per affected player (idempotent by `game_id + player_id`).

This reversal is atomic within a single PostgreSQL transaction covering all affected `EloRecord` rows and the processing log update.

### 5.4 Burst Handling at Round End

At tournament round end, up to 100,000 `GameCompleted` events may arrive within ~60 seconds. Ranking processes these with 20 consumer instances (each owning ~5 partitions of the 100-partition `game-events` topic).

Each `GameCompleted` requires:
1. `SELECT FOR UPDATE` on `elo_records WHERE player_id = $1` for each player in the game (up to 10 players).
2. Compute deltas.
3. `UPDATE elo_records SET casual_elo = ... WHERE player_id = $1`.
4. `INSERT INTO ranking_outbox` (one `EloUpdated` event per player).
5. `COMMIT`.

At 100K games × ~5 players average = 500K row updates in 60 seconds ≈ 8,300 TPS. With row-level locking per player, the concurrent TPS is well within a single PostgreSQL instance's capacity (10K–30K TPS). The Kafka partition key (`player_id`) ensures per-player ordering but does NOT prevent concurrent updates to different players — these proceed in parallel.

**Optimization for burst:** The `ranking-game-consumer-worker` batches Elo updates for players that appear in multiple games within the same consumer poll cycle. If player P1 appears in 3 games in the same batch, their Elo updates are coalesced into a single UPDATE + single outbox row.

---

## 6. Persistence

### 6.1 PostgreSQL Schema (`ranking` schema)

```sql
CREATE TABLE elo_records (
    player_id           UUID PRIMARY KEY REFERENCES player_profiles(player_id),
    casual_elo          REAL NOT NULL DEFAULT 1000.0,
    tournament_elo      REAL NOT NULL DEFAULT 1000.0,
    casual_games_played  INTEGER NOT NULL DEFAULT 0,
    tournament_count     INTEGER NOT NULL DEFAULT 0,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ON elo_records (casual_elo DESC);
CREATE INDEX ON elo_records (tournament_elo DESC);

-- Tracks which games/tournaments have already been processed (idempotency for GameCompleted, GameResultVoided)
CREATE TABLE elo_processing_log (
    game_id             UUID NOT NULL,
    player_id           UUID NOT NULL,
    event_type          TEXT NOT NULL,     -- 'GameCompleted' | 'GameResultVoided'
    delta_applied       REAL NOT NULL,
    processed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (game_id, player_id)
);

-- Tracks which tournaments have already been processed (idempotency for TournamentCompleted, TournamentCancelled)
CREATE TABLE tournament_elo_applied (
    tournament_id   UUID PRIMARY KEY,
    applied_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ranking_outbox (
    id            BIGSERIAL PRIMARY KEY,
    player_id     UUID NOT NULL,
    event_type    TEXT NOT NULL,
    payload       JSONB NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered     BOOLEAN NOT NULL DEFAULT false,
    delivered_at  TIMESTAMPTZ
);

CREATE INDEX ON ranking_outbox (delivered, id) WHERE delivered = false;
```

**Consistency:** Strong per-player (row-lock on `EloRecord`). Eventually consistent across players (Elo updates for a single game are applied to each player independently). The `elo_processing_log` provides exactly-once processing guarantee: before applying any delta, the consumer checks whether `(game_id, player_id)` already exists in the log. If it does, the event is a duplicate and is skipped.

### 6.2 Redis Leaderboards

| Key | Type | Eviction policy | Update trigger |
|---|---|---|---|
| `ranking:leaderboard:casual` | Sorted Set | `noeviction` | `ZADD ranking:leaderboard:casual <elo> <player_id>` on `EloUpdated` |
| `ranking:leaderboard:tournament` | Sorted Set | `noeviction` | `ZADD ranking:leaderboard:tournament <elo> <player_id>` on `TournamentEloUpdated` |

**Sizing:** ~1M entries × ~60 bytes per entry ≈ 60 MB per sorted set. Well within a single Redis instance.

**Consistency:** Redis leaderboards are eventually consistent (updated after the PostgreSQL commit). They serve as fast read paths for Spectator View and Analytics queries. The authoritative Elo values are always in PostgreSQL.

---

## 7. Dependencies on Other Contexts

| Dependency | Direction | Mechanism | What is delegated |
|---|---|---|---|
| Room Gameplay | Inbound event | Consumes `game-events` Kafka topic: `GameCompleted` | Casual Elo computation trigger; game type and forfeited list determine Elo applicability |
| Tournament Orchestration | Inbound event | Consumes `tournament-events` Kafka topic: `TournamentCompleted`, `TournamentCancelled` | Tournament Elo computation and reversal |
| Moderation | Inbound event | Consumes `moderation-events` Kafka topic: `GameResultVoided` | Casual Elo reversal for voided game results |
| Identity/Session | Inbound event | Consumes `identity-events` Kafka topic: `PlayerRegistered` | Initialize `EloRecord` for new players |
| Spectator View | Outbound event | Produces `ranking-events` Kafka topic: `EloUpdated`, `TournamentEloUpdated`, `EloReverted` | Leaderboard display updates |
| Analytics | Outbound event | Same `ranking-events` topic | Player statistics, Elo history |

**Anti-corruption layer:** Ranking never queries Room Gameplay's PostgreSQL schema. All game data is derived from `GameCompleted` event payloads. The `forfeited` list and `game_type` field in the event are the sole signals for Elo applicability. Ranking never queries Moderation's audit log — `GameResultVoided` events carry the `game_id` needed for reversal.