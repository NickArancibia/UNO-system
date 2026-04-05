# UnoArena — Edge Cases & Failure-Path Analysis

This document covers every required failure-path category from the assignment. For each scenario: the trigger, expected domain behavior, emitted events, and the invariant being protected. All terms follow [GLOSSARY.md](./GLOSSARY.md).

---

## 1. Concurrent Conflicting Actions

### 1.1 Two players simultaneously play a card
**Trigger:** Players A and B both submit `PlayCard` at the same `state_version: N`. Only one turn is active.

**Behavior:**
- The server serializes both commands. The first to arrive is validated against state version N — if it matches, it is accepted and state advances to N+1.
- The second command arrives with state_version N, but the server is now at N+1 → rejected with 409 Conflict.
- The losing client reconciles by consuming the event stream and retrying only if the action is still valid.

**Emitted events:** `CardPlayed`, `TurnAdvanced` (winner) — conflict response only (loser, no domain event).

**Invariant protected:** Only the active player's turn command may advance the game state.

---

### 1.2 Two players simultaneously attempt to jump in
**Trigger:** Players C (region `EU-W`) and D (region `AS-E`) both hold a card identical to the top of the discard pile and submit `JumpIn` at nearly the same moment. Both carry `state_version: N`. C's packet arrives 80ms before D's purely because C is closer to the server.

**Behavior (with RTT-adjusted race resolution):**
- Both submissions arrive within the 150ms race window — they are treated as a race, not as a clear sequential pair.
- Server computes effective submission times:
  - C: `arrival_C − RTT_C/2` (e.g., arrival at T+10ms, RTT 20ms → effective T+0ms)
  - D: `arrival_D − RTT_D/2` (e.g., arrival at T+90ms, RTT 200ms → effective T−10ms)
- D's effective time is earlier — D actually pressed the button first. D wins despite the later packet arrival.
- If effective times are within ±20ms of each other: server-side RNG picks the winner with equal probability.
- `RaceResolved` is appended to the game log before `JumpInOccurred`, recording both submissions, effective times, RTT values, and resolution method.
- Losing submission (C) is rejected with 409 Conflict; C's card remains in hand.

**Emitted events:** `RaceResolved {race_type: JumpIn, winner: D, resolution_method: EffectiveTimestamp}`, `JumpInOccurred`, card effects, `TurnAdvanced` — conflict response (C).

**Invariant protected:** At most one jump-in per turn cycle; turn order is unambiguous. Cross-region latency does not systematically advantage players closer to the server.

---

### 1.3 Two opponents simultaneously challenge Uno!
**Trigger:** Players B (region `NA-W`) and C (region `EU-E`) both submit `ChallengeUno` against Player A within the 5-second window, within milliseconds of each other.

**Behavior (with RTT-adjusted race resolution):**
- Both submissions arrive within the 150ms race window.
- Server computes effective submission times using each player's `LatencyProfile.rolling_rtt_ms`.
- The player with the earlier effective submission time wins the challenge right.
- If effective times are within ±20ms: server-side RNG resolves with equal probability.
- `RaceResolved` is appended to the game log before `UnoChallengeIssued`.
- Only one `UnoChallengeIssued` is emitted; one penalty outcome resolved; losing submission rejected with 409 Conflict.

**Emitted events:** `RaceResolved {race_type: UnoChallenge, winner: B or C, resolution_method: EffectiveTimestamp or RNG}`, `UnoChallengeIssued`, `UnoChallengeResolved`, `PenaltyCardsDrawn` — conflict response (loser).

**Invariant protected:** At most one Uno! challenge per window; one penalty outcome. Fairness preserved across regions.

---

### 1.4 Next player acts before Uno! window expires
**Trigger:** Player B (next player) submits `DrawCard` or `PlayCard` while the 5-second Uno! window is still open.

**Behavior:**
- B's action is a valid game action. Its arrival closes the Uno! challenge window early (the window closes the moment the next player begins their turn).
- If A had not yet called Uno!: A has escaped without penalty because the window closed without a successful challenge.
- B's action is then processed normally.

**Emitted events:** `ChallengeWindowClosed {reason: NextPlayerActed}`, then `CardPlayed`/`CardDrawn`, `TurnAdvanced`.

**Invariant protected:** The window is time-bound AND action-bound; once B acts the challenge opportunity is gone.

---

### 1.5 Simultaneous forfeit and game completion
**Trigger:** Player A plays their last card and Player B submits `Forfeit` at the exact same `state_version: N`.

**Behavior:**
- First to arrive wins serialization:
  - If `PlayCard` (A's last card) arrives first: `GameCompleted` emitted; B's `Forfeit` is then rejected (game is no longer `in_progress`).
  - If `Forfeit` (B) arrives first: B forfeited; game continues; A's `PlayCard` then completes the game normally.
- Either way the game reaches a determinate completion state.

**Emitted events (PlayCard first):** `CardPlayed`, `GameCompleted` — conflict response for Forfeit.
**Emitted events (Forfeit first):** `PlayerForfeited`, `CardPlayed`, `GameCompleted`.

**Invariant protected:** Game completion and forfeit cannot both apply to the same final state.

---

### 1.6 Jump-in during an active Draw Two stack
**Trigger:** A Draw Two stack is active (accumulated penalty: 4). Player E holds the identical Draw Two on top of the discard pile and submits `JumpIn`.

**Behavior:**
- Valid jump-in: E's Draw Two extends the stack (accumulated penalty becomes 6). Turn order resets from E's position. The original intended next player (F) is skipped.
- E's `JumpIn` is treated as both a jump-in and a stack response simultaneously.

**Emitted events:** `JumpInOccurred`, `DrawTwoStacked {accumulated_penalty: 6}`, `DrawTwoActivated {target: next player after E}`.

**Invariant protected:** Stack accumulation is consistent regardless of jump-in; turn order resets cleanly.

---

### 1.7 Non-eligible player attempts WD4 challenge
**Trigger:** Player C (not the next player in turn order) submits `ChallengeWildDrawFour`.

**Behavior:**
- `wd4_eligible_challenger` in the active `ChallengeWindow` is Player D (next player). C is not eligible.
- Command rejected immediately: submitter is not the eligible challenger.
- No state change; window remains open.

**Emitted events:** None (rejection response only).

**Invariant protected:** Only the player required to draw can challenge a WD4.

---

### 1.8 RTT measurement unavailable at race time
**Trigger:** Player E just reconnected to an active game 2 seconds ago — not enough heartbeat exchanges have completed to establish a reliable `LatencyProfile`. Player F (established session, full RTT data) submits `JumpIn` at the same moment as Player E.

**Behavior:**
- Both submissions arrive within the 150ms race window.
- Server checks `LatencyProfile.measurement_available` for each submitter:
  - F: `measurement_available: true` — effective time computable.
  - E: `measurement_available: false` — effective time cannot be reliably computed.
- Because at least one participant lacks a valid RTT measurement, the server **falls back to RNG** regardless of F's computed effective time. Both submissions receive equal probability.
- `RaceResolved` is emitted with `resolution_method: RNG`; the per-submission entry for E records `rtt_available: false`.

**Emitted events:** `RaceResolved {resolution_method: RNG, submissions: [{player: F, rtt_available: true, ...}, {player: E, rtt_available: false}]}`, then winner's action proceeds normally.

**Invariant protected:** A player cannot gain an advantage by deliberately triggering reconnection to invalidate their RTT profile. RNG fallback is no worse than the pre-RTT model, and the audit log makes the reason transparent.

---

## 2. Disconnections & Late Rejoin Attempts

### 2.1 Player disconnects and reconnects within the window
Covered in detail in [EVENT_FLOWS.md — Flow 4, Phase A–B](./EVENT_FLOWS.md).

**Key behavior:** Turns skipped; AFK counter does not accumulate; hand preserved; turn resumes at next opportunity after reconnection.

---

### 2.2 Player disconnects; reconnection window expires
Covered in [EVENT_FLOWS.md — Flow 4, Phase C](./EVENT_FLOWS.md).

**Key behavior:** `ReconnectionWindowExpired` triggers automatic `PlayerForfeited`. Hand discarded. Tournament players permanently eliminated.

---

### 2.3 Late rejoin attempt after forfeit already issued
**Trigger:** Player B's reconnection window expired 10 seconds ago. B now submits `ReconnectToGame`.

**Behavior:**
- `PlayerSession` has no open `ReconnectionWindow` for B (it is closed, forfeit already issued).
- `ReconnectToGame` rejected: no active reconnection window for this player/game combination.
- B may still connect as a spectator to observe the game.

**Emitted events:** None (rejection response).

**Invariant protected:** Forfeit is permanent and irreversible once issued.

---

### 2.4 Player disconnects exactly when it is their turn
**Trigger:** The server detects Player B's disconnection at the moment `TurnAdvanced` points to B.

**Behavior:**
- `PlayerDisconnected` emitted; `ReconnectionWindowStarted` for B.
- B's turn is skipped immediately — the 45-second turn timer does NOT run for a disconnected player.
- `TurnAdvanced` skips to the next active connected player.
- AFK counter does NOT increment.

**Emitted events:** `PlayerDisconnected`, `ReconnectionWindowStarted`, `TurnAdvanced {skipping: B}`.

**Invariant protected:** Disconnected players cannot be AFK-forfeited; their turns are neutrally skipped.

---

### 2.5 Player disconnects during their active challenge window obligation
**Trigger:** Player D is the `wd4_eligible_challenger` (must decide to challenge or draw within 5 seconds) and disconnects mid-window.

**Behavior:**
- Server-side timer continues running regardless of D's connection state.
- If window expires without a challenge: WD4 effect resolves by inaction — D must draw 4 cards (same as if D chose not to challenge). D's reconnection window starts.
- D's draws are processed server-side; D's hand count updated.
- When D reconnects: full state snapshot includes the 4 penalty cards in D's hand.

**Emitted events:** `PlayerDisconnected`, `ReconnectionWindowStarted`, `ChallengeWindowClosed {reason: Expired}`, `PenaltyCardsDrawn {player_id: D, count: 4}`, `TurnAdvanced`.

**Invariant protected:** Server-side timers are authoritative; client connection state does not freeze domain time.

---

### 2.6 No-show in tournament lobby
**Trigger:** Player P7 is assigned to tournament room R-3-042 but is not present (disconnected or never reconnected) when the lobby timer fires.

**Behavior:**
- When the lobby timer expires, the server checks presence of all assigned players.
- P7 is absent → P7 is forfeited before the game begins; treated as if they explicitly forfeited during play.
- P7 is permanently eliminated from the tournament.
- Game starts with remaining players (minimum 2 required; if only 1 remains after no-shows, that player auto-advances).

**Emitted events:** `PlayerForfeited {player_id: P7, reason: NoShow}`, `GameStarted` (with remaining players).

**Invariant protected:** Empty seats do not stall or distort game start; tournament elimination is consistent with in-game forfeit behavior.

---

### 2.7 Multiple disconnections within a single game
**Trigger:** Player C disconnects and reconnects three times during the same game.

**Behavior:**
- Each disconnection starts a fresh 60-second `ReconnectionWindow`.
- Each reconnection within the window closes it; turns resume; AFK counter resets.
- AFK counter only accumulates for connected players with expired turn timers — disconnection periods are excluded entirely.
- No cap on the number of reconnection cycles per game; this is by design.

**Emitted events:** Repeated `PlayerDisconnected`, `ReconnectionWindowStarted`, `PlayerReconnected`, `ReconnectionWindowClosed` cycles.

**Invariant protected:** Disconnection handling is stateless per-window; prior cycles do not influence current window.

---

## 3. Stale Commands & Replayed Commands

### 3.1 Stale command (outdated state_version)
**Trigger:** Client A submits `PlayCard {state_version: 5}` but the server's current version is 7.

**Behavior:**
- Command rejected with 409 Conflict immediately.
- Client consumes events from version 6 and 7 via the event stream to reconcile current state.
- Client re-evaluates: is the intended card still in hand? Is it still their turn? Is it still a legal play?
- If still valid, client resubmits with `state_version: 7`.

**Emitted events:** None (conflict response only).

**Invariant protected:** No command may act on a state it has not observed; serialization is enforced.

---

### 3.2 Replayed command (duplicate idempotency key)
**Trigger:** Client A submitted `PlayCard {idempotency_key: uuid-88}` which was accepted. Due to a network timeout, the client retries with the same `uuid-88`.

**Behavior:**
- Server finds `uuid-88` in its idempotency cache.
- Returns the original outcome (the `CardPlayed` event payload) without reprocessing.
- State version is NOT incremented again; no duplicate event emitted.

**Emitted events:** None new (cached response returned).

**Invariant protected:** At-least-once delivery does not cause duplicate state changes.

---

### 3.3 Command arrives after game has ended
**Trigger:** Client A submits `PlayCard` but the game has already transitioned to `completed` (they missed the `GameCompleted` event).

**Behavior:**
- Command rejected: game is not `in_progress`.
- Client reconciles via event stream and discovers `GameCompleted`; no retry needed.

**Emitted events:** None.

**Invariant protected:** Completed games are immutable.

---

### 3.4 Challenge command arrives after window closed
**Trigger:** Player B submits `ChallengeUno` 6 seconds after the card was played — the 5-second window has expired.

**Behavior:**
- No active `ChallengeWindow` in the `GameSession`.
- Command rejected: no open challenge window.
- Player A retains their one-card hand with no penalty (window expired cleanly).

**Emitted events:** None.

**Invariant protected:** Challenge windows are strictly time-bounded; late challenges have no effect.

---

### 3.5 Command submitted by a forfeited player
**Trigger:** Player C was AFK-forfeited 2 turns ago but their client (which missed the event) submits `PlayCard`.

**Behavior:**
- `PlayerHand` for C no longer exists in the `GameSession`; C is not in the active players list.
- Command rejected: player is not an active participant in this game.
- Client reconciles via event stream and discovers `PlayerForfeited`.

**Emitted events:** None.

**Invariant protected:** Forfeited players have no game presence and cannot act.

---

### 3.6 Duplicate forfeit submission
**Trigger:** Player D submits `Forfeit` twice (network retry with the same `idempotency_key`).

**Behavior:**
- First submission: accepted, `PlayerForfeited` emitted.
- Second submission: idempotency cache returns original outcome; no second forfeit processed.

**Emitted events:** `PlayerForfeited` (once only).

**Invariant protected:** Forfeit is idempotent; duplicate submissions are harmless.

---

## 4. Partial Failures Between Contexts

### 4.1 Ranking context unavailable when GameCompleted emitted
**Trigger:** A casual game completes and `GameCompleted` is emitted, but the Ranking context consumer is temporarily down.

**Behavior:**
- Event delivery is retried (at-least-once delivery assumption).
- Game result and room state are unaffected — Room Gameplay does not wait for Ranking.
- When Ranking recovers, it processes `GameCompleted`; its consumer is idempotent (checks whether Elo for this `game_id` was already applied before updating).
- If the event is delivered twice: second processing is a no-op.

**Emitted events (when Ranking recovers):** `EloUpdated` for each player — same as the happy path.

**Invariant protected:** Elo update eventual consistency; game result integrity is independent of Ranking availability.

---

### 4.2 Tournament Orchestration misses GameCompleted for a match game
**Trigger:** Game G2 in match M-3-001 completes, but the Tournament Orchestration event consumer drops the `GameCompleted` message.

**Behavior:**
- Match M-3-001 does not advance (no `MatchWinAwarded` emitted for G2's winner).
- Event is retried; Match eventually processes it idempotently.
- If the 20-minute match timeout fires before the event is redelivered: timeout resolution takes over — it resolves the active game using current hand state and terminates the match.
- The timeout acts as a safety net against indefinite stalls.

**Emitted events (timeout path):** `MatchTimeoutReached`, `GameCompleted` (timeout-resolved), `MatchCompleted`, `AdvancementResolved`.

**Invariant protected:** Match progression is never permanently blocked; timeout bounds the worst-case delay.

---

### 4.3 Spectator View falls behind the event stream
**Trigger:** High event throughput causes Spectator View to lag; spectators see a state that is 2–3 events behind the live game.

**Behavior:**
- No game invariant is affected; Spectator View is a read-only projection.
- `PublicGameView` catches up as events are processed in order.
- Spectators experience a brief display lag but receive all events eventually (ordered by state version).
- Players are unaffected — their authoritative view comes from the `GameSession` event stream directly.

**Emitted events:** None new; existing events eventually processed.

**Invariant protected:** Read model lag does not affect game state consistency.

---

### 4.4 Room created in Tournament Orchestration but RoomCreated event lost
**Trigger:** Tournament Orchestration assigns players to a room and emits `TournamentRoomAssigned`, but `RoomCreated` fails to reach Room Gameplay.

**Behavior:**
- Room Gameplay has no record of the room; it cannot start a game.
- Tournament Orchestration retries room creation via its own recovery mechanism (e.g., after a timeout with no `GameStarted` confirmation).
- Room Gameplay uses the `room_id` as an idempotency key for room creation — duplicate `RoomCreated` commands are no-ops.

**Emitted events (on retry):** `RoomCreated`, `PlayerAssignedToRoom` (all players), `LobbyTimerStarted`.

**Invariant protected:** Rooms are eventually created exactly once per tournament round assignment.

---

### 4.5 TournamentCancelled arrives at Ranking after Elo already applied for several games
**Trigger:** A tournament is cancelled mid-round. Ranking has already applied `EloUpdated` for 15,000 completed games within the tournament.

**Behavior:**
- `TournamentCancelled` consumed by Ranking.
- Ranking queries its event log for all `EloUpdated` events tagged with `tournament_id: T1`.
- Issues `EloReverted` for each affected player in each affected game — reverting to the pre-game Elo value.
- This is a compensating operation; Ranking processes it idempotently (tracks which game IDs have been reverted).

**Emitted events:** `EloReverted` × (number of players × number of completed games in the tournament).

**Invariant protected:** No Elo changes persist from a cancelled tournament.

---

### 4.6 AdvancementResolved emitted but TournamentRound crashes before RoundCompleted
**Trigger:** 28 of 30 rooms in Round 3 have emitted `AdvancementResolved`, but the TournamentRound aggregate crashes before processing the last 2.

**Behavior:**
- On recovery, TournamentRound replays its event log.
- `AdvancementResolved` events already processed are detected via their idempotency keys — skipped.
- The 2 remaining rooms' `MatchCompleted` events are reprocessed; `AdvancementResolved` emitted.
- `RoundCompleted` emitted once all 30 rooms are confirmed.

**Emitted events (recovery):** `AdvancementResolved` (×2 remaining rooms), `RoundCompleted`.

**Invariant protected:** Round completion is idempotent; partial progress survives crashes.

---

## 5. Security & Abuse Scenarios

### 5.1 Session takeover via stolen JWT
**Trigger:** An attacker obtains Player A's JWT token and attempts to use it.

**Behavior:**
- Server validates JWT signature (stateless check) — passes if token is not tampered with.
- Server reads `valid_sessions_from` for Player A.
- If the token's `issued_at` < `valid_sessions_from`: token is rejected (player has logged in since this token was issued).
- If the token is still valid (attacker captured a very recent token): the attacker can act as Player A until Player A logs in again, at which point the attacker's token is invalidated.
- **Mitigation:** Player A logging in from any device immediately invalidates all prior sessions, including the attacker's. Player A is informed of the new session on login.

**Emitted events (on A's re-login):** `SessionCreated`, `SessionInvalidated` (invalidates attacker's token).

**Invariant protected:** Single-session enforcement bounds the window of a session takeover.

---

### 5.2 Command injection / malformed game commands
**Trigger:** A client submits `PlayCard {card: {color: "Purple", type: "Explode", value: 999}}` or other structurally invalid input.

**Behavior:**
- Input is validated at the system boundary before reaching the domain.
- Rejected with 400 Bad Request; no command reaches the `GameSession` aggregate.
- No domain event emitted; no state change.

**Emitted events:** None.

**Invariant protected:** Domain aggregates only process structurally valid, schema-conformant commands.

---

### 5.3 Player attempts to play out of turn (not a jump-in)
**Trigger:** Player C submits `PlayCard` when it is Player B's turn and the card does not qualify as a jump-in.

**Behavior:**
- `GameSession` validates: `turn_index` does not point to C.
- Command rejected: not the player's turn.
- No state change.

**Emitted events:** None.

**Invariant protected:** Turn ownership is strictly enforced by turn_index.

---

### 5.4 Rate limit flooding — game action spam
**Trigger:** Player D submits 40 game-action commands within one minute (limit: 30/min).

**Behavior:**
- Commands 1–30: processed normally (or rejected by game logic if invalid — each counts toward the rate limit).
- Commands 31–40: rate limit enforced; each emits `ActionRateLimitExceeded`.
- After 5 violations in 10 minutes: `PlayerAbuseWarningIssued`.
- After 3 warnings in 24 hours: `PlayerSessionSuspended` (15-minute cooldown); session invalidated; reconnection window applies if in active game.
- Repeated suspensions within 7 days escalate to admin review.

**Emitted events:** `ActionRateLimitExceeded` ×N, `PlayerAbuseWarningIssued`, `PlayerSessionSuspended`.

**Invariant protected:** Flooding cannot stall the game engine or starve other players of server resources.

---

### 5.5 Admin impersonation
**Trigger:** A regular player submits `CreateTournament` or `VoidGameResult`.

**Behavior:**
- JWT is validated; player's account record is checked for admin flag.
- Admin flag is absent → command rejected at the authentication boundary with 403 Forbidden.
- No domain event emitted; no state change.

**Emitted events:** None.

**Invariant protected:** Admin capabilities are account-level, not command-level; they cannot be bypassed by command submission alone.

---

### 5.6 Replay attack using a captured JWT
**Trigger:** Attacker captures Player A's JWT from a previous session (issued 2 hours ago) and replays it.

**Behavior:**
- JWT signature is valid (token was legitimately issued).
- Server reads `valid_sessions_from` for Player A: timestamp is 1 hour ago (A logged in again since).
- Token's `issued_at` (2 hours ago) < `valid_sessions_from` (1 hour ago) → token rejected.

**Emitted events:** None.

**Invariant protected:** `valid_sessions_from` invalidates all tokens issued before the last login, making replay attacks ineffective after any subsequent login.

---

### 5.7 Concurrent login race condition
**Trigger:** Player A logs in from two devices within the same millisecond.

**Behavior:**
- Both login requests create new JWTs with the current timestamp.
- Both attempt to update `valid_sessions_from`.
- The server serializes this update atomically; whichever write completes last sets the final `valid_sessions_from`.
- The JWT issued with an `issued_at` before the final `valid_sessions_from` is immediately invalid.
- One session survives; the other is effectively invalidated.

**Emitted events:** `SessionCreated` ×2, `SessionInvalidated` ×1 (the losing session's prior token).

**Invariant protected:** At most one valid session per player at any moment, even under concurrent login race conditions.

---

## 6. Spectator Privacy Violations

### 6.1 Spectator attempts to read a player's hand via the spectator channel
**Trigger:** A spectator subscribes to game G1's event stream hoping to see card identities in any player's hand.

**Behavior:**
- The Spectator View anti-corruption layer (ACL/whitelist filter) strips all hand card identity data before storing or broadcasting any event.
- `PublicGameView` contains only hand counts (number of cards), never card identities.
- If the spectator sends a direct API request for a player's hand: rejected with 403 Forbidden at the API boundary.
- No hand data ever reaches the spectator channel regardless of what Room Gameplay emits upstream.

**Emitted events:** None (filtered at ACL).

**Invariant protected:** Card identities are private during play; ACL is the last line of defense against upstream accidents.

---

### 6.2 Active player uses the spectator channel to read an opponent's hand
**Trigger:** Player B, who is an active participant in game G1, also subscribes to the spectator feed for G1 hoping to see more information than their player view provides.

**Behavior:**
- The spectator feed for G1 is identical regardless of the subscriber's identity (player or external spectator).
- Spectator feed carries `PublicGameView`: no card identities for any player, including B's own hand.
- B's own hand is available exclusively through the authenticated player endpoint, which serves only B's own cards.
- No additional information is obtainable via the spectator channel.

**Emitted events:** None.

**Invariant protected:** Spectator channel is information-neutral with respect to the subscriber's identity.

---

### 6.3 Attempting to view the accused player's hand during a WD4 challenge
**Trigger:** A spectator (or any player) attempts to learn the accused player's hand composition during an active Wild Draw Four challenge.

**Behavior:**
- `WildDrawFourChallengeResolved` event carries only the `outcome` field (Guilty/Innocent).
- The `accused_hand_at_time` field is populated server-side for audit purposes but is **withheld from all event broadcasts** during the game — it is not included in the payload delivered to any client.
- The field enters the `PublicGameLog` only after `GameCompleted` is processed.
- Any direct API request for hand data during the game is rejected at the API boundary.

**Emitted events:** `WildDrawFourChallengeResolved {outcome: Guilty/Innocent}` (hand field absent from broadcast).

**Invariant protected:** Hand revelation during WD4 challenge is server-internal only; accusation outcome is public, hand composition is not.

---

### 6.4 Spectator attempts to submit a game action
**Trigger:** A spectator sends a `PlayCard` command for game G1.

**Behavior:**
- API boundary checks the sender's role in game G1: spectator (no active player record in this room).
- Command rejected with 403 Forbidden before reaching the `GameSession` aggregate.
- No state change; no domain event.

**Emitted events:** None.

**Invariant protected:** Spectators are read-only observers; the command API is gated by active player membership.

---

### 6.5 Client requests the game log during an active game
**Trigger:** A client (player or spectator) requests the full `PublicGameLog` for game G1 while G1 is `in_progress`.

**Behavior:**
- The game log endpoint checks the game's status.
- Status is `in_progress` → request rejected: game log is only accessible after the game reaches `completed` state.
- Players and spectators observe the live game exclusively through the real-time event stream, which enforces visibility rules.

**Emitted events:** None.

**Invariant protected:** The full game log (including all card identities and WD4 hand compositions) is never exposed while the game is active.

---

### 6.6 Accidental hand data leak via upstream event payload change
**Trigger:** A Room Gameplay developer adds a `full_hand` field to the `CardDrawn` event payload for internal debugging purposes.

**Behavior:**
- The event flows to Spectator View's ACL.
- Spectator View maintains an explicit whitelist of permitted fields per event type. `full_hand` is not on the whitelist for `CardDrawn`.
- The field is dropped before the event is stored in `PublicGameView` or broadcast to any subscriber.
- No spectator or downstream consumer ever receives the leaked field.

**Emitted events:** `CardDrawn` (filtered; `full_hand` absent from broadcast).

**Invariant protected:** The ACL acts as a defense-in-depth layer — spectator privacy does not depend on upstream developers never making mistakes.
