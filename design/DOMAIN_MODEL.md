# UnoArena - Aggregates, Entities, and Value Objects

This document defines consistency boundaries and core domain model structure.

---

## 1. Aggregate Catalog

| Aggregate | Context | Consistency Boundary | Key Invariants |
|---|---|---|---|
| `GameSession` | Room Gameplay | One game instance and its state transitions | legal turns only, legal card plays only, one terminal outcome |
| `Room` | Room Gameplay | Lobby and game lifecycle inside a room | room state progression is valid; active player count constraints hold |
| `Tournament` | Tournament Orchestration | Full tournament lifecycle | round transitions valid; one champion only; cancel semantics consistent |
| `TournamentRoomMatch` | Tournament Orchestration | Bo3 match state in one tournament room | `match_wins` progression valid; early end at 2 wins; top-3 advancement deterministic |
| `PlayerProfile` | Ranking / Identity | Player statistical and rating identity | rating history append-only; profile references valid account |
| `Session` | Identity/Session | Active login session ownership | single active session per player invariant enforced |

---

## 2. Entity Model (Initial)

### 2.1 `GameSession` entities
- `PlayerSeat`
- `DeckState`
- `DiscardState`
- `TurnState`
- `PenaltyState`
- `ChallengeState`

### 2.2 `Tournament` entities
- `Round`
- `TournamentRoom`
- `QualifierPool`
- `AdvancementBucket`

### 2.3 `TournamentRoomMatch` entities
- `MatchParticipant`
- `GameResultSnapshot`
- `MatchStanding`

---

## 3. Value Object Catalog (Initial)

- `Card`
- `Color`
- `CardSymbol`
- `PlayerId`
- `RoomId`
- `TournamentId`
- `RoundNumber`
- `Placement`
- `Score`
- `CardPointBurden`
- `CardsRemainingCount`
- `StateVersion`
- `IdempotencyKey`
- `Timestamp`
- `Region`
- `TimerWindow`

---

## 4. Invariant Ownership Details

### 4.1 Gameplay invariants
- A card play must match legal play rules or be rejected.
- Turn actions respect turn ownership except jump-in rule.
- No player performs more than one normal action per turn.

### 4.2 Tournament match invariants
- `match_wins` starts at `0` for active players.
- Bo3 ends early if any active player reaches `2` wins.
- If no active player reaches 2 wins by end of Game 2, Game 3 must be played.
- Final ranking is deterministic by metric order:
1. higher `match_wins`
2. lower cumulative card-point burden
3. lower cumulative cards remaining

### 4.3 Forfeit invariants
- Forfeit is permanent for current game/match participation.
- Forfeited players rank below active players in final match standings.
- If active players become `<= 3` in tournament room, all active players advance.

---

## 5. Modeling Decisions Pending

1. Deterministic fallback when all ranking metrics tie at top-3 cutoff.
2. Whether tie-break metrics include all played match games or only games where tied players remained active.
3. Exact snapshot policy for timeout-terminated game result and match-level carryover.

