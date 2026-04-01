# UnoArena - Commands and Domain Events Catalog

This document is the command-to-event contract baseline.
It defines causality and idempotency expectations across contexts.

---

## 1. Global Command Semantics

- Every write command includes:
  - `command_id` (idempotency key UUID)
  - `expected_state_version` when applicable
  - authenticated `actor_id`
  - server timestamp on acceptance
- Duplicate `command_id` returns original outcome.
- Mismatched `expected_state_version` returns conflict with no state mutation.

---

## 2. Room Gameplay Commands and Events

| Command | Aggregate | Preconditions | Success events | Rejection outcomes |
|---|---|---|---|---|
| `JoinQuickPlayQueue` | `Room` | player authenticated, not in active game | `PlayerQueuedForCasualMatch` | already queued, suspended |
| `LeaveQuickPlayQueue` | `Room` | player currently queued | `PlayerRemovedFromQueue` | not queued |
| `SubmitPlayCard` | `GameSession` | actor owns turn or valid jump-in, card legal | `CardPlayed`, `TurnAdvanced` (or chain events) | stale version, illegal card, not actor turn |
| `SubmitDrawCard` | `GameSession` | actor owns turn, draw allowed | `CardDrawn`, `TurnEnded`, `TurnAdvanced` | stale version, not actor turn |
| `CallUno` | `GameSession` | caller has one card after play window conditions | `UnoCalled` | invalid timing |
| `ChallengeUno` | `GameSession` | active challenge window open | `UnoChallengeResolved` | window closed, duplicate challenge |
| `ChallengeWildDrawFour` | `GameSession` | actor is required victim, in challenge window | `WildDrawFourChallengeResolved` | invalid actor, window closed |
| `ForfeitGame` | `GameSession` | actor active in game | `PlayerForfeited`, `GameAutoResolvedIfNeeded` | already forfeited |

---

## 3. Tournament Commands and Events

| Command | Aggregate | Preconditions | Success events | Rejection outcomes |
|---|---|---|---|---|
| `RegisterForTournament` | `Tournament` | registration open, eligible player | `TournamentRegistrationConfirmed` | closed window, duplicate registration |
| `StartTournament` | `Tournament` | admin actor, min players satisfied | `TournamentStarted`, `RoundStarted` | insufficient players, unauthorized |
| `AssignPlayersToRoundRooms` | `Tournament` | round open, qualifiers available | `TournamentRoomCreated`, `PlayersAssignedToRoom` | round locked |
| `RecordTournamentGameResult` | `TournamentRoomMatch` | game completed, result not already recorded | `TournamentGameResultRecorded`, `MatchWinAwarded` | duplicate result, invalid game reference |
| `FinalizeTournamentRoomMatch` | `TournamentRoomMatch` | Bo3 end condition reached or timeout/forfeit terminal | `TournamentRoomMatchCompleted`, `AdvancementResolved` | match not terminal |
| `AdvanceRound` | `Tournament` | all required room outcomes resolved | `RoundCompleted`, `NextRoundInitialized` | unresolved rooms |
| `CompleteTournament` | `Tournament` | final room complete | `TournamentCompleted` | tournament not terminal |
| `CancelTournament` | `Tournament` | admin actor, tournament active | `TournamentCancelled` | unauthorized, already complete |

---

## 4. Ranking Commands and Events

| Trigger (event-driven) | Aggregate | Preconditions | Output events |
|---|---|---|---|
| `GameCompleted` | `PlayerProfile` | casual game valid and non-void | `CasualEloUpdated` |
| `TournamentCompleted` | `PlayerProfile` | tournament final placement available and not cancelled | `TournamentPlacementEloUpdated` |
| `GameResultVoidedByAdmin` | `PlayerProfile` | prior rating adjustment exists | `EloAdjustmentReverted` |

---

## 5. Bo3 Event Set (Minimum)

- `TournamentMatchInitialized`
- `TournamentGameResultRecorded`
- `MatchWinAwarded`
- `MatchEndedEarlyAtTwoWins`
- `MatchEndedAfterGameThree`
- `TournamentMatchTimeoutReached`
- `TournamentMatchCompleted`
- `AdvancementResolved`

---

## 6. Open Event Contract Tasks

1. Lock payload schema for each event (required/optional fields).
2. Define partition keys for event ordering guarantees per aggregate.
3. Document replay behavior for projection rebuilds and late consumers.

