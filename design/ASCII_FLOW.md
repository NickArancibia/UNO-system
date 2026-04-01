# UnoArena - End-to-End ASCII Flow

This file provides a precise, end-to-end flow chart for the whole platform lifecycle.
It reflects the current baseline specs, including Bo3 tournament behavior.

Legend:
- `[]` process/state
- `<>` decision
- `-->` transition
- `==>` async event propagation

---

## 1) Full Platform Flow (Top-Level)

```text
[Player/Admin Command]
        |
        v
[API/Application Boundary]
        |
        v
<Authenticated + Authorized?>
   |yes                               |no
   v                                  v
[Rate Limit Check]                [Reject: Unauthorized]
        |
        v
<Within Limits?>
   |yes                               |no
   v                                  v
[Idempotency Check by command_id] [Reject: RateLimited + abuse events]
        |
        v
<Duplicate command_id?>
   |yes                               |no
   v                                  v
[Return original outcome]      [State Version Check (if write on versioned aggregate)]
                                       |
                                       v
                               <expected_state_version matches?>
                                  |yes                           |no
                                  v                              v
                           [Execute domain command]      [Reject: Conflict (409)]
                                  |
                                  v
                     <Mode: Casual / Tournament / Admin?>
                         |Casual      |Tournament         |Admin
                         v            v                   v
                    [Casual Flow] [Tournament Flow] [Admin/Dispute Flow]
                         |            |                   |
                         +------------+-------------------+
                                      |
                                      v
                            [Domain Events Published]
                                      |
                                      +==> [Spectator Projection (public-only)]
                                      |
                                      +==> [Ranking Projection (casual/tournament Elo)]
                                      |
                                      +==> [Audit + Game Log]
```

---

## 2) Casual Flow (Room Creation -> Game Completion -> Elo)

```text
[JoinQuickPlayQueue]
        |
        v
[Matchmaking: region proximity -> Elo proximity]
        |
        v
[RoomCreated + PlayersAssignedToRoom]
        |
        v
<Lobby has >=5 players?>
   |no                          |yes
   v                            v
[Wait in waiting state]   [LobbyCountdownStarted (5 min)]
                                |
                                v
                      <Room reaches 10 players?>
                         |yes                     |no
                         v                        v
                [Countdown shortened to 10 sec] [Keep countdown]
                                |
                                v
                      <Countdown expired and >=2 players?>
                         |yes                      |no
                         v                         v
                     [GameStarted]         [RoomCancelled -> return players to queue]
                         |
                         v
                 [Turn Loop (45 sec per turn)]
                         |
                         v
      +------------------------------------------------------------------+
      | Player action path:                                               |
      | - SubmitPlayCard (legal by color/symbol/wild rules)              |
      | - SubmitDrawCard (draw one; turn ends)                            |
      | - Optional Jump-In (first valid submission wins)                  |
      | - Uno window (5 sec) + WD4 challenge window (5 sec)               |
      | - Combined Uno+WD4 window when WD4 is second-to-last card         |
      +------------------------------------------------------------------+
                         |
                         v
      +------------------------------------------------------------------+
      | Timer/disconnect path:                                            |
      | - Connected turn timeout -> auto draw one + end turn              |
      | - 3 consecutive connected timeouts -> AFK forfeit                 |
      | - Disconnect -> 60 sec reconnect window; turns skipped            |
      | - Reconnect in time -> resume; window expiry -> forfeit           |
      +------------------------------------------------------------------+
                         |
                         v
                <Terminal condition reached?>
                  |no                          |yes
                  v                            v
             [Continue turn loop]     <Which terminal condition?>
                                            |A                      |B                         |C
                                            v                       v                          v
                             [A: Player emptied hand] [B: Forfeit leaves 1 active] [C: Forfeit leaves 0]
                                            |                       |                          |
                                            v                       v                          v
                                   [GameCompleted]         [GameCompleted]              [GameVoided]
                                            |
                                            v
                     [Placement + score finalization + post-game log]
                                            |
                                            v
              <Is game voided?>
                 |yes                                   |no
                 v                                      v
      [No Elo update for any player]      [Ranking consumes GameCompleted]
                                                      |
                                                      v
                                           [CasualEloUpdated published]
```

---

## 3) Tournament Flow (Registration -> Rounds -> Bo3 -> Champion)

```text
[RegisterForTournament (window open)]
        |
        v
[Registration closes at configured time]
        |
        v
<Confirmed active players >= 1000?>
   |no                                  |yes
   v                                    v
[Tournament does not start]      [TournamentStarted + RoundStarted(R1)]
                                          |
                                          v
                             [Round Loop: while active players > 10]
                                          |
                                          v
                     [Wait round-start threshold for qualifier pool]
                                          |
                                          v
                             [AssignPlayersToRoundRooms]
                                          |
                                          v
                  [TournamentRoomCreated + PlayersAssignedToRoom]
                                          |
                                          v
                [Tournament lobby starts when room cannot be filled more]
                                          |
                                          v
                                [TournamentMatchInitialized]
                                          |
                                          v
                            [Initialize each active player: match_wins=0]
                                          |
                                          v
                               [Play Game 1 -> record result]
                                          |
                                          v
                  [TournamentGameResultRecorded + MatchWinAwarded]
                                          |
                                          v
                          <Any active player has match_wins=2?>
                            |yes                              |no
                            v                                 v
                [MatchEndedEarlyAtTwoWins]             [Play Game 2]
                            |                                 |
                            |                                 v
                            |                 [TournamentGameResultRecorded + MatchWinAwarded]
                            |                                 |
                            |                                 v
                            |                   <Any active player has match_wins=2?>
                            |                      |yes                      |no
                            |                      v                         v
                            |            [MatchEndedEarlyAtTwoWins]   [Play Game 3]
                            |                                                     |
                            |                                                     v
                            |                           [TournamentGameResultRecorded + MatchWinAwarded]
                            |                                                     |
                            |                                                     v
                            |                                        [MatchEndedAfterGameThree]
                            |                                                     |
                            +------------------------------+----------------------+
                                                           |
                                                           v
                         [Exceptional branch can interrupt at any point:]
                         [20-min match timeout during active game]
                         --> [Resolve active game by points/cards/random]
                         --> [Award match win to timeout-resolved first place]
                         --> [TournamentMatchTimeoutReached]
                                                           |
                                                           v
                                          [FinalizeTournamentRoomMatch]
                                                           |
                                                           v
                            [TournamentRoomMatchCompleted + AdvancementResolved]
                                                           |
                                                           v
                       [Room ranking for top-3 advancement computed by order:]
                       1) higher match_wins
                       2) lower cumulative card-point burden
                       3) lower cumulative cards remaining
                       Notes:
                       - if active players <=3, all active advance
                       - forfeited players rank below all active players
                                                           |
                                                           v
                     <All required room outcomes for current round resolved?>
                        |no                                         |yes
                        v                                           v
          [Keep processing room outcomes]                 [RoundCompleted]
                                                                   |
                                                                   v
                                                     [NextRoundInitialized]
                                                                   |
                                                                   v
                                                       [Repeat round loop]
                                                                   |
                                                                   v
                                            <Active players <= 10 (final threshold)?>
                                               |no                           |yes
                                               v                             v
                                          [Continue rounds]      [Create Final Room]
                                                                          |
                                                                          v
                                                            [Final room match completes]
                                                                          |
                                                                          v
                                                               [TournamentCompleted]
                                                                          |
                                                                          v
                                                  [Ranking consumes TournamentCompleted]
                                                                          |
                                                                          v
                                                        [TournamentPlacementEloUpdated]
```

---

## 4) Admin/Dispute Side Flow (Cross-Cutting)

```text
[Player/Spectator flags completed game]
        |
        v
[Admin review]
        |
        v
<Result valid?>
   |yes                             |no
   v                                v
[No change]                 [GameResultVoidedByAdmin or Override]
                                     |
                                     v
                              [Ranking compensation]
                                     |
                                     v
                           [EloAdjustmentReverted emitted]
```

