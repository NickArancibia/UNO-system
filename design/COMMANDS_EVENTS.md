# UnoArena — Commands & Domain Events Catalog

This document is the authoritative behavioral contract for the UnoArena domain. It defines every command (intent to change state) and every domain event (record of a state change that occurred), with causality, preconditions, rejection reasons, and idempotency behavior. All terms follow [GLOSSARY.md](./GLOSSARY.md). Aggregate ownership follows [DOMAIN_MODEL.md](./DOMAIN_MODEL.md).

**Notation:**
- `[stale-version]` — command carries a `state_version` and is rejected with HTTP 409 if it does not match the server's current version.
- `[idempotent]` — command carries an `idempotency_key`; duplicate submissions return the original outcome without reprocessing.
- `→` — causes / produces

---

## 1. Command Catalog

### 1.1 Room Gameplay — GameSession Commands

---

#### `PlayCard`
Play one card from the player's hand onto the discard pile. For Wild and Wild Draw Four cards, `declared_color` is a **required field** of this command — color declaration is atomic with the play.

| Field | Value |
|---|---|
| **Aggregate** | `GameSession` |
| **Submitted by** | Active player whose turn it is (or any player for jump-in — see `JumpIn`) |
| **Preconditions** | Game is `in_progress`; it is the player's turn; no challenge window is open blocking their action; the card is in the player's hand; the card is a legal play; for Wild/WD4: `declared_color` is present and is a valid color (Red, Green, Blue, Yellow) |
| **Rejection reasons** | Not the player's turn; card not in hand; illegal play (color/rank mismatch and not Wild/WD4); WD4 played while holding a matching active-color card; Wild or WD4 played without a `declared_color`; game not in `in_progress`; challenge window is open and this action is not permitted during it; stale state version |
| **Concurrency** | `[stale-version]` `[idempotent]` |
| **Produces** | `CardPlayed` → conditionally: `ColorDeclared` (Wild/WD4, using `declared_color` from this command), `DirectionReversed` (Reverse), `PlayerSkipped` (Skip), `DrawTwoActivated` (Draw Two), `WildDrawFourActivated` (WD4), `ChallengeWindowOpened` (second-to-last card or WD4), `TurnAdvanced`, `GameCompleted` (last card) |

#### `DrawCard`
Draw one card from the draw pile and end the turn.

| Field | Value |
|---|---|
| **Aggregate** | `GameSession` |
| **Submitted by** | Active player whose turn it is |
| **Preconditions** | Game is `in_progress`; it is the player's turn; no active stack penalty pending (stack must be resolved separately); no challenge window blocking the action |
| **Rejection reasons** | Not the player's turn; an active Draw Two stack requires the player to either stack or draw the full accumulated penalty (not a single card draw); game not `in_progress`; stale state version |
| **Concurrency** | `[stale-version]` `[idempotent]` |
| **Produces** | `CardDrawn` → `DrawPileReplenished` (if draw pile was empty) → `TurnAdvanced` |

---

#### `DrawStackPenalty`
Accept the accumulated Draw Two stack penalty (draw the full total and skip turn).

| Field | Value |
|---|---|
| **Aggregate** | `GameSession` |
| **Submitted by** | Active player whose turn it is, when a Draw Two stack is active |
| **Preconditions** | Game is `in_progress`; it is the player's turn; `active_stack_penalty > 0` |
| **Rejection reasons** | No active stack; not the player's turn; stale state version |
| **Concurrency** | `[stale-version]` `[idempotent]` |
| **Produces** | `PenaltyCardsDrawn` (full accumulated total) → `DrawPileReplenished` (if needed) → `TurnAdvanced` |

---

#### `JumpIn`
Play an identical card out of turn, resetting turn order from the jumping player's position.

| Field | Value |
|---|---|
| **Aggregate** | `GameSession` |
| **Submitted by** | Any active player not currently taking their turn |
| **Preconditions** | Game is `in_progress`; no challenge window is open; the submitted card is identical (same color + same rank/symbol) to the top of the discard pile; the submitter holds that card; the submitter is not the player who just played the top card; card type is not Wild or WD4 |
| **Rejection reasons** | Card does not match top of discard pile exactly; player is the one who just played that card (self-jump); card is Wild or WD4; challenge window open; game not `in_progress`; stale state version |
| **Concurrency** | `[stale-version]` `[idempotent]` — resolved via **RTT-adjusted effective timestamp** (see race resolution policy below); all losing submissions rejected with conflict |
| **Produces** | `JumpInOccurred` → card effects applied (same as `PlayCard`) → `TurnAdvanced`; if multiple simultaneous valid submissions: `RaceResolved` emitted before `JumpInOccurred` |

**Race resolution policy for `JumpIn`:** When two or more valid `JumpIn` submissions arrive within a 150ms server-arrival window, the server computes `effective_submission_time = arrival_time − RTT/2` for each submitter using their `LatencyProfile`. The submission with the earliest effective time wins. If effective times are within ±20ms of each other (within measurement uncertainty), or if any submitter's `LatencyProfile.measurement_available` is false, the winner is chosen by server-side RNG with equal probability per submission. The outcome is recorded in a `RaceResolved` event appended to the game log before any effect is applied.

---

#### `CallUno`
Declare "Uno!" when holding exactly one card in hand.

| Field | Value |
|---|---|
| **Aggregate** | `GameSession` |
| **Submitted by** | The player who just played their second-to-last card |
| **Preconditions** | Game is `in_progress`; the challenge window for this player's Uno! call is open; the player holds exactly 1 card; the player has not already called Uno! in this window |
| **Rejection reasons** | No open Uno! challenge window for this player; player holds more than 1 card (penalty already applied); already called; window expired |
| **Concurrency** | `[idempotent]` |
| **Produces** | `UnoCallMade` |

---

#### `ChallengeUno`
Challenge that a player did not call "Uno!" after playing their second-to-last card.

| Field | Value |
|---|---|
| **Aggregate** | `GameSession` |
| **Submitted by** | Any opponent (not the player who played the second-to-last card) |
| **Preconditions** | Game is `in_progress`; a Uno! challenge window is open; the target player has not yet called Uno!; the challenger has not already challenged in this window |
| **Rejection reasons** | No open Uno! challenge window; target already called Uno!; challenge already issued in this window; submitter is the target player; window expired; stale state version |
| **Concurrency** | `[stale-version]` `[idempotent]` — resolved via **RTT-adjusted effective timestamp** (see race resolution policy below); all losing submissions rejected with conflict |
| **Produces** | `UnoChallengeIssued` → `UnoChallengeResolved` → `PenaltyCardsDrawn` (2 cards to guilty party) → `ChallengeWindowClosed`; if multiple simultaneous valid submissions: `RaceResolved` emitted before `UnoChallengeIssued` |

**Race resolution policy for `ChallengeUno`:** Same policy as `JumpIn` above. When two or more opponents submit `ChallengeUno` within a 150ms server-arrival window, effective submission times are compared; earliest wins. Ties within ±20ms or missing `LatencyProfile` fall back to server-side RNG. `RaceResolved` is appended to the game log before `UnoChallengeIssued`.

---

#### `ChallengeWildDrawFour`
Challenge that the player who played a WD4 held a card matching the active color.

| Field | Value |
|---|---|
| **Aggregate** | `GameSession` |
| **Submitted by** | The next player in turn order (the one required to draw 4) |
| **Preconditions** | Game is `in_progress`; a WD4 challenge window is open; the challenger is the correct next player; no prior WD4 challenge has been issued in this window; challenger has not yet drawn cards |
| **Rejection reasons** | No open WD4 challenge window; challenger is not the affected next player; challenge already issued; challenger already drew cards (waived challenge); window expired; stale state version |
| **Concurrency** | `[stale-version]` `[idempotent]` |
| **Produces** | `WildDrawFourChallengeIssued` → `WildDrawFourChallengeResolved` → on guilty: `WD4Rescinded`, `PenaltyCardsDrawn` (4 to accused), `TurnAdvanced` (challenger takes turn normally); on innocent: `PenaltyCardsDrawn` (6 to challenger), `TurnAdvanced` (challenger's turn skipped) |

---

#### `Forfeit`
Voluntarily and permanently leave the current game.

| Field | Value |
|---|---|
| **Aggregate** | `GameSession` + `Room` |
| **Submitted by** | Any active player |
| **Preconditions** | Player is an active (non-forfeited) participant in the game |
| **Rejection reasons** | Player already forfeited; player not in this game |
| **Concurrency** | `[idempotent]` — duplicate forfeit submissions return original outcome |
| **Produces** | `PlayerForfeited` → conditionally: `GameCompleted` (1 player left — that player wins), or game continues (2+ players left) |

---

### 1.2 Room Gameplay — Room Commands

---

#### `JoinQueue`
Enter the casual Quick Play matchmaking queue.

| Field | Value |
|---|---|
| **Aggregate** | `MatchmakingQueue` |
| **Submitted by** | Any authenticated player not currently in an active game or queue |
| **Preconditions** | Player session is valid; player is not already in a queue or active game; player account is not suspended or banned |
| **Rejection reasons** | Already in queue; already in active game; session invalid; account suspended/banned |
| **Concurrency** | `[idempotent]` |
| **Produces** | `PlayerJoinedQueue` → (when room assembled) `RoomCreated`, `PlayerAssignedToRoom` |

---

#### `LeaveQueue`
Exit the casual matchmaking queue before a room is assigned.

| Field | Value |
|---|---|
| **Aggregate** | `MatchmakingQueue` |
| **Submitted by** | Player currently in the queue |
| **Preconditions** | Player is in the queue and has not yet been assigned to a room |
| **Rejection reasons** | Not in queue; already assigned to a room |
| **Concurrency** | `[idempotent]` |
| **Produces** | `PlayerLeftQueue` |

---

#### `JoinAsSpectator`
Subscribe to observe an active or lobby room.

| Field | Value |
|---|---|
| **Aggregate** | `Room` |
| **Submitted by** | Any authenticated player |
| **Preconditions** | Room exists; player session is valid |
| **Rejection reasons** | Room does not exist; session invalid |
| **Concurrency** | `[idempotent]` |
| **Produces** | `SpectatorJoined` |

---

### 1.3 Identity/Session Commands

---

#### `Register`
Create a new player account.

| Field | Value |
|---|---|
| **Aggregate** | `PlayerProfile`, `PlayerSession` |
| **Submitted by** | Unauthenticated client |
| **Preconditions** | Username is not already taken; region is a valid region ID |
| **Rejection reasons** | Username taken; invalid region; invalid input |
| **Concurrency** | `[idempotent]` (by username) |
| **Produces** | `PlayerRegistered` → `SessionCreated` |

---

#### `Login`
Authenticate and obtain a new session token.

| Field | Value |
|---|---|
| **Aggregate** | `PlayerSession` |
| **Submitted by** | Unauthenticated client |
| **Preconditions** | Credentials are valid; account is not banned |
| **Rejection reasons** | Invalid credentials; account banned |
| **Concurrency** | `[idempotent]` (by credentials + timestamp) |
| **Produces** | `SessionCreated` → `SessionInvalidated` (for any prior session) → if prior session was in active game: `ReconnectionWindowStarted` |

---

#### `Logout`
Explicitly terminate the current session.

| Field | Value |
|---|---|
| **Aggregate** | `PlayerSession` |
| **Submitted by** | Authenticated player |
| **Preconditions** | Session is valid |
| **Rejection reasons** | Session already invalid |
| **Concurrency** | `[idempotent]` |
| **Produces** | `SessionInvalidated` → if player was in active game: `ReconnectionWindowStarted` |

---

#### `ReconnectToGame`
Re-establish a session and synchronize game state after a disconnection.

| Field | Value |
|---|---|
| **Aggregate** | `PlayerSession` |
| **Submitted by** | Player with a valid JWT within their reconnection window |
| **Preconditions** | Player has an open `ReconnectionWindow`; the window has not expired; the new session JWT is valid |
| **Rejection reasons** | No open reconnection window; window expired (forfeit already issued); session invalid |
| **Concurrency** | `[idempotent]` |
| **Produces** | `PlayerReconnected` → `ReconnectionWindowClosed` → full game state snapshot delivered to client |

---

### 1.4 Tournament Orchestration Commands

---

#### `RegisterForTournament`
Enroll the player in an upcoming tournament.

| Field | Value |
|---|---|
| **Aggregate** | `Tournament` |
| **Submitted by** | Authenticated player |
| **Preconditions** | Tournament status is `registration_open`; player is not already registered; player is not actively participating in another tournament |
| **Rejection reasons** | Registration closed; already registered; concurrent tournament participation |
| **Concurrency** | `[idempotent]` |
| **Produces** | `PlayerRegisteredForTournament` |

---

#### `WithdrawFromTournament`
Cancel registration before the tournament starts.

| Field | Value |
|---|---|
| **Aggregate** | `Tournament` |
| **Submitted by** | Registered player |
| **Preconditions** | Tournament status is `registration_open` or `registration_closed` (not yet started) |
| **Rejection reasons** | Tournament already started; player not registered |
| **Concurrency** | `[idempotent]` |
| **Produces** | `PlayerWithdrewFromTournament` |

---

#### `CloseRegistration`
Close the registration window and lock the confirmed player list. Triggered automatically by the system at the scheduled registration-close time; may also be issued early by an admin.

| Field | Value |
|---|---|
| **Aggregate** | `Tournament` |
| **Submitted by** | System (scheduled) or Admin |
| **Preconditions** | Tournament status is `registration_open` |
| **Rejection reasons** | Tournament not in `registration_open` state; tournament already cancelled |
| **Concurrency** | `[idempotent]` |
| **Produces** | `RegistrationClosed {tournament_id, confirmed_player_count}` |

---

#### `StartTournament`
Transition the tournament from `registration_closed` to `in_progress` and kick off Round 1. Triggered automatically by the system at the scheduled start time; may be issued manually by an admin after registration has closed.

| Field | Value |
|---|---|
| **Aggregate** | `Tournament` |
| **Submitted by** | System (scheduled) or Admin |
| **Preconditions** | Tournament status is `registration_closed`; `confirmed_players ≥ 1,000` |
| **Rejection reasons** | Tournament not in `registration_closed` state; fewer than 1,000 confirmed players (tournament is cancelled instead); tournament already cancelled |
| **Concurrency** | `[idempotent]` |
| **Produces** | `TournamentStarted {tournament_id, confirmed_players, total_rounds}` → `RoundStarted {round_number: 1, ...}` |

**Failure path:** If `confirmed_players < 1,000` when `StartTournament` fires, the tournament is automatically cancelled: `TournamentCancelled {reason: InsufficientPlayers}` is emitted instead of `TournamentStarted`. Registered players are notified via the `TournamentCancelled` event.

---

### 1.5 Moderation/Admin Commands

---

#### `CreateTournament`
Schedule a new tournament.

| Field | Value |
|---|---|
| **Aggregate** | `Tournament` |
| **Submitted by** | Admin |
| **Preconditions** | Admin session is valid; start time is in the future |
| **Rejection reasons** | Not an admin; invalid schedule |
| **Concurrency** | `[idempotent]` |
| **Produces** | `TournamentCreated` → `RegistrationOpened` (at scheduled registration-open time) |

---

#### `CancelTournament`
Abort a running or upcoming tournament.

| Field | Value |
|---|---|
| **Aggregate** | `Tournament` |
| **Submitted by** | Admin |
| **Preconditions** | Admin session is valid; tournament is not already `completed` or `cancelled` |
| **Rejection reasons** | Not an admin; tournament already ended |
| **Concurrency** | `[idempotent]` |
| **Produces** | `TournamentCancelled` → Ranking reverses all Elo changes for games within this tournament |

---

#### `VoidGameResult`
Override a completed game result after admin review.

| Field | Value |
|---|---|
| **Aggregate** | `GameSession` (via Moderation) |
| **Submitted by** | Admin |
| **Preconditions** | Admin session is valid; game is in `completed` state; game has not already been voided |
| **Rejection reasons** | Not an admin; game not completed; already voided |
| **Concurrency** | `[idempotent]` |
| **Produces** | `GameResultVoided` → Ranking reverses Elo changes from that game |

---

#### `FlagGame`
Mark a game for admin review.

| Field | Value |
|---|---|
| **Aggregate** | `GameSession` (via Moderation) |
| **Submitted by** | Any authenticated player or spectator |
| **Preconditions** | Game is `completed`; submitter has not already flagged this game; rate limit not exceeded |
| **Rejection reasons** | Game not completed; already flagged by this user; rate limit hit (5 flags/hour per user) |
| **Concurrency** | `[idempotent]` |
| **Produces** | `GameFlagged` |

---

## 2. Domain Event Catalog

### 2.1 Room Gameplay — GameSession Events

| Event | Producing aggregate | Key payload fields | Downstream consumers |
|---|---|---|---|
| `GameInitialized` | `GameSession` | `game_id`, `room_id`, `player_order`, `initial_discard_top`, `state_version` | Spectator View, Tournament Orchestration |
| `CardPlayed` | `GameSession` | `game_id`, `player_id`, `card`, `new_discard_top`, `active_color`, `state_version` | Spectator View |
| `ColorDeclared` | `GameSession` | `game_id`, `player_id`, `declared_color`, `state_version` | Spectator View |
| `CardDrawn` | `GameSession` | `game_id`, `player_id`, `new_hand_count`, `state_version` *(card identity omitted for spectators)* | Spectator View (filtered) |
| `DrawPileReplenished` | `GameSession` | `game_id`, `cards_reshuffled_count`, `state_version` | Spectator View |
| `TurnAdvanced` | `GameSession` | `game_id`, `next_player_id`, `direction`, `state_version` | Spectator View |
| `DirectionReversed` | `GameSession` | `game_id`, `new_direction`, `caused_by_player_id`, `state_version` | Spectator View |
| `PlayerSkipped` | `GameSession` | `game_id`, `skipped_player_id`, `state_version` | Spectator View |
| `DrawTwoActivated` | `GameSession` | `game_id`, `target_player_id`, `accumulated_penalty`, `state_version` | Spectator View |
| `DrawTwoStacked` | `GameSession` | `game_id`, `stacking_player_id`, `accumulated_penalty`, `state_version` | Spectator View |
| `PenaltyCardsDrawn` | `GameSession` | `game_id`, `player_id`, `count`, `reason: UnoChallenge\|WD4Effect\|WD4Challenge\|StackPenalty`, `new_hand_count`, `state_version` | Spectator View (count only, not card identities) |
| `JumpInOccurred` | `GameSession` | `game_id`, `player_id`, `card`, `new_turn_order`, `state_version` | Spectator View |
| `WildDrawFourActivated` | `GameSession` | `game_id`, `player_id`, `declared_color`, `target_player_id`, `state_version` | Spectator View |
| `ChallengeWindowOpened` | `GameSession` | `game_id`, `window_type: Uno\|WD4\|Combined`, `target_player_id` *(player who may be challenged)*, `uno_eligible_challengers: List<player_id>` *(all opponents — present on Uno and Combined windows)*, `wd4_eligible_challenger: player_id` *(next player in turn order — present on WD4 and Combined windows only)*, `expires_at`, `state_version` | Spectator View |
| `ChallengeWindowClosed` | `GameSession` | `game_id`, `window_type`, `reason: Challenged\|Expired\|NextPlayerActed`, `state_version` | Spectator View |
| `UnoCallMade` | `GameSession` | `game_id`, `player_id`, `state_version` | Spectator View |
| `UnoChallengeIssued` | `GameSession` | `game_id`, `challenger_id`, `target_player_id`, `state_version` | Spectator View |
| `UnoChallengeResolved` | `GameSession` | `game_id`, `challenger_id`, `target_player_id`, `outcome: Guilty\|Innocent`, `state_version` | Spectator View |
| `WildDrawFourChallengeIssued` | `GameSession` | `game_id`, `challenger_id`, `accused_player_id`, `state_version` | Spectator View |
| `WildDrawFourChallengeResolved` | `GameSession` | `game_id`, `challenger_id`, `accused_player_id`, `outcome: Guilty\|Innocent`, `accused_hand_at_time` *(withheld from spectators during game; in post-game log)*, `state_version` | Spectator View (outcome only, hand withheld), Moderation/Admin |
| `RaceResolved` | `GameSession` | `game_id`, `race_type: JumpIn\|UnoChallenge`, `submissions: List<{player_id, arrival_time, effective_submission_time, rtt_used_ms, rtt_available: bool}>`, `winner_player_id`, `resolution_method: EffectiveTimestamp\|RNG`, `state_version` | Spectator View (winner only; individual RTT values withheld), game log (full detail for audit) |
| `PlayerDisconnected` | `GameSession` | `game_id`, `player_id`, `reconnection_window_expires_at` | Spectator View, Tournament Orchestration |
| `PlayerReconnected` | `GameSession` | `game_id`, `player_id` | Spectator View |
| `PlayerForfeited` | `GameSession` | `game_id`, `player_id`, `reason: Voluntary\|AFK\|ReconnectionExpired`, `remaining_active_players` | Spectator View, Tournament Orchestration, Ranking |
| `GameCompleted` | `GameSession` | `game_id`, `room_id`, `placements: List<GamePlacement>`, `game_type: casual\|tournament`, `tournament_id?`, `match_id?` | Ranking (casual), Tournament Orchestration (tournament), Spectator View |

---

### 2.2 Room Gameplay — Room Events

| Event | Producing aggregate | Key payload fields | Downstream consumers |
|---|---|---|---|
| `RoomCreated` | `Room` | `room_id`, `room_type`, `tournament_id?` | Spectator View, Tournament Orchestration |
| `PlayerAssignedToRoom` | `Room` | `room_id`, `player_id` | Spectator View |
| `LobbyTimerStarted` | `Room` | `room_id`, `player_count`, `timer_expires_at` | Spectator View |
| `LobbyTimerReduced` | `Room` | `room_id`, `new_expires_at` *(triggered when room fills to 10)* | Spectator View |
| `GameStarted` | `Room` | `room_id`, `game_id`, `player_ids` | Spectator View, Tournament Orchestration |
| `RoomCompleted` | `Room` | `room_id`, `final_standings` | Spectator View, Tournament Orchestration |
| `RoomCancelled` | `Room` | `room_id`, `reason: InsufficientPlayers\|TournamentCancelled` | Spectator View, Tournament Orchestration *(tournament rooms only, for `TournamentCancelled` reason)* |
| `PlayerJoinedQueue` | `MatchmakingQueue` | `player_id`, `joined_at`, `region`, `elo_rating` | — |
| `PlayerLeftQueue` | `MatchmakingQueue` | `player_id` | — |
| `QueueEntryExpired` | `MatchmakingQueue` | `player_id`, `queued_since` | — *(player must re-submit `JoinQueue` to re-enter)* |
| `RoomAssemblyTriggered` | `MatchmakingQueue` | `assembled_player_ids: List<player_id>`, `queue_type` | Room Gameplay *(triggers `RoomCreated` + `PlayerAssignedToRoom` sequence)* |

---

### 2.3 Tournament Orchestration — Match Events

| Event | Producing aggregate | Key payload fields | Downstream consumers |
|---|---|---|---|
| `MatchStarted` | `Match` | `match_id`, `room_id`, `tournament_id`, `round_number`, `player_ids`, `timeout_deadline` | Spectator View |
| `GameInMatchStarted` | `Match` | `match_id`, `game_id`, `sequence_number` | Spectator View |
| `MatchWinAwarded` | `Match` | `match_id`, `player_id`, `match_wins_total`, `sequence_number` | Spectator View |
| `MatchEndedEarly` | `Match` | `match_id`, `winner_player_id`, `match_wins`, `games_played` | Spectator View, TournamentRound |
| `MatchEndedAfterGame3` | `Match` | `match_id`, `final_standings: List<MatchStanding>` | Spectator View, TournamentRound |
| `MatchTimeoutReached` | `Match` | `match_id`, `active_game_id`, `standings_at_timeout` | Spectator View, TournamentRound |
| `MatchCompleted` | `Match` | `match_id`, `room_id`, `tournament_id`, `round_number`, `final_standings: List<MatchStanding>`, `qualifiers: List<player_id>` | TournamentRound, Spectator View |

---

### 2.4 Tournament Orchestration — Round & Tournament Events

| Event | Producing aggregate | Key payload fields | Downstream consumers |
|---|---|---|---|
| `RoundStarted` | `TournamentRound` | `tournament_id`, `round_number`, `expected_player_count`, `phase_start_threshold` | Spectator View |
| `PhaseStartThresholdReached` | `TournamentRound` | `tournament_id`, `round_number`, `qualifier_count` | Spectator View |
| `TournamentRoomAssigned` | `TournamentRound` | `tournament_id`, `round_number`, `room_id`, `player_ids` | Spectator View |
| `LoneQualifierAdvanced` | `TournamentRound` | `tournament_id`, `round_number`, `player_id` | Spectator View |
| `AdvancementResolved` | `TournamentRound` | `tournament_id`, `round_number`, `room_id`, `qualifiers`, `eliminated_players` | Spectator View |
| `RoundCompleted` | `TournamentRound` | `tournament_id`, `round_number`, `total_qualifiers`, `next_round_player_count` | Tournament, Spectator View |
| `TournamentCreated` | `Tournament` | `tournament_id`, `created_by_admin_id`, `scheduled_start`, `registration_open_at` | — |
| `RegistrationOpened` | `Tournament` | `tournament_id`, `registration_closes_at` | Spectator View |
| `RegistrationClosed` | `Tournament` | `tournament_id`, `confirmed_player_count` | Spectator View |
| `TournamentStarted` | `Tournament` | `tournament_id`, `confirmed_players`, `total_rounds` | Spectator View |
| `FinalRoomCreated` | `Tournament` | `tournament_id`, `room_id`, `player_ids` | Spectator View |
| `TournamentCompleted` | `Tournament` | `tournament_id`, `champion_id`, `final_standings: List<Placement>` | Ranking, Spectator View |
| `TournamentCancelled` | `Tournament` (via Moderation command) | `tournament_id`, `cancelled_by_admin_id`, `reason` | Ranking, Spectator View |

---

### 2.5 Identity/Session Events

| Event | Producing aggregate | Key payload fields | Downstream consumers |
|---|---|---|---|
| `PlayerRegistered` | `PlayerProfile` | `player_id`, `username`, `region` | Ranking (initialize Elo records) |
| `SessionCreated` | `PlayerSession` | `player_id`, `issued_at` | — (JWT returned to client) |
| `SessionInvalidated` | `PlayerSession` | `player_id`, `invalidated_at` | Room Gameplay (start reconnection window if in game) |
| `ReconnectionWindowStarted` | `PlayerSession` | `player_id`, `game_id`, `expires_at` | Room Gameplay, Tournament Orchestration |
| `PlayerReconnected` | `PlayerSession` | `player_id`, `game_id` | Room Gameplay |
| `ReconnectionWindowExpired` | `PlayerSession` | `player_id`, `game_id` | Room Gameplay (triggers `PlayerForfeited`) |
| `PlayerSuspended` | `PlayerProfile` | `player_id`, `suspended_until` | Room Gameplay, Tournament Orchestration |
| `PlayerBanned` | `PlayerProfile` | `player_id`, `banned_at` | Room Gameplay, Tournament Orchestration |

---

### 2.6 Ranking Events

| Event | Producing aggregate | Key payload fields | Downstream consumers |
|---|---|---|---|
| `EloUpdated` | `EloRecord` (Ranking context) | `player_id`, `old_elo`, `new_elo`, `delta`, `game_id`, `placement`, `k_factor_used`, `bonus_applied` | Spectator View (leaderboard update) |
| `TournamentEloUpdated` | `EloRecord` (Ranking context) | `player_id`, `old_elo`, `new_elo`, `delta`, `tournament_id`, `tournament_placement` | Spectator View (leaderboard update) |
| `EloReverted` | `EloRecord` (Ranking context) | `player_id`, `reverted_game_id`, `old_elo`, `restored_elo` | Spectator View |
| `PlayerStatsUpdated` | `PlayerProfile` (Identity/Session context) | `player_id`, `games_played`, `casual_wins`, `cumulative_points`, `tournaments_won` | Spectator View (profile stats) |

---

### 2.7 Moderation/Admin Events

| Event | Producing aggregate | Key payload fields | Downstream consumers |
|---|---|---|---|
| `GameFlagged` | Moderation | `game_id`, `flagged_by`, `reason_text` | Moderation (admin review queue) |
| `GameResultVoided` | Moderation | `game_id`, `voided_by_admin_id` | Ranking (`EloReverted`), Spectator View |
| `ActionRateLimitExceeded` | Moderation | `player_id`, `action_type`, `violation_count_in_window` | Moderation |
| `PlayerAbuseWarningIssued` | Moderation | `player_id`, `warning_count_in_24h` | Identity/Session (notify player) |
| `PlayerSessionSuspended` | Moderation | `player_id`, `suspended_until` | Identity/Session (`PlayerSuspended`) |

---

## 3. Causality Map

Key chains showing what triggers what across the domain.

### 3.1 Normal Turn
```
PlayCard
  → CardPlayed
  → [if Reverse] DirectionReversed
  → [if Skip] PlayerSkipped + TurnAdvanced
  → [if Draw Two] DrawTwoActivated
      → [if next player stacks] DrawTwoStacked → DrawTwoActivated (accumulated)
      → [if next player draws] PenaltyCardsDrawn → TurnAdvanced
  → [if Wild] ColorDeclared (declared_color taken from PlayCard command) → TurnAdvanced
  → [if WD4] ColorDeclared (declared_color taken from PlayCard command) → WildDrawFourActivated → ChallengeWindowOpened (WD4 or Combined)
      → [if challenged + guilty] WD4Rescinded → PenaltyCardsDrawn (4 to accused) → TurnAdvanced
      → [if challenged + innocent] PenaltyCardsDrawn (6 to challenger) → TurnAdvanced
      → [if not challenged] PenaltyCardsDrawn (4 to next player) → TurnAdvanced
  → [if second-to-last card] ChallengeWindowOpened (Uno or Combined)
      → [if Uno! called in time] UnoCallMade → (window stays open for remaining time)
      → [if challenged + guilty] PenaltyCardsDrawn (2 to player) → ChallengeWindowClosed
      → [if challenged + innocent] PenaltyCardsDrawn (2 to challenger) → ChallengeWindowClosed
      → [if window expires unchallenged] ChallengeWindowClosed (no penalty; player retains one-card hand)
  → [if last card] GameCompleted
  → [else] TurnAdvanced
```

### 3.2 Game Completion → Ranking (Casual)
```
GameCompleted (game_type: casual)
  → Ranking consumes event
  → EloUpdated (for each player, based on placement)
```

### 3.3 Game Completion → Match Progression (Tournament)
```
GameCompleted (game_type: tournament)
  → Match consumes event
  → MatchWinAwarded (to game winner)
  → [if winner reaches 2 match_wins] MatchEndedEarly → MatchCompleted
  → [if Game 3 completed] MatchEndedAfterGame3 → MatchCompleted
  → MatchCompleted
      → AdvancementResolved (top 3 qualifiers identified)
      → TournamentRound accumulates qualifiers
      → [if all rooms in round done] RoundCompleted
          → [if ≤10 players remain] FinalRoomCreated
          → [else] RoundStarted (next round) → TournamentRoomAssigned (per room)
      → [if Final Room match completes] TournamentCompleted
          → TournamentEloUpdated (for all participants)
```

### 3.4 Forfeit Cascade
```
PlayerForfeited
  → [if 1 active player remains] GameCompleted (that player wins)
      NOTE: reaching 0 active players through forfeits is unreachable — commands are
      serialized, so the last-player-wins rule fires before a second "final" forfeit
      could be processed. GameResultVoided is emitted by Moderation only (admin-only outcome; see VoidGameResult).
  → [if 2+ active players remain] game continues
  → [if tournament room] Tournament Orchestration marks player eliminated
      → [if ≤3 active players in room] all remaining active players advance unconditionally
```

### 3.5 Session Invalidation → Reconnection
```
Login (new device)
  → SessionCreated
  → SessionInvalidated (old session)
      → [if player in active game] ReconnectionWindowStarted
          → [if reconnected within 60s] PlayerReconnected → turns resume
          → [if window expires] ReconnectionWindowExpired → PlayerForfeited
```

### 3.6 Abuse Escalation
```
[Rate limit violation]
  → ActionRateLimitExceeded
  → [if 5 violations in 10 min] PlayerAbuseWarningIssued
      → [if 3 warnings in 24h] PlayerSessionSuspended
          → SessionInvalidated → [if in game] ReconnectionWindowStarted
          → [after 15-min cooldown] suspension lifts
          → [if repeated suspensions in 7 days] admin review → potential PlayerBanned
```

---

## 4. Idempotency & Stale Command Reference

| Command type | Stale-version check | Idempotency key | Duplicate behavior |
|---|---|---|---|
| All `GameSession` write commands | Yes — `state_version` must match | Yes — `idempotency_key` UUID | Returns original outcome; no reprocessing |
| `JumpIn`, `ChallengeUno`, `ChallengeWildDrawFour` | Yes | Yes | First valid submission wins; all concurrent duplicates get conflict response |
| `Forfeit` | No (irreversible; version not required) | Yes | Subsequent forfeits return original outcome |
| `CallUno` | No (window-bound, not version-bound) | Yes | Subsequent calls within window are no-ops |
| `Login`, `Register` | No | Yes (by credentials/username) | Returns existing session/profile |
| `JoinQueue`, `LeaveQueue` | No | Yes | No-op if already in desired state |
| Admin commands (`VoidGameResult`, `CancelTournament`) | No | Yes (by target ID) | Returns original outcome |

**Stale command resolution:**
1. Client submits command with `state_version: N`.
2. Server's current version is `M > N`.
3. Server rejects with 409 Conflict.
4. Client consumes the event stream from version `N+1` to `M` to reconcile.
5. Client re-evaluates whether the intended action is still valid in the current state.
6. If still valid, client resubmits with `state_version: M`.
