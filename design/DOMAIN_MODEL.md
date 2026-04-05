# UnoArena — Domain Model

This document defines the aggregates, entities, and value objects of the UnoArena domain, along with the key invariants each aggregate must enforce. All terms follow [GLOSSARY.md](./GLOSSARY.md). Context ownership follows [CONTEXT_MAP.md](./CONTEXT_MAP.md).

---

## 1. Aggregates

An aggregate is a cluster of domain objects treated as a single unit of consistency. All state changes within an aggregate are atomic. Cross-aggregate interactions happen exclusively through domain events.

### 1.1 GameSession
**Owned by:** Room Gameplay context

The authoritative owner of all in-game state for a single game. This is the most behavior-rich aggregate in the domain.

**State:**
- `game_id` — unique identifier
- `room_id` — the room this game belongs to
- `state_version` — monotonically increasing integer; increments on every accepted state change
- `status` — `initializing` | `in_progress` | `completed`
- `deck` — ordered list of all 108 cards (draw pile + dealt hands combined at init)
- `draw_pile` — ordered face-down card stack
- `discard_pile` — ordered face-up card stack; top card defines active color and rank/symbol
- `active_color` — current color governing legal plays (may differ from top card's color after a Wild)
- `players` — ordered list of `PlayerHand` entities (in turn order)
- `turn_index` — pointer into the players list; whose turn it is
- `direction` — `clockwise` | `counterclockwise`
- `active_stack_penalty` — accumulated Draw Two penalty (0 when no stack is active)
- `challenge_window` — optional `ChallengeWindow` value object (null when no window is open)
- `afk_counters` — map of player_id → consecutive expired turn count

**Key invariants:**
1. `state_version` is strictly monotonic; no two accepted commands produce the same version.
2. Only the player at `turn_index` may submit a play-card or draw-card command (except jump-in, which is out-of-turn).
3. A played card must pass legal play validation against the current `active_color` and top of `discard_pile`.
4. A Wild Draw Four may only be played if the player holds no cards matching `active_color` (Wilds in hand do not count).
5. Jump-in is only valid if the submitted card is identical (color + rank/symbol) to the top of `discard_pile`, and the submitter is not the player who just played that card.
6. At most one Uno! challenge and one Wild Draw Four challenge may be open simultaneously (the combined window).
7. When a challenge window is open, only the eligible challenger(s) may submit challenge actions.
8. The game ends immediately when any player's hand reaches zero cards.
9. A forfeited player's hand is discarded; they are removed from `players`; turn order adjusts around them.
10. If a forfeit leaves 0 active players, the game is voided (no scores, no Elo).
11. If a forfeit leaves 1 active player, that player wins immediately.
12. All random outcomes (shuffle, deal, draw) are generated server-side and appended to the event log before being broadcast.

---

### 1.2 Room
**Owned by:** Room Gameplay context

The lifecycle container for a group of players. Governs lobby logic, player membership, and the transition into an active game.

**State:**
- `room_id` — unique identifier
- `room_type` — `casual` | `tournament`
- `status` — `waiting` | `lobby` | `in_progress` | `completed`
- `players` — list of `RoomPlayer` entities (active players registered in the room)
- `spectators` — list of player IDs (no cap)
- `lobby_timer_start` — timestamp when the countdown began (null if not yet started)
- `current_game_id` — ID of the active `GameSession` (null if no game running)
- `tournament_room_ref` — optional reference to the `TournamentRoom` entity (null for casual rooms)

**Key invariants:**
1. A room may hold 2 to 10 active players.
2. The lobby countdown does not start until at least 5 players are present.
3. If the room reaches 10 players, the timer is reduced to 10 seconds (if more than 10 seconds remain).
4. A game starts only when the lobby timer expires with at least 2 active players present.
5. If the timer expires with fewer than 2 players, the room is cancelled.
6. No player may join as an active player once the room is `in_progress`.
7. A player may not be an active player in more than one room simultaneously (enforced in coordination with Identity/Session).
8. State transitions are one-way: `waiting → lobby → in_progress → completed`. No rollback.

---

### 1.3 Match
**Owned by:** Tournament Orchestration context

Tracks the Best-of-Three series played within a single tournament room. Coordinates game sequencing, match win accounting, early-end detection, and timeout.

**State:**
- `match_id` — unique identifier
- `room_id` — the tournament room this match runs in
- `tournament_id` / `round_number` — lineage reference
- `status` — `in_progress` | `completed` | `timed_out`
- `games` — ordered list of `MatchGame` entities (up to 3)
- `match_standings` — map of player_id → `MatchStanding` value object
- `timeout_deadline` — absolute timestamp (match start + 20 minutes)
- `active_game_id` — ID of the currently running `GameSession` (null between games)

**Key invariants:**
1. A match contains at most 3 games.
2. The match ends immediately when any player reaches `match_wins = 2` (early end).
3. If no player reaches 2 wins after Game 2, Game 3 is always played.
4. When `timeout_deadline` is reached during an active game, that game is resolved immediately using current hands (highest score → fewest cards → random); the match then ends.
5. Match standings are recomputed after every completed game; `match_wins`, `cumulative_card_point_burden`, and `cumulative_cards_remaining` are always consistent with completed game results.
6. A forfeited player's `match_standing` is frozen at the time of forfeit; they rank below all non-forfeited players regardless of standing.
7. If forfeits reduce active players to 1, remaining games are not played; that player wins the match unconditionally.

---

### 1.4 TournamentRound
**Owned by:** Tournament Orchestration context

Represents one elimination tier within a tournament. Manages the qualifier pool for the round, room formation, phase-start thresholds, and advancement tracking.

**State:**
- `tournament_id`
- `round_number` — 1-indexed
- `status` — `pending` | `forming` | `in_progress` | `completed`
- `expected_qualifiers` — computed from previous round
- `qualifier_pool` — list of player IDs eligible to be placed into rooms
- `rooms` — list of `TournamentRoom` entities for this round
- `qualifiers_for_next_round` — list of player IDs who advanced
- `phase_start_threshold` — minimum qualifiers needed before room formation begins

**Key invariants:**
1. Room formation does not begin until `qualifier_pool.size ≥ phase_start_threshold`.
2. Rooms target 10 players; minimum 2 to start.
3. A player appears in at most one room per round.
4. A lone qualifier (cannot be paired) auto-advances without playing.
5. The round is `completed` only when all rooms have resolved advancement.
6. Players not present in their assigned lobby when the timer starts are forfeited before the game begins.

---

### 1.5 Tournament
**Owned by:** Tournament Orchestration context

The top-level aggregate governing the full tournament lifecycle, from registration through champion declaration.

**State:**
- `tournament_id`
- `status` — `registration_open` | `registration_closed` | `in_progress` | `completed` | `cancelled`
- `registered_players` — list of player IDs
- `confirmed_players` — players present at start time
- `total_rounds` — computed at start: `ceil(log(confirmed_players / 10) / log(10/3))`
- `current_round` — reference to the active `TournamentRound`
- `champion_id` — player ID of the Tournament Champion (null until completed)
- `created_by` — admin ID

**Key invariants:**
1. A tournament does not start if `confirmed_players < 1,000`.
2. `total_rounds` is computed once at start and does not change mid-tournament.
3. A player may only participate in one tournament at a time.
4. If the tournament is `cancelled`, no Elo changes are applied for any game played within it.
5. The Final Room is created when the active player count drops to ≤ 10 after a round concludes.
6. The `champion_id` is set exactly once, when the Final Room's match completes.

---

### 1.6 PlayerProfile
**Owned by:** Identity/Session context

The persistent player record. Owns identity, region, Elo ratings, and statistics.

**State:**
- `player_id` — unique identifier
- `username` — unique, immutable after registration
- `region` — home region; self-selected at registration; immutable after 30 days without admin review
- `casual_elo` — `EloRating` value object (starts at 1,000)
- `tournament_elo` — `EloRating` value object (starts at 1,000)
- `stats` — `PlayerStats` value object: games played, win rate, cumulative points, tournaments won
- `status` — `active` | `suspended` | `banned`

**Key invariants:**
1. `username` is globally unique.
2. `casual_elo` is updated only after completed casual games; never after voided games or tournament games.
3. `tournament_elo` is updated only once after a full tournament concludes; never mid-tournament.
4. A banned player may not log in or participate in any room or tournament.
5. A suspended player's active session is invalidated; participation resumes after the cooldown expires.

---

### 1.7 PlayerSession
**Owned by:** Identity/Session context

Manages the single active session per player, JWT validity, and reconnection window state.

**State:**
- `player_id`
- `valid_sessions_from` — timestamp; tokens issued before this timestamp are invalid
- `current_jwt_issued_at` — timestamp of the currently valid JWT
- `reconnection_window` — optional `ReconnectionWindow` value object (null when player is connected or not in a game)
- `latency_profile` — `LatencyProfile` value object; updated by the server on each heartbeat exchange; governs effective submission time computation for race resolution

**Key invariants:**
1. At most one session is valid per player at any time.
2. A new login sets `valid_sessions_from` to the current timestamp, invalidating all prior tokens.
3. When a session is invalidated while the player is in an active game, a `ReconnectionWindow` (60s) is created immediately.
4. If the `ReconnectionWindow` expires without reconnection, a forfeit is automatically issued for the player's active game(s).
5. Reconnection is complete only when the session is re-established **and** game state is fully synchronized.

---

## 2. Entities

Entities have identity but live within an aggregate's consistency boundary.

| Entity | Lives within | Key fields | Purpose |
|---|---|---|---|
| `PlayerHand` | `GameSession` | `player_id`, `cards: List<Card>`, `uno_declared: bool`, `connected: bool` | Tracks a player's private hand and state within a game |
| `RoomPlayer` | `Room` | `player_id`, `joined_at`, `status: active\|forfeited` | Tracks a player's membership and status within a room |
| `MatchGame` | `Match` | `game_id`, `sequence_number` (1–3), `status`, `placements: List<GamePlacement>` | Records the result of one game within a Bo3 match |
| `TournamentRoom` | `TournamentRound` | `room_id`, `player_ids`, `match_id`, `advancement_result` | Links a physical room and its match result to a tournament round |

---

## 3. Value Objects

Value objects have no identity; they are defined entirely by their attributes and are immutable.

| Value Object | Fields | Used by | Notes |
|---|---|---|---|
| `Card` | `color: Red\|Green\|Blue\|Yellow\|None`, `type: Number\|Skip\|Reverse\|DrawTwo\|Wild\|WildDrawFour`, `value: 0–9\|20\|50` | `GameSession`, `PlayerHand` | Immutable; two cards are equal iff all fields match |
| `TurnState` | `current_player_id`, `direction`, `active_color`, `state_version` | `GameSession` | Snapshot of turn context for a given state version |
| `ChallengeWindow` | `type: Uno\|WildDrawFour\|Combined`, `opened_at`, `duration_ms`, `paused_remaining_ms`, `uno_eligible_challengers: List<player_id>` *(all opponents; populated on Uno and Combined)*, `wd4_eligible_challenger: player_id` *(next player in turn order; populated on WD4 and Combined only)* | `GameSession` | Encapsulates timer logic for all challenge window types; supports pause/resume for the combined window. The two eligibility fields are mutually exclusive in a pure Uno or WD4 window, but both are populated on a Combined window — each controls who may issue which specific challenge command. |
| `MatchStanding` | `player_id`, `match_wins`, `cumulative_card_point_burden`, `cumulative_cards_remaining`, `forfeited: bool`, `forfeit_timestamp` | `Match` | Complete data needed to determine room placement and advancement; fully reproducible from completed game results |
| `GamePlacement` | `player_id`, `rank`, `game_score`, `cards_remaining` | `MatchGame`, `GameSession` | Final result for one player in one game |
| `Placement` | `player_id`, `rank`, `scope: game\|room\|tournament` | `GameSession`, `Match`, `Tournament` | Scoped ranking result; scope disambiguates usage |
| `EloRating` | `value`, `games_played`, `k_factor_tier: provisional\|established\|veteran` | `PlayerProfile` | K-factor tier derived from `games_played`: <20 → 32, 20–99 → 16, 100+ → 12 (casual); always 40 (tournament) |
| `PlayerStats` | `games_played`, `casual_wins`, `cumulative_points`, `tournaments_won` | `PlayerProfile` | Aggregate statistics for the player's public profile |
| `StateVersion` | `value: int` | `GameSession` | Monotonically increasing; compared on every command to enforce optimistic concurrency |
| `IdempotencyKey` | `uuid` | All commands | Client-generated UUID; server stores result keyed by this value for at-least-once safety |
| `ReconnectionWindow` | `player_id`, `started_at`, `expires_at`, `game_id` | `PlayerSession` | 60-second server-tracked window; expiry triggers automatic forfeit |
| `TimerWindow` | `type: TurnTimer\|ChallengeWindow\|ReconnectionWindow`, `started_at`, `duration_ms`, `expired: bool` | `GameSession`, `PlayerSession` | Generic timer; all timers are server-generated and server-enforced |
| `Region` | `region_id`, `name` | `PlayerProfile` | One of 11 defined regions; governs matchmaking priority |
| `AbuseRecord` | `player_id`, `violations: List<Violation>`, `warnings_issued`, `suspensions_in_7_days` | `PlayerSession` (via Moderation) | Tracks escalation state for rate-limit abuse |
| `LatencyProfile` | `rolling_rtt_ms: float`, `sample_count: int`, `last_measured_at: timestamp`, `measurement_available: bool` | `PlayerSession` | Server-measured rolling RTT average (not client-reported). Used to compute `effective_submission_time = arrival_time − RTT/2` for race resolution. `measurement_available` is false until at least one heartbeat exchange completes. |

---

## 4. Aggregate Interaction Map

Aggregates never call each other directly. They interact only through domain events, which cross context boundaries asynchronously.

```
PlayerSession ──SessionInvalidated──▶ Room (reconnection window starts)
                                            │
                              PlayerForfeited│
                                            ▼
GameSession ──GameCompleted──────────────▶ Match (match win credited, standings updated)
                │                               │
                │                     MatchCompleted
                │                               ▼
                │                    TournamentRound (qualifiers resolved)
                │                               │
                │                    TournamentCompleted
                │                               ▼
                └──GameCompleted──────────────▶ Ranking (Elo updated)
                                               ▲
                                    TournamentCompleted
                                    (from TournamentRound)
```

---

## 5. Spectator View Read Models

Spectator View is a projection context — it owns no aggregates. Its DDD artifacts are **read models** built by consuming and filtering events from Room Gameplay and Tournament Orchestration. All read models are eventually consistent with their source aggregates.

| Read Model | Built from events | Fields exposed | Fields withheld |
|---|---|---|---|
| `PublicGameView` | `GameStarted`, `CardPlayed`, `CardDrawn`, `TurnAdvanced`, `DirectionReversed`, `PlayerSkipped`, `PenaltyApplied`, `UnoCallMade`, `UnoChallengeResolved`, `WildDrawFourPlayed`, `WildDrawFourChallengeResolved`, `PlayerDisconnected`, `PlayerReconnected`, `PlayerForfeited`, `GameCompleted` | Player names, hand counts (per player), discard pile (full history + top card), draw pile size, turn order, current direction, active color, current player, scores, all game events | Card identities in any player's hand; WD4 accused player's hand composition (until post-game) |
| `PublicGameLog` | All `GameCompleted` events + full event history | Everything in `PublicGameView` plus: card identities for all draws and plays, WD4 accused hand composition, final standings | Nothing — full log is public post-game |
| `BracketView` | `RoundStarted`, `TournamentRoomAssigned`, `MatchStarted`, `MatchCompleted`, `AdvancementResolved`, `TournamentCompleted` | Tournament structure, round number, room assignments (player names), match status, qualifier results per room, current round progress | Individual game scores mid-match (only final match standings are shown) |
| `SpectatorRoomList` | `RoomCreated`, `RoomStatusChanged`, `PlayerJoinedRoom`, `GameStarted`, `GameCompleted` | Room ID, room type, status, player count, spectator count | Player hand information |
| `LeaderboardView` | `EloUpdated` (from Ranking context) | Player name, region, casual Elo, tournament Elo, rank position | Internal K-factor tier, raw game statistics |

**Key projection rules:**
- `PublicGameView` is updated in near real-time as events arrive; it is the live feed for active spectators.
- `PublicGameLog` is sealed and immutable once `GameCompleted` is processed; it becomes the post-game audit record.
- `BracketView` updates progressively as rooms complete within a round; it does not wait for the full round to finish.
- All read models apply the Spectator View anti-corruption layer: any field not on the explicit whitelist is dropped before storage or broadcast.

---

## 6. Consistency Boundary Summary

| Aggregate | Consistency guarantee | Cross-boundary mechanism |
|---|---|---|
| `GameSession` | Strong consistency within a single game via `state_version` and optimistic concurrency | Emits domain events; no direct calls to other aggregates |
| `Room` | Strong consistency for lifecycle transitions | Emits `RoomStatusChanged`; reacts to `GameCompleted` |
| `Match` | Strong consistency for Bo3 standing and match end detection | Reacts to `GameCompleted`; emits `MatchCompleted` |
| `TournamentRound` | Eventual consistency — rooms complete at different times; advancement accumulates | Reacts to `MatchCompleted`; emits `RoundCompleted` when all rooms resolved |
| `Tournament` | Eventual consistency — rounds complete sequentially | Reacts to `RoundCompleted`; emits `TournamentCompleted` |
| `PlayerProfile` | Strong consistency for Elo updates (one update per completed game or tournament) | Reacts to `GameCompleted` (casual Elo) and `TournamentCompleted` (tournament Elo) |
| `PlayerSession` | Strong consistency for single-session invariant | Emits `SessionInvalidated`; reacts to login commands |
