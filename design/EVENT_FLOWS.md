# UnoArena - Domain Event Flow Narratives

This document captures end-to-end event narratives required by the assignment.
Each flow shows synchronous decisions and asynchronous propagation.

---

## 1. Room Creation to Completion (Casual)

1. Player submits `JoinQuickPlayQueue`.
2. Matchmaking groups candidates by region then Elo.
3. `RoomCreated` and `PlayersAssignedToRoom`.
4. Lobby threshold reached:
  - `LobbyCountdownStarted`.
  - optional `LobbyCountdownShortened` when room fills to max.
5. Timer expires with enough players:
  - `GameStarted`.
6. Gameplay loop:
  - repeated `CardPlayed` / `CardDrawn` / `TurnAdvanced`.
  - optional `UnoCalled`, `UnoChallengeResolved`, `WildDrawFourChallengeResolved`.
  - optional `PlayerDisconnected`, `PlayerReconnected`, `PlayerForfeited`.
7. Terminal condition:
  - `GameCompleted` with final placements and scores.
8. Async projection updates:
  - Spectator projection updates.
  - Ranking consumes `GameCompleted` and emits `CasualEloUpdated`.

---

## 2. Tournament Round Advancement (Bo3 Rooms)

1. Tournament starts:
  - `TournamentStarted`
  - `RoundStarted`
2. Orchestration creates rooms and assigns qualifiers:
  - `TournamentRoomCreated`
  - `PlayersAssignedToRoom`
3. Room begins Bo3 match:
  - `TournamentMatchInitialized`
4. For each completed game:
  - `TournamentGameResultRecorded`
  - `MatchWinAwarded`
5. Match terminal path:
  - Early end path: `MatchEndedEarlyAtTwoWins`
  - Full-length path: `MatchEndedAfterGameThree`
  - Exceptional path: `TournamentMatchTimeoutReached`
6. Match finalized:
  - `TournamentMatchCompleted`
  - `AdvancementResolved` (top 3 by ranking rules)
7. Round transition:
  - `RoundCompleted`
  - `NextRoundInitialized` (if not final)
8. Final round completion:
  - `TournamentCompleted`

---

## 3. Elo and Ranking Update After Completion

### 3.1 Casual
1. `GameCompleted` published from Room Gameplay.
2. Ranking validates event integrity and dedups by event id.
3. Ranking computes placement-based Elo delta.
4. Ranking persists rating history and current value.
5. `CasualEloUpdated` published.

### 3.2 Tournament
1. `TournamentCompleted` published from Tournament Orchestration.
2. Ranking checks cancellation/void status.
3. Ranking computes tournament-placement Elo from final placement.
4. Ranking persists rating history and current value.
5. `TournamentPlacementEloUpdated` published.

---

## 4. Flow Risks and Validation Hooks

- Every terminal event must include immutable placement snapshot.
- Every event consumer must be idempotent by event id.
- Projection lag must not mutate source-of-truth ordering.

