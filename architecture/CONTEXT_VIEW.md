# UnoArena — Context View

This document maps the seven bounded contexts from the DDD design to their deployable services, states what each context owns vs. delegates, and shows the updated context map including cross-cutting infrastructure components.

All terms follow [GLOSSARY.md](../design/GLOSSARY.md). Bounded context definitions follow [CONTEXT_MAP.md](../design/CONTEXT_MAP.md).

---

## 1. Updated Context Map

```
                ┌──────────────────────────────────────────────────────────────────┐
                │                       API Gateway                                │
                │  • Terminates all WebSocket + REST connections                   │
                │  • JWT validation via valid_sessions_from (Redis cache-aside)     │
                │  • Per-IP + per-user rate limiting (Redis)                       │
                │  • Routes commands to downstream services                        │
                │  • Subscribes to Redis Pub/Sub: session:invalidated:*            │
                │    → closes old WebSocket connections on session invalidation     │
                └────────────────────────────┬─────────────────────────────────────┘
                                             │ routes to
            ┌────────────────────────────────┼───────────────────────────────────┐
            │                                │                                   │
            ▼                                ▼                                   ▼
┌───────────────────────┐      ┌─────────────────────────┐        ┌────────────────────────┐
│  Identity / Session   │      │     Room Gameplay        │        │ Tournament Orchestration│
│  (upstream to all)    │      │  (upstream core;         │        │ (round logic, Bo3       │
│                       │      │   game state owner)      │        │  match tracking)        │
│  PlayerProfile        │      │                          │        │                         │
│  PlayerSession        │      │  GameSession             │        │  Tournament             │
│                       │      │  Room                    │        │  TournamentRound        │
│  ──publishes──▶       │      │  MatchmakingQueue        │        │  Match                  │
│  PlayerRegistered     │      │                          │        │                         │
│  SessionCreated       │      │  ──publishes──▶          │        │  ──publishes──▶         │
│  SessionInvalidated   │◀─────│  game-events topic       │◀───────│  tournament-events topic│
│  PlayerSuspended      │      │  (Kafka)                 │        │  (Kafka)                │
│  PlayerBanned         │      │                          │        │                         │
│  ReconnectionWindow   │      │  ──outbox relay──▶       │        │  ──creates rooms in──▶  │
│  events               │      │  Kafka broker            │        │  Room Gameplay          │
└───────────────────────┘      └──────────────────────────┘        └─────────────────────────┘
            │                                │                                   │
            │  identity-events (Kafka)       │  game-events (Kafka)              │  tournament-events (Kafka)
            │                                │                                   │
            ▼                                ▼                                   ▼
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│                                      Kafka Broker                                          │
│  Topics: game-events, tournament-events, identity-events, ranking-events                  │
│  Partitioned by game_id / room_id / player_id for per-entity ordering                     │
└──────────────────────────┬───────────────────────────────────────────────────┬────────────┘
                           │                                                   │
           ┌───────────────┴────────────────────────────┐                     │
           │               │                            │                     │
           ▼               ▼                            ▼                     ▼
┌──────────────────┐ ┌──────────────────┐ ┌────────────────────┐ ┌──────────────────────┐
│  Spectator View  │ │     Ranking      │ │   Analytics /      │ │   Moderation /       │
│  (read-only;     │ │  (Elo authority) │ │   Read Models      │ │   Admin              │
│   privacy ACL)   │ │                  │ │   (read-only)      │ │   (audit log;        │
│                  │ │  EloRecord       │ │                    │ │    corrective cmds)  │
│  PublicGameView  │ │  Leaderboard     │ │  Player stats      │ │                      │
│  PublicGameLog   │ │                  │ │  Bracket views     │ │  AdminAction         │
│  BracketView     │ │  ──publishes──▶  │ │  Standings         │ │  (audit log)         │
│  SpectatorRoom   │ │  ranking-events  │ │  Leaderboard       │ │                      │
│  List            │ │  (Kafka)         │ │  display copies    │ │  ──issues cmds──▶    │
│  LeaderboardView │ │                  │ │                    │ │  upstream contexts   │
└──────────────────┘ └──────────────────┘ └────────────────────┘ └──────────────────────┘
```

**Cross-cutting infrastructure (not owned by any context):**

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  Redis (logical databases / instances)                                               │
│                                                                                      │
│  Cache DB:       valid_sessions_from (Cache-Aside), idempotency keys               │
│  Timer DB:       turn timers, challenge windows, reconnection windows, match timeout│
│  Pub/Sub:        session:invalidated:<player_id> channel                            │
│  Leaderboard DB: ranking:leaderboard:casual / :tournament (noeviction policy)      │
│  Session DB:     AFK counters, distributed locks (lobby, match start)              │
│  Spectator DB:   PublicGameView hash, SpectatorRoomList hash                       │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Context → Service Mapping

| Bounded Context | Deployable Service(s) | Notes |
|---|---|---|
| Identity / Session | `identity-service` | Single service; owns `PlayerProfile`, `PlayerSession` aggregates. Writes `valid_sessions_from` to PostgreSQL and Redis. |
| Room Gameplay | `room-gameplay-service` + `outbox-relay-worker` | Two processes in one deployable unit. The relay worker is an internal process — not a separate service. Shares the same PostgreSQL instance/schema. |
| Tournament Orchestration | `tournament-service` | Single service (decision O2). Owns `Tournament`, `TournamentRound`, `Match` aggregates. Drives room-creation fan-out. |
| Ranking | `ranking-service` | Single service. Pure event consumer + writer. No client-facing commands. |
| Spectator View | `spectator-service` | Single service. Pure projection consumer. Holds WebSocket connections for spectators (routed via API Gateway). |
| Analytics / Read Models | `analytics-service` + `analytics-worker` (N instances) | Analytics workers are dedicated partitioned consumers for burst absorption. The service exposes read-only query APIs. |
| Moderation / Admin | `moderation-service` | Single service. Low-traffic, high-privilege admin interface. |
| Cross-cutting | `api-gateway` | Routes REST and WebSocket traffic. Enforces JWT + rate limiting. Owns session-invalidation push path. |

---

## 3. What Each Context Owns vs. Delegates

### 3.1 Identity / Session
**Owns:** Player profiles, password hashes, JWTs, `valid_sessions_from` timestamp, reconnection window tracking.

**Delegates:**
- Elo ratings → Ranking context
- Game state during disconnection → Room Gameplay context
- Abuse escalation to ban → Moderation context

**Published language consumed by all contexts:** `player_id`, JWT claims, `PlayerRegistered`, `SessionInvalidated`, `PlayerSuspended`, `PlayerBanned`.

---

### 3.2 Room Gameplay
**Owns:** All in-game state (`GameSession`), room lifecycle (`Room`), casual matchmaking queue (`MatchmakingQueue`), immutable game log, turn timers, challenge windows.

**Delegates:**
- Player identity validation → API Gateway (JWT) / Identity context
- Tournament progression → Tournament Orchestration (reacts to `GameCompleted`)
- Elo calculation → Ranking context
- Spectator filtering → Spectator View context
- Reconnection window timer ownership → Identity/Session context

**Key constraint:** Room Gameplay only knows it received a `PlayerDisconnected` and a subsequent `ReconnectionWindowExpired`; it does not own or track the 60-second window itself.

---

### 3.3 Tournament Orchestration
**Owns:** Tournament lifecycle, round sequencing, room assignment, Bo3 match state (`match_wins`, game sequence), match timeout, advancement decisions, tie-break resolution.

**Delegates:**
- Individual game execution → Room Gameplay (creates rooms, receives `GameCompleted` back)
- Tournament Elo → Ranking context
- Bracket display → Spectator View / Analytics

**Key constraint:** Tournament Orchestration issues `CreateRoom` + `AssignPlayersToRoom` commands to Room Gameplay during the round-kickoff surge. Room IDs are pre-determined by Tournament Orchestration using a deterministic scheme (`tournament_id + round_number + room_index`) to enable idempotent retries.

---

### 3.4 Ranking
**Owns:** `EloRecord` aggregate (one per player), casual leaderboard, tournament leaderboard.

**Delegates:**
- Game results → Room Gameplay (consumes `GameCompleted`)
- Tournament results → Tournament Orchestration (consumes `TournamentCompleted`)
- Leaderboard display copies → Analytics (pushes `EloUpdated`)

**Key constraint:** Ranking applies Elo only for completed casual games. Tournament Elo is applied once per tournament at `TournamentCompleted`. No Elo for abandoned games (those where all active players forfeited or the game was admin-voided).

---

### 3.5 Spectator View
**Owns:** `PublicGameView` (live), `PublicGameLog` (sealed post-game), `BracketView`, `SpectatorRoomList`, `LeaderboardView` read models.

**Delegates:** Nothing — this context is purely a read-side projection. It consumes events and serves queries/streams; it never issues commands or writes to other contexts.

**Key constraint:** The privacy whitelist filter is applied at event consumption, before any data is written to read models. The read model itself never contains hand data — even `PublicGameLog` withholds `WildDrawFourChallengeResolved.accused_hand_at_time` until post-game seal.

---

### 3.6 Analytics / Read Models
**Owns:** Player statistics, tournament bracket trees, round-by-round standings, historical game lists, leaderboard display views (display copy only — authoritative Elo remains in Ranking).

**Delegates:** Nothing — purely read-side. All writes are driven by incoming Kafka events.

**Key constraint:** Analytics consumer groups are separate from all other consumers of the same Kafka topics. Analytics lag does not affect Room Gameplay writers, Ranking updates, or Tournament Orchestration processing.

---

### 3.7 Moderation / Admin
**Owns:** `AdminAction` aggregate, audit log. Issues corrective commands to upstream contexts but does not own the state those commands modify.

**Delegates:**
- Game state changes → Room Gameplay (via `VoidGameResult`)
- Tournament cancellation → Tournament Orchestration (via `CancelTournament`)
- Player suspension/ban → Identity/Session (via `SuspendPlayer` / `BanPlayer` sync call)
- Elo reversal → Ranking (via `GameResultVoided` / `TournamentCancelled` events)

---

## 4. Context Relationship Summary

| Relationship | Type | Integration mechanism |
|---|---|---|
| Identity/Session → All contexts | Upstream / Published Language | JWT claims (sync); `identity-events` Kafka topic (async) |
| Room Gameplay → Spectator View | Published Language + ACL | `game-events` Kafka topic; Spectator applies whitelist filter |
| Room Gameplay → Ranking | Published Language | `game-events` Kafka topic; `GameCompleted` event |
| Room Gameplay → Tournament Orchestration | Partnership | `game-events` Kafka topic; Tournament creates rooms via HTTP commands to Room Gameplay |
| Room Gameplay → Analytics | Published Language | `game-events` Kafka topic; dedicated consumer group |
| Tournament Orchestration → Ranking | Published Language | `tournament-events` Kafka topic; `TournamentCompleted` event |
| Tournament Orchestration → Spectator View | Published Language | `tournament-events` Kafka topic; bracket and match events |
| Tournament Orchestration → Analytics | Published Language | `tournament-events` Kafka topic; dedicated consumer group |
| Ranking → Analytics | Published Language | `ranking-events` Kafka topic; `EloUpdated` / `TournamentEloUpdated` |
| Moderation → All upstream | Downstream Observer + Corrective | Sync HTTP (SuspendPlayer); Kafka events (GameResultVoided, TournamentCancelled) |
| API Gateway → Identity/Session | Cache-Aside | Redis `identity:vsf:<player_id>`; fallback HTTP on cache miss |
| Identity/Session → API Gateway | Redis Pub/Sub push | `session:invalidated:<player_id>` channel → Gateway closes WebSocket |
