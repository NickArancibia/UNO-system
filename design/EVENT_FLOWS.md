# UnoArena — Domain Event Flow Narratives

This document provides end-to-end event sequence narratives for the three mandatory flows required by the assignment, plus two additional exceptional flows that are critical to domain correctness. All terms follow [GLOSSARY.md](./GLOSSARY.md). Events and commands reference [COMMANDS_EVENTS.md](./COMMANDS_EVENTS.md).

**Notation:**
- `[SYNC]` — decision or state change that happens atomically within the same aggregate transaction. When shown immediately after a command submission, it lists the **server-side precondition checks** being validated before the command is accepted. A ✓ means the check passes.
- `[ASYNC]` — propagation that crosses a context boundary via domain event; eventual consistency applies.
- `[TIMER]` — a server-side timer fires; no client action involved.
- `>>` — time passes / multiple steps condensed.

---

## Flow 1: Casual Room — Creation to Completion

This flow covers the full lifecycle of a casual Quick Play room from queue entry through game completion and Elo update.

### Phase A — Matchmaking & Lobby

```
Player A submits: JoinQueue
  [SYNC] Identity/Session validates session
  [SYNC] Matchmaking checks: not already in queue or active game
  → PlayerJoinedQueue {player_id: A}

  >> (Players B, C, D, E also join queue)

[SYNC] Matchmaking assembles room from queue (regional + Elo proximity)
  → RoomCreated {room_id: R1, room_type: casual, status: waiting}
  → PlayerAssignedToRoom {room_id: R1, player_id: A}
  → PlayerAssignedToRoom {room_id: R1, player_id: B}
  → PlayerAssignedToRoom {room_id: R1, player_id: C}
  → PlayerAssignedToRoom {room_id: R1, player_id: D}
  → PlayerAssignedToRoom {room_id: R1, player_id: E}
  (5 players now present — lobby timer threshold reached; room may still fill up to 10)

[SYNC] Room transitions waiting → lobby
  → LobbyTimerStarted {room_id: R1, player_count: 5, timer_expires_at: T+5min}

  >> (Player F joins queue; matchmaking assigns to R1)
  >> ... up to Player J (10th player)

[SYNC] Room reaches maximum capacity (10 players)
  → PlayerAssignedToRoom {room_id: R1, player_id: J}
  → LobbyTimerReduced {room_id: R1, new_expires_at: T+10s}
```

### Phase B — Game Initialization

```
[TIMER] Lobby timer expires; 10 active players present
[SYNC] Room transitions lobby → in_progress
  → GameStarted {room_id: R1, game_id: G1, player_ids: [A..J]}

[SYNC] GameSession initializes:
  - Server shuffles 108-card deck (server-side RNG)
  - Deals 7 cards to each of 10 players (70 cards dealt)
  - Reveals top card of draw pile; if not a number card, reinsert and repeat
  - Sets turn_index, direction: clockwise, state_version: 1
  → GameInitialized {game_id: G1, player_order: [...], initial_discard_top: Red 5, state_version: 1}

[ASYNC] Spectator View receives GameInitialized
  → PublicGameView created for G1 (no hand data)
```

### Phase C — Gameplay Loop

```
Player A's turn (state_version: 1):

  Player A submits: PlayCard {card: Red 7, state_version: 1, idempotency_key: uuid-1}
  [SYNC] GameSession validates:
    - state_version matches (1 = 1) ✓
    - it is player A's turn ✓
    - Red 7 is in A's hand ✓
    - Red 7 is legal on Red 5 (color match) ✓
    - A holds 6 cards remaining (not second-to-last) ✓
  [SYNC] state_version increments to 2
  → CardPlayed {game_id: G1, player_id: A, card: Red 7, new_discard_top: Red 7,
                active_color: Red, state_version: 2}
  → TurnAdvanced {game_id: G1, next_player_id: B, direction: clockwise, state_version: 2}

[ASYNC] Spectator View receives CardPlayed, TurnAdvanced
  → PublicGameView updated (discard top, turn pointer, A's hand count: 6)

  >> Normal turns proceed for players B through J

--- Draw Two Example ---

Player C submits: PlayCard {card: Blue +2, state_version: N}
  [SYNC] validated, accepted
  → CardPlayed {card: Blue +2, ...}
  → DrawTwoActivated {target_player_id: D, accumulated_penalty: 2, state_version: N+1}
  → ChallengeWindowOpened? No — Draw Two has no challenge window
  (Player D must now either stack or draw the penalty)

  Player D holds a Green +2. Player D submits: PlayCard {card: Green +2, state_version: N+1}
  [SYNC] validated as stack response
  → CardPlayed {card: Green +2, ...}
  → DrawTwoStacked {stacking_player_id: D, accumulated_penalty: 4, state_version: N+2}
  → DrawTwoActivated {target_player_id: E, accumulated_penalty: 4, ...}

  Player E has no Draw Two. Player E submits: DrawStackPenalty {state_version: N+2}
  [SYNC] draw pile checked; replenished if needed
  → DrawPileReplenished {cards_reshuffled_count: 40, ...}  (if applicable)
  → PenaltyCardsDrawn {player_id: E, count: 4, reason: StackPenalty, new_hand_count: 11, ...}
  → TurnAdvanced {next_player_id: F, ...}

--- Second-to-Last Card + Uno! Call Example ---

Player A now holds 2 cards.
  Player A submits: PlayCard {card: Yellow 3, state_version: M}
  [SYNC] validated; A will hold 1 card after this play
  → CardPlayed {card: Yellow 3, ...}
  → ChallengeWindowOpened {window_type: Uno,
                            target_player_id: A,
                            uno_eligible_challengers: [B,C,D,E,F,G,H,I,J],
                            wd4_eligible_challenger: null,
                            expires_at: T+5s,
                            state_version: M+1}
  → TurnAdvanced {next_player_id: B, state_version: M+1}
  [TIMER] B's 45-second turn timer starts immediately (concurrent with the Uno! window)
  [TIMER] 5-second Uno! challenge window also starts now — runs within B's turn timer,
          does not pause or reset it. Window closes early if B submits any game action.

  NOTE — timing model distinction:
    Uno! window  → runs CONCURRENTLY with the next player's 45s turn timer.
    WD4 window   → runs BEFORE the next player's 45s turn timer (sequential).
    Combined window → runs BEFORE the next player's 45s turn timer (sequential).

  Player A submits: CallUno {state_version: M+1, idempotency_key: uuid-k}
  [SYNC] preconditions: window is open ✓; A holds exactly 1 card ✓; A has not previously
         called Uno! in this window ✓
  → UnoCallMade {game_id: G1, player_id: A, state_version: M+2}
  (Window stays open for remaining time — opponents may still challenge,
   but A is now safe; a successful challenge at this point penalizes the challenger)

  [TIMER] 5-second Uno! window expires with no challenge
  → ChallengeWindowClosed {reason: Expired, state_version: M+3}
  (A retains their one-card hand with no penalty — a penalty is only applied on a
   successful active challenge. B's 45s turn timer continues uninterrupted — time
   elapsed during the Uno! window counts against B's turn)
```

### Phase D — Game Completion

```
Player A's turn again. A holds 1 card.
  Player A submits: PlayCard {card: Wild, declared_color: Green, state_version: P}
  [SYNC] Wild is legal on any card ✓; declared_color: Green is valid ✓; A will hold 0 cards
  → CardPlayed {game_id: G1, player_id: A, card: Wild, new_discard_top: Wild,
                active_color: Green, state_version: P+1}
  → ColorDeclared {player_id: A, declared_color: Green, state_version: P+1}

  [SYNC] A's hand is now empty → game end condition met
  [SYNC] Server computes final placements:
    - A: rank 1, game_score: 0
    - Others: ranked by game_score (most negative = last); ties broken by fewest cards, then random
  [SYNC] Room transitions in_progress → completed
  → GameCompleted {game_id: G1, room_id: R1,
                   placements: [{player_id: A, rank: 1, game_score: 0, cards_remaining: 0}, ...],
                   game_type: casual,
                   state_version: P+2}
  → RoomCompleted {room_id: R1, final_standings: [...]}

[ASYNC] Spectator View receives GameCompleted
  → PublicGameView sealed; PublicGameLog created (all events, full card identities now visible)

[ASYNC] Ranking receives GameCompleted (casual)  ← see Flow 3 for detail
  → EloUpdated for each of the 10 players
```

---

## Flow 2: Tournament Round Advancement

This flow covers one full elimination round: qualifier accumulation, progressive room formation, concurrent match execution, and advancement resolution. It assumes Round 2 (90,000 players expected, threshold: 9,000).

### Phase A — Round Start & Progressive Room Formation

```
[SYNC] Previous round (Round 1) completes; 300,000 qualifiers expected
[ASYNC] TournamentRound for Round 2 created
  → RoundStarted {tournament_id: T1, round_number: 2,
                  expected_player_count: 300000,
                  phase_start_threshold: 9000}

  >> Rooms from Round 1 complete one by one; qualifiers stream in
  >> 9,000 qualifiers have arrived

[SYNC] Phase-start threshold reached
  → PhaseStartThresholdReached {tournament_id: T1, round_number: 2, qualifier_count: 9000}

[SYNC] Matchmaking begins forming rooms immediately (does not wait for all 300,000)
  [SYNC] Room R-2-001 assembled: 10 qualifiers pulled from pool
  → TournamentRoomAssigned {tournament_id: T1, round_number: 2,
                             room_id: R-2-001, player_ids: [P1..P10]}
  → RoomCreated {room_id: R-2-001, room_type: tournament}

  [SYNC] Lobby timer starts (matchmaking has determined room is at capacity)
  → LobbyTimerStarted {room_id: R-2-001, timer_expires_at: T+10s}

  >> Rooms R-2-002, R-2-003 ... formed in parallel as more qualifiers arrive
  >> Players not present when their lobby timer fires are forfeited before game starts
```

### Phase B — Concurrent Match Execution (one room shown)

```
[TIMER] Lobby timer expires for R-2-001; all 10 players present
[SYNC] Match M-2-001 created for room R-2-001
  → MatchStarted {match_id: M-2-001, room_id: R-2-001, tournament_id: T1,
                  round_number: 2, player_ids: [P1..P10],
                  timeout_deadline: T+20min}

--- Game 1 of 3 ---

  → GameInMatchStarted {match_id: M-2-001, game_id: G-2-001-1, sequence_number: 1}
  → GameInitialized {game_id: G-2-001-1, ...}

  >> Gameplay proceeds (same loop as Flow 1 Phase C)

  Player P3 empties hand first.
  → GameCompleted {game_id: G-2-001-1, game_type: tournament,
                   tournament_id: T1, match_id: M-2-001,
                   placements: [{P3, rank:1}, {P7, rank:2}, ...]}

[SYNC] Match receives GameCompleted
  → MatchWinAwarded {match_id: M-2-001, player_id: P3, match_wins_total: 1, sequence_number: 1}
  [SYNC] No player has reached 2 wins yet → Game 2 starts
  → GameInMatchStarted {match_id: M-2-001, game_id: G-2-001-2, sequence_number: 2}

--- Game 2 of 3 ---

  >> Gameplay proceeds

  Player P3 empties hand again.
  → GameCompleted {game_id: G-2-001-2, ...}

[SYNC] Match receives GameCompleted
  → MatchWinAwarded {match_id: M-2-001, player_id: P3, match_wins_total: 2, sequence_number: 2}
  [SYNC] P3 has reached 2 wins → early end condition met
  → MatchEndedEarly {match_id: M-2-001, winner_player_id: P3, match_wins: 2, games_played: 2}

--- Match End ---

[SYNC] Final standings computed:
  1. match_wins (P3: 2, others: 0 or 1)
  2. tie-break: cumulative card-point burden (for players tied on match_wins)
  3. tie-break: cumulative cards remaining
  4. forfeited players ranked below all active players

  → MatchCompleted {match_id: M-2-001, room_id: R-2-001, tournament_id: T1,
                    round_number: 2,
                    final_standings: [
                      {player_id: P3, match_wins: 2, burden: 0, cards: 0},
                      {player_id: P7, match_wins: 1, burden: 15, cards: 2},
                      {player_id: P1, match_wins: 1, burden: 22, cards: 3},
                      ...
                    ],
                    qualifiers: [P3, P7, P1]}

[SYNC] Top 3 (P3, P7, P1) advance
  → AdvancementResolved {tournament_id: T1, round_number: 2, room_id: R-2-001,
                          qualifiers: [P3, P7, P1],
                          eliminated_players: [P2, P4, P5, P6, P8, P9, P10]}
  → RoomCompleted {room_id: R-2-001, final_standings: [...]}

[ASYNC] Spectator View receives MatchCompleted, AdvancementResolved
  → BracketView updated for room R-2-001
```

### Phase C — Match Timeout Scenario (alternate path)

```
[TIMER] timeout_deadline reached for match M-2-001 during Game 2

[SYNC] Match receives MatchTimeoutReached
  → MatchTimeoutReached {match_id: M-2-001, active_game_id: G-2-001-2,
                          standings_at_timeout: [...current hand states...]}

[SYNC] Active game G-2-001-2 is resolved immediately using current state:
  - Players ranked by: highest game_score → fewest cards → random
  → GameCompleted {game_id: G-2-001-2, ... (timeout-resolved placements)}

[SYNC] MatchWinAwarded to timeout-resolved first-place player
[SYNC] Match ends immediately — no further games
  → MatchCompleted (with games_played: 2, resolved via timeout)
  → AdvancementResolved (top 3 from standings using completed + timeout game)
```

### Phase D — Round Completion & Next Round

```
  >> All 30,000 rooms for Round 2 complete over time (asynchronously)
  >> TournamentRound accumulates qualifiers from each AdvancementResolved event

[SYNC] Last room resolves → all rooms in Round 2 completed
  → RoundCompleted {tournament_id: T1, round_number: 2,
                    total_qualifiers: 90000,
                    next_round_player_count: 90000}

[SYNC] Tournament checks: 90,000 > 10 → not yet final
  → RoundStarted {tournament_id: T1, round_number: 3, ...}

  >> Rounds continue until ≤10 players remain

[SYNC] Round N completes with 8 qualifiers remaining
  → RoundCompleted {total_qualifiers: 8}
[SYNC] Tournament detects ≤10 players
  → FinalRoomCreated {tournament_id: T1, room_id: R-FINAL, player_ids: [Q1..Q8]}

  >> Final Room plays a Bo3 match (same flow as Phase B)

[SYNC] Final Room MatchCompleted
  → TournamentCompleted {tournament_id: T1, champion_id: Q3,
                          final_standings: [...all T participants ranked...]}

[ASYNC] Ranking receives TournamentCompleted  ← see Flow 3 for detail
```

---

## Flow 3: Elo & Ranking Updates After Game Completion

### Phase A — Casual Elo Update

```
[ASYNC] Ranking context receives:
  GameCompleted {game_id: G1, game_type: casual,
                 placements: [
                   {player_id: A, rank: 1, game_score: 0,    cards_remaining: 0},
                   {player_id: B, rank: 2, game_score: -14,  cards_remaining: 2},
                   {player_id: C, rank: 3, game_score: -22,  cards_remaining: 3},
                   {player_id: D, rank: 4, game_score: -22,  cards_remaining: 4},  ← tie on score
                   {player_id: E, rank: 5, game_score: -55,  cards_remaining: 5, forfeited: true}
                 ]}

[SYNC] Ranking reads current Elo for all players: A=1200, B=1050, C=1000, D=980, E=900

[SYNC] Forfeit check: E forfeited → assigned rank 5 (last) regardless of score

[SYNC] Actual score computed per player (S_i = (N − rank_i) / (N − 1), N=5):
  A (rank 1): S = (5-1)/(5-1) = 1.00
  B (rank 2): S = (5-2)/(5-1) = 0.75
  C (rank 3): S = (5-3)/(5-1) = 0.50
  D (rank 4): S = (5-4)/(5-1) = 0.25
  E (rank 5): S = (5-5)/(5-1) = 0.00

[SYNC] Expected score computed per player (pairwise):
  E_A = [P(A>B) + P(A>C) + P(A>D) + P(A>E)] / 4
        P(i>j) = 1 / (1 + 10^((R_j - R_i)/400))
  (computed for each player against all others)

[SYNC] K-factor assigned per player based on games_played:
  A: 200 games → K=12
  B: 45 games  → K=16
  C: 15 games  → K=32
  D: 8 games   → K=32
  E: 30 games  → K=16

[SYNC] Points bonus check (card-point burden ≤ 80% of room average):
  Room average burden = (0 + 14 + 22 + 22 + 55) / 5 = 22.6
  80% threshold = 18.08
  A: burden 0  ≤ 18.08 → +3 bonus ✓
  B: burden 14 ≤ 18.08 → +3 bonus ✓
  C: burden 22 > 18.08 → no bonus
  D: burden 22 > 18.08 → no bonus
  E: burden 55 > 18.08 → no bonus

[SYNC] Elo deltas computed: ΔR_i = K × (S_i − E_i) + bonus
  → EloUpdated {player_id: A, old_elo: 1200, new_elo: 1200+ΔA, delta: ΔA,
                game_id: G1, placement: 1, k_factor_used: 12, bonus_applied: true}
  → EloUpdated {player_id: B, ...}
  → EloUpdated {player_id: C, ...}
  → EloUpdated {player_id: D, ...}
  → EloUpdated {player_id: E, delta: negative (last place), bonus_applied: false}

[ASYNC] Spectator View receives EloUpdated events
  → LeaderboardView updated for all 5 players

[SYNC] PlayerProfile.stats updated for each player (games_played +1, win recorded for A)
  → PlayerStatsUpdated {player_id: A, ...}
```

### Phase B — Tournament Elo Update

```
[ASYNC] Ranking context receives:
  TournamentCompleted {tournament_id: T1, champion_id: Q3,
                       final_standings: [all T=50,000 participants ranked 1..50,000]}

[SYNC] Ranking reconstructs full placement list:
  - Round 1 eliminees (35,000 players): sub-ordered within their bucket by
    cumulative match win rate → cumulative game win rate
  - Round 2 eliminees (10,500 players): same sub-ordering
  - ... up to the Final Room participants
  - Champion Q3: rank 1

[SYNC] For each player i (1 to T=50,000):
  Actual score:  S_i = (T − p_i) / (T − 1)
  Expected score: E_i = [Σ_{j≠i} P(i beats j)] / (T − 1)
    (pairwise comparison against all other T-1 participants using current tournament Elo)
  K-factor: always 40 for tournament Elo
  Forfeit players: assigned worst placement within their elimination round bucket

[SYNC] Elo deltas applied and emitted per player:
  → TournamentEloUpdated {player_id: Q3, old_elo: 1100, new_elo: 1100+Δ,
                           delta: Δ, tournament_id: T1, tournament_placement: 1}
  >> (TournamentEloUpdated emitted for all T participants)

[ASYNC] Spectator View receives TournamentEloUpdated events
  → LeaderboardView (tournament) updated

[SYNC] PlayerProfile.stats updated for champion Q3:
  → PlayerStatsUpdated {player_id: Q3, tournaments_won: +1}
```

### Phase C — Elo Revert (Admin Void)

```
Admin submits: VoidGameResult {game_id: G1}
  [SYNC] Moderation validates: admin session valid; G1 is completed; not already voided
  → GameResultVoided {game_id: G1, voided_by_admin_id: admin-1}

[ASYNC] Ranking receives GameResultVoided
  [SYNC] Ranking reads original EloUpdated events for G1
  [SYNC] Reverses each player's Elo to pre-game value
  → EloReverted {player_id: A, reverted_game_id: G1,
                 old_elo: 1200+ΔA, restored_elo: 1200}
  >> (EloReverted emitted for all players in G1)

[ASYNC] Spectator View receives EloReverted
  → LeaderboardView updated to reflect reverted ratings
```

---

## Flow 4: Disconnection, Reconnection & Forfeit

This flow is not one of the three mandatory assignment narratives, but is included because the reconnection window and its failure path are critical to domain correctness.

### Phase A — Disconnection During Active Game

```
  >> Player B is in active game G1 (their turn)

[SYNC] Server detects B's connection has dropped (heartbeat timeout or explicit close)
  → PlayerDisconnected {game_id: G1, player_id: B,
                         reconnection_window_expires_at: T+60s}

[SYNC] PlayerSession creates ReconnectionWindow for B (expires at T+60s)
  → ReconnectionWindowStarted {player_id: B, game_id: G1, expires_at: T+60s}

[SYNC] GameSession: B's turns are now skipped (AFK counter does NOT accumulate)
  → TurnAdvanced {next_player_id: C, ...}  (B's turn skipped)
```

### Phase B — Successful Reconnection

```
  >> B reconnects within 60 seconds; submits Login (new token) + ReconnectToGame

[SYNC] Identity/Session validates credentials; new JWT issued
  → SessionCreated {player_id: B, issued_at: T+30s}

[SYNC] ReconnectToGame command received
  [SYNC] ReconnectionWindow for B is still open (T+30s < T+60s) ✓
  [SYNC] Session re-established; game state snapshot prepared
  → PlayerReconnected {player_id: B, game_id: G1}
  → ReconnectionWindowClosed {player_id: B}

[SYNC] Full current game state snapshot delivered to B's client
  (all events since B disconnected replayed; B's hand intact)

[SYNC] B's AFK counter reset to 0; turns resume normally on B's next turn
```

### Phase C — Reconnection Window Expiry → Forfeit

```
  >> B does not reconnect; T+60s is reached

[TIMER] ReconnectionWindow for B expires
  → ReconnectionWindowExpired {player_id: B, game_id: G1}

[SYNC] GameSession receives ReconnectionWindowExpired
  [SYNC] B is forfeited; B's hand discarded
  → PlayerForfeited {game_id: G1, player_id: B,
                     reason: ReconnectionExpired,
                     remaining_active_players: 9}

[SYNC] Forfeit consequence check:
  → 9 players remain → game continues normally
  → [if tournament room] Tournament Orchestration marks B as eliminated
```

### Phase D — New Login Invalidates In-Game Session

```
  >> Player B is in active game G1

B logs in from a new device:
  [SYNC] Identity/Session issues new JWT; updates valid_sessions_from
  → SessionCreated {player_id: B, issued_at: T_new}
  → SessionInvalidated {player_id: B, invalidated_at: T_new}

[ASYNC] Room Gameplay receives SessionInvalidated
  [SYNC] Old session for B is no longer valid
  → PlayerDisconnected {game_id: G1, player_id: B, ...}  (treated as disconnection)
  → ReconnectionWindowStarted {player_id: B, game_id: G1, expires_at: T_new+60s}

On the new device, B submits: ReconnectToGame
  >> Same as Phase B above — B can resume within 60 seconds
```
