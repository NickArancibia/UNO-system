# UnoArena — Bounded Contexts & Context Map

This document defines the six bounded contexts of UnoArena, their responsibilities, their relationships, and the events and data that cross each boundary. All terms follow [GLOSSARY.md](./GLOSSARY.md).

---

## 1. Bounded Contexts Overview

```
                    ┌─────────────────────────────────────────────────────────┐
                    │  Identity / Session  (upstream to all)                  │
                    └───┬──────────────────────────────────────┬──────────────┘
          player valid  │                                       │  player valid
          + session     │                          ┌────────────▼──────────────┐
          invalidated   │                          │  Moderation / Admin       │
                        │                          │  (issues corrective       │
                        │            ◀─────────────┤   commands upstream;      │
                        │            SuspendPlayer  │   audit log; observes     │
                        │            BanPlayer      │   all contexts)           │
                        │                          └────────────┬──────────────┘
                        │                   TournamentCancelled │ GameResultVoided
                        │                                       │
          ┌─────────────▼───────────────┐   ◀game events────────┘
          │      Room Gameplay          │◀───────────────────────────────────┐
          │  (upstream core;            │                                    │
          │   game state owner)         │──────room created/result──────────▶│
          └──────┬─────────────┬────────┘                                   │
    game events  │             │  GameCompleted             ┌────────────────┴──────┐
                 │             │  PlayerForfeited           │ Tournament             │
                 ▼             └───────────────────────────▶│ Orchestration         │
        ┌────────────────┐                                  │ (round logic,         │
        │ Spectator View │◀──match/bracket events───────────┤  match tracking,      │
        │ (read-only;    │                                  │  advancement)         │
        │  privacy ACL)  │                                  └──────────┬────────────┘
        └────────────────┘                                             │ TournamentCompleted
                                                                       │
                                                          ┌────────────▼────────────┐
                                                          │        Ranking          │
                                                          │  (Elo updates;          │
                                                          │   leaderboards)         │
                                                          └─────────────────────────┘
```
**Arrow guide:** `──▶` event/data flow (downstream); `◀──` corrective command issued upstream.

---

## 2. Context Definitions & Responsibilities

### 2.1 Room Gameplay

**Role:** Upstream core. The authoritative owner of all in-game state.

**Responsibilities:**
- Owns the `GameSession`, `Room`, and `MatchmakingQueue` aggregates. Tournament queue membership is **not** owned here — it is managed by `TournamentRound.qualifier_pool` in Tournament Orchestration.
- Enforces all UNO rules: legal play validation, turn order, special card effects, Draw Two stacking, jump-in, draw pile exhaustion.
- Manages the `state version` and rejects stale commands with conflict responses.
- Enforces idempotency via `idempotency key` on all game commands.
- Runs all server-side timers: turn timer (45s), challenge windows (5s), combined window.
- Manages disconnection detection: triggers the reconnection window, skips turns, triggers AFK forfeits.
- Produces the immutable game log (all events appended before broadcast).
- Produces domain events consumed by Ranking, Spectator View, and Tournament Orchestration.

**Does NOT own:**
- Player identity or session validity (delegates to Identity/Session).
- Tournament progression logic (delegates to Tournament Orchestration).
- Elo calculation (delegates to Ranking).
- Spectator filtering (delegates to Spectator View).

**Local term nuances:**
- `placement` = finish rank within a single game (1st through last).
- `forfeit` = player is removed from the current game; their hand is discarded.
- `winner` = the first player to empty their hand.

---

### 2.2 Tournament Orchestration

**Role:** Downstream from Room Gameplay; upstream to Ranking for tournament results.

**Responsibilities:**
- Owns the `Tournament`, `TournamentRound`, and `Match` aggregates.
- Manages tournament lifecycle: registration, round sequencing, phase-start thresholds, Final Room creation.
- Drives matchmaking for tournament rooms: assembles qualifiers into rooms, triggers lobby timers.
- Tracks Bo3 match state: `match_wins`, game sequence, early-end detection (2 wins reached).
- Applies the 20-minute match timeout: resolves the active game on timeout and freezes advancement.
- Computes room placement using match wins → cumulative card-point burden → cumulative cards remaining.
- Determines advancement: top 3 per room; all active players if ≤ 3 remain.
- Handles no-show forfeits before game start and lone-qualifier auto-advancement.
- Emits tournament-level events: `RoundStarted`, `MatchCompleted`, `AdvancementResolved`, `TournamentCompleted`.

**Does NOT own:**
- Individual game state (owned by Room Gameplay).
- Elo calculation (delegates to Ranking after tournament completion).
- Casual matchmaking (separate flow).

**Local term nuances:**
- `placement` = finish rank within a room at match end (used for advancement).
- `forfeit` = permanent tournament elimination, not just game removal.
- `qualifier` = one of the top 3 players advancing from a room (not called "winner").
- `Tournament Champion` = the sole winner of the Final Room; the only "winner" in a tournament context.

---

### 2.3 Ranking

**Role:** Downstream from Room Gameplay (casual Elo) and Tournament Orchestration (tournament Elo).

**Responsibilities:**
- Owns the `EloRecord` aggregate (one per player; authoritative source for all Elo ratings) and the `Leaderboard` read model.
- Consumes `GameCompleted` events from Room Gameplay to update casual Elo.
- Consumes `TournamentCompleted` events from Tournament Orchestration to update tournament-placement Elo.
- Applies the placement-based multi-player Elo formula (see CONSTRAINTS.md Section 5.2 and TOURNAMENT_RULES.md Section 8).
- Maintains global casual leaderboard and tournament leaderboard.
- Applies the +3 points bonus for dominant score performance.
- Assigns last-place rank to forfeiting players for Elo calculation.
- Handles Elo reversal when an admin voids a game result.

**Does NOT own:**
- Game state or player hands (never needs them — only final placements and scores).
- Player profile identity (delegates to Identity/Session for profile lookups).

**Local term nuances:**
- `placement` = final rank used as input to Elo formula; scoped to casual game or full tournament.
- `score` = Elo delta (ΔR), not card-point score.

---

### 2.4 Identity / Session

**Role:** Upstream to all other contexts. All contexts depend on it for player identity validation.

**Responsibilities:**
- Owns the `PlayerProfile` and `PlayerSession` aggregates.
- Manages registration, login, and logout.
- Issues JWTs with `issued_at` timestamps; maintains one `valid_sessions_from` record per player.
- Enforces single-active-session invariant: new login invalidates the previous session.
- Notifies Room Gameplay of session invalidation so the reconnection window starts for any active game.
- Tracks player statistics: games played, win rate, cumulative points, tournaments won.
- Manages region assignment (self-selected at registration; immutable after 30 days without admin review).

**Does NOT own:**
- Game state or room lifecycle.
- Elo ratings (owned by the `EloRecord` aggregate in the Ranking context, linked to `PlayerProfile` by `player_id`).

**Published language (consumed by all other contexts):**
- `PlayerRegistered`, `SessionCreated`, `SessionInvalidated`, `PlayerSuspended`
- Player ID is the shared identifier used across all contexts.

---

### 2.5 Spectator View

**Role:** Downstream read-only projection context. Receives events from Room Gameplay and Tournament Orchestration.

**Responsibilities:**
- Maintains a filtered, real-time read model of every active game, suitable for public consumption.
- Strips all private data before exposing state: **no player's card identities are ever included**.
- Exposes: player names, hand counts (not card identities), discard pile (full history), draw pile size, turn order, current direction, scores, all game events (plays, draws, penalties, Uno calls, challenge outcomes), match progress.
- Serves spectator connections: any number of spectators may subscribe to any room at any time, including mid-game.
- Does NOT interact with game state — spectators cannot submit commands.

**Privacy contract (what is withheld and why):**

| Information | Withheld? | Reason |
|---|---|---|
| Card identities in any player's hand | **Yes** | Core game rule: hands are always private during play |
| Wild Draw Four accused player's hand | **Yes** | Revealed server-side only; enters public game log post-game |
| Hand counts (number of cards per player) | No | Public information; all players can see it |
| Discard pile (top card + full history) | No | Public information |
| Draw pile size | No | Public information |
| Turn order and current direction | No | Public information |
| Game events (plays, draws, Uno calls, etc.) | No | Public game stream |
| Scores and placements | No | Public information |

**Events consumed from Room Gameplay:**
`RoomCreated`, `RoomStatusChanged`, `PlayerAssignedToRoom`, `GameStarted`, `GameCompleted`, `CardPlayed`, `CardDrawn`, `TurnAdvanced`, `DirectionReversed`, `PlayerSkipped`, `DrawTwoStacked`, `WildDrawFourActivated`, `PenaltyCardsDrawn`, `UnoCallMade`, `UnoChallengeResolved`, `WildDrawFourChallengeResolved`, `PlayerDisconnected`, `PlayerReconnected`, `PlayerForfeited`

**Events consumed from Tournament Orchestration:**
`MatchStarted`, `GameInMatchStarted`, `MatchCompleted`, `MatchTimeoutReached`, `AdvancementResolved`

**Anti-corruption layer:** Spectator View applies a strict whitelist filter to all incoming events before storing or broadcasting them. Any field not on the whitelist is dropped regardless of what Room Gameplay emits. This prevents accidental hand exposure from upstream changes.

---

### 2.6 Moderation / Admin

**Role:** Downstream from all contexts. Observes the entire system; does not own game state.

**Responsibilities:**
- Owns the `AdminAction` aggregate and the audit log.
- Allows admins to create, schedule, and cancel tournaments (commands forwarded to Tournament Orchestration).
- Allows admins to review flagged games and void or override results (commands forwarded to Room Gameplay / Ranking).
- When a game is voided: emits `GameResultVoided`, consumed by Ranking to reverse Elo changes.
- When a tournament is cancelled: emits `TournamentCancelled`, consumed by Tournament Orchestration and Ranking (no Elo applied for any game in the tournament).
- Manages rate-limit escalation: consumes `PlayerAbuseWarningIssued` and `PlayerSessionSuspended` events, escalates to permanent ban review after repeated suspensions.
- All admin actions are recorded in the audit log before taking effect.

**Does NOT own:**
- Game state, room lifecycle, or Elo calculations (delegates to respective contexts via commands).

---

## 3. Context Relationships

```
Identity/Session ──────────────────────────────────────────────────────────┐
     (upstream, published language: player identity, session validity)      │
          │                                                                  │
          ▼                                                                  │
Room Gameplay ──────────────────────────────────────────────────────────────┤
     (upstream core: game events flow downstream)                           │
          │                                                                  │
          ├──▶ Spectator View        (downstream, conformist: consumes      │
          │                           Room Gameplay events as-is with        │
          │                           privacy filter applied)                │
          │                                                                  │
          ├──▶ Ranking               (downstream: consumes GameCompleted     │
          │                           for casual Elo updates)                │
          │                                                                  │
          └──▶ Tournament Orchestration (peer: Room Gameplay runs games      │
                    │               inside tournament rooms; Tournament      │
                    │               Orchestration drives round logic)        │
                    │                                                        │
                    ├──▶ Ranking    (downstream: consumes TournamentCompleted│
                    │               for tournament Elo updates)              │
                    │                                                        │
                    └──▶ Spectator View (downstream: tournament bracket and  │
                                        match progress events)              │
                                                                             │
Moderation/Admin ◀──────────────────────────────────────────────────────────┘
     (downstream observer: issues commands back upstream via admin actions)
```

### Relationship Types

| Relationship | Type | Notes |
|---|---|---|
| Identity/Session → Room Gameplay | **Upstream / Downstream** | Room Gameplay conforms to Identity/Session's player model. Session invalidation triggers reconnection window. |
| Identity/Session → Tournament Orchestration | **Upstream / Downstream** | Tournament Orchestration uses player IDs from Identity/Session for qualifier tracking. |
| Room Gameplay → Spectator View | **Published Language + ACL** | Spectator View applies an anti-corruption layer (whitelist filter) to prevent private data leakage. |
| Room Gameplay → Ranking | **Published Language** | Ranking consumes `GameCompleted` events; no ACL needed — event payload is already public. |
| Room Gameplay → Tournament Orchestration | **Partnership** | Both contexts must collaborate on tournament room lifecycle: Tournament Orchestration creates rooms, Room Gameplay runs games inside them, and emits results back. |
| Tournament Orchestration → Ranking | **Published Language** | Ranking consumes `TournamentCompleted`; tournament Elo is computed once post-tournament. |
| Tournament Orchestration → Spectator View | **Published Language** | Bracket and match progress events flow to Spectator View for tournament display. |
| Moderation/Admin → all contexts | **Downstream Observer + Conformist** | Admin observes events from all contexts; issues corrective commands (void, cancel) back upstream. Admin conforms to each context's command model. |
| Identity/Session → Moderation/Admin | **Upstream / Downstream** | Admin users require authenticated sessions issued by Identity/Session. Moderation conforms to the same session model as all other contexts. |
| Moderation/Admin → Identity/Session | **Downstream → Upstream (corrective command)** | When abuse escalation reaches a ban, Moderation issues a `SuspendPlayer` or `BanPlayer` command to Identity/Session, which invalidates the session and locks the account. |

---

## 4. Cross-Context Event Contracts

The table below highlights the most notable events that cross context boundaries, with emphasis on privacy-sensitive payloads and multi-consumer flows. It is not exhaustive — the authoritative per-event detail (payload fields, all downstream consumers, idempotency behavior) is in [COMMANDS_EVENTS.md](./COMMANDS_EVENTS.md).

| Event | Producer | Consumers | Privacy-sensitive? |
|---|---|---|---|
| `RoomCreated` | Room Gameplay | Spectator View | No |
| `RoomStatusChanged` | Room Gameplay | Spectator View | No |
| `PlayerAssignedToRoom` | Room Gameplay | Spectator View | No |
| `GameStarted` | Room Gameplay | Spectator View, Tournament Orchestration | No |
| `GameCompleted` | Room Gameplay | Ranking, Spectator View, Tournament Orchestration | No (final placements and scores are public) |
| `CardPlayed` | Room Gameplay | Spectator View | No (card identity is public once played) |
| `CardDrawn` | Room Gameplay | Spectator View | **Yes** — drawn card identity withheld from spectators |
| `TurnAdvanced` | Room Gameplay | Spectator View | No |
| `DirectionReversed` | Room Gameplay | Spectator View | No |
| `PlayerSkipped` | Room Gameplay | Spectator View | No |
| `DrawTwoStacked` | Room Gameplay | Spectator View | No |
| `WildDrawFourActivated` | Room Gameplay | Spectator View | No |
| `PenaltyCardsDrawn` | Room Gameplay | Spectator View | **Yes** — penalty card identities withheld |
| `UnoCallMade` | Room Gameplay | Spectator View | No |
| `UnoChallengeResolved` | Room Gameplay | Spectator View | No |
| `WildDrawFourChallengeResolved` | Room Gameplay | Spectator View | **Yes** — hand composition withheld until post-game log |
| `PlayerDisconnected` | Room Gameplay | Spectator View, Tournament Orchestration | No |
| `PlayerReconnected` | Room Gameplay | Spectator View | No |
| `PlayerForfeited` | Room Gameplay | Spectator View, Tournament Orchestration, Ranking | No |
| `SessionInvalidated` | Identity/Session | Room Gameplay | No |
| `PlayerSuspended` | Identity/Session | Room Gameplay, Tournament Orchestration | No |
| `RoundStarted` | Tournament Orchestration | Spectator View | No |
| `TournamentRoomAssigned` | Tournament Orchestration | Spectator View | No |
| `MatchStarted` | Tournament Orchestration | Spectator View | No |
| `GameInMatchStarted` | Tournament Orchestration | Spectator View | No |
| `MatchCompleted` | Tournament Orchestration | Spectator View, Ranking (indirectly via TournamentCompleted) | No |
| `AdvancementResolved` | Tournament Orchestration | Spectator View | No |
| `TournamentCompleted` | Tournament Orchestration | Ranking | No |
| `EloUpdated` | Ranking | Spectator View | No |
| `TournamentCancelled` | Moderation/Admin | Tournament Orchestration, Ranking | No |
| `GameResultVoided` | Moderation/Admin | Ranking | No |
| `PlayerBanned` | Identity/Session (triggered by Moderation command) | Room Gameplay, Tournament Orchestration, Moderation/Admin (audit) | No |
