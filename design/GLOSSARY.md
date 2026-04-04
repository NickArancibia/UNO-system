# UnoArena — Domain Glossary

This is the authoritative ubiquitous language for the UnoArena platform. All design documents, event definitions, aggregate models, and narratives must use these terms exactly as defined here. When a term here conflicts with casual UNO usage, this document wins.

---

## 1. Core Structural Terms

| Term | Definition |
|---|---|
| `game` | A single UNO session played to completion: cards are dealt once, players take turns until one player empties their hand (or a terminal exception applies). A game has one winner. The atomic unit of play. |
| `match` | A Best-of-Three (Bo3) series of up to 3 games played by the same set of players within a single tournament room. A match ends early the moment any player reaches 2 game wins; otherwise it ends after Game 3. Matches exist only in tournament rooms. |
| `round` | One elimination tier within a tournament. All active tournament players are redistributed into new rooms and play a full match. The top 3 per room advance. A tournament consists of sequential rounds until 10 or fewer players remain. |
| `tournament` | A full multi-round elimination competition, starting from up to 1,000,000 registered players and concluding with a single Final Room whose winner is the Tournament Champion. |
| `room` | The runtime container that groups players for either a casual game or a tournament match. A room has a lifecycle (see Section 4) and holds both active players and spectators. Rooms are created by the matchmaking system, never by players. |
| `Final Room` | The single room created when 10 or fewer players remain in a tournament. The winner of the Final Room is the Tournament Champion. |
| `lobby` | The pre-game state of a room where players are assembled and a countdown timer is running. A game begins when the lobby timer expires with at least 2 players present. |
| `casual room` | A room created by the matchmaking system for a Quick Play queue match. Plays a single game. Elo-rated. |
| `tournament room` | A room created by the matchmaking system for a specific tournament round. Plays a Bo3 match. Tournament-Elo-rated. |

---

## 2. Player & Session Terms

| Term | Definition |
|---|---|
| `player` | A registered user with a persistent profile. Registration is mandatory; no anonymous participation as an active player. |
| `active player` | A player who is currently registered in a game and has not forfeited. During their turn, they must act or be acted upon by the system. |
| `spectator` | A player who is watching a room without participating as an active player. Spectators see public information only: hand counts, discard pile, turn order, scores, and game events — never any player's card identities. |
| `session` | A single authenticated login instance. Each player may hold exactly one active session at a time. A new login immediately invalidates the previous session. |
| `reconnection window` | The 60-second grace period after a player loses connection during which their turns are skipped and they may reconnect without penalty. If the window expires, the player is automatically forfeited. |
| `no-show` | A player who is assigned to a lobby but is not present when the lobby timer starts. Treated as having forfeited before the game begins; permanently eliminated from the tournament (in tournament rooms). |
| `qualifier` | A player who has advanced from a tournament round and is eligible to be assigned to a room in the next round. Distinct from "winner" — up to 3 players per room qualify; only the Final Room produces a single winner. |

---

## 3. Gameplay Terms

| Term | Definition |
|---|---|
| `hand` | The private set of cards held by a single active player. Card identities in a hand are never visible to other players or spectators during a game. |
| `deck` | The full 108-card standard UNO card set used to initialize every game. |
| `draw pile` | The face-down stack of undealt cards from which players draw during the game. |
| `discard pile` | The face-up stack of cards that have been played. The top card of the discard pile defines the current active color and rank/symbol. |
| `active color` | The color currently governing legal plays. Set by the top card of the discard pile, or explicitly declared when a Wild or Wild Draw Four is played. |
| `legal play` | A card is legal to play if it matches the top card of the discard pile in color, or in number/symbol, or is a Wild/Wild Draw Four. |
| `turn` | The period in which a single active player must perform exactly one action: play a legal card or draw one card from the draw pile. |
| `turn order` | The sequence in which players take turns, either clockwise or counterclockwise. Direction may be reversed by a Reverse card. |
| `turn timer` | The 45-second server-side timer for each turn. When it expires for a connected player, the system automatically draws one card on their behalf. For disconnected players, the turn is skipped. |
| `AFK counter` | A per-player counter that increments each time the turn timer expires consecutively for a connected player. Resets to zero on any successful action. At 3, an automatic forfeit is triggered. |
| `jump-in` | An out-of-turn play where a player holds a card identical (same color and same rank/symbol) to the top card of the discard pile and immediately plays it, resetting turn order from their position. Not allowed on Wild or Wild Draw Four cards. |
| `stack chain` | An active sequence of Draw Two cards where each successive player adds a Draw Two instead of drawing. The accumulated penalty grows by 2 per card added. The first player unable or unwilling to extend the chain must draw the full total. |
| `Uno! call` | The verbal/signal declaration a player must make at the moment they play their second-to-last card, leaving exactly one card in hand. |
| `Uno! challenge` | An action submitted by any opponent within the 5-second challenge window after a player plays their second-to-last card, asserting the player did not call "Uno!". |
| `challenge window` | A server-enforced time window during which specific challenge or response actions are valid. Two types exist: the **Uno! challenge window** (5 seconds, any opponent may challenge) and the **Wild Draw Four challenge window** (5 seconds, only the affected next player may challenge). |
| `combined window` | The merged 5-second window that applies when a Wild Draw Four is a player's second-to-last card. Both the Uno! challenge and the Wild Draw Four challenge are resolved within this single window. |
| `Wild Draw Four challenge` | An action by the next player in turn order, submitted within the challenge window, asserting that the player who played the Wild Draw Four held at least one card matching the active color at the time of play. |
| `draw pile exhaustion` | The state where the draw pile is empty and must be replenished by reshuffling the discard pile (minus the top card) before a draw can proceed. |

---

## 4. Lifecycle & State Terms

| Term | Definition |
|---|---|
| `room state` | One of four states a room may be in: `waiting`, `lobby`, `in_progress`, `completed`. |
| `waiting` | Room has been created and is accepting players; the countdown has not yet started because the 5-player threshold for timer activation has not been reached. The state is defined by the timer not having started, not purely by player count. |
| `lobby` | 5 or more players are present and the countdown timer is active. |
| `in_progress` | The game (casual) or match (tournament) is actively being played. |
| `completed` | The game or match has concluded; a winner or advancement list has been determined. |
| `game lifecycle` | The sequence of events from game initialization (deck shuffle, deal) through gameplay to game end (a player empties their hand or all but one player forfeit). |
| `match lifecycle` | The sequence of events from match start through up to 3 games to match end, including early end (any player reaches 2 game wins) and timeout resolution. |
| `tournament lifecycle` | The sequence from tournament registration open through sequential rounds to Final Room completion and champion declaration. |
| `forfeit` | The permanent removal of a player from the current game (casual) or from the entire tournament (tournament). Causes: explicit forfeit command, AFK (3 consecutive expired turn timers while connected), or reconnection window expiry. All forfeits are equivalent for scoring and Elo purposes. |
| `void` | A game outcome where no scores are recorded and no Elo changes are applied. Occurs when all active players forfeit simultaneously, leaving 0 active players. |
| `phase-start threshold` | The minimum number of qualifiers that must be available before the matchmaking system begins forming rooms for the next tournament round. Varies by round (see TOURNAMENT_RULES.md Section 5). |

---

## 5. Concurrency & Command Terms

| Term | Definition |
|---|---|
| `state version` | A monotonically increasing integer attached to every game state. Increments with every accepted state change. Every client command must include the last state version the client observed; mismatches are rejected with a conflict response. |
| `idempotency key` | A client-generated UUID attached to every command. If the server receives the same UUID twice, it returns the original outcome without reprocessing. Protects against duplicate submissions caused by at-least-once delivery retries. |
| `stale command` | A command whose included state version does not match the server's current state version. Rejected with HTTP 409 Conflict. The client must reconcile via the event stream before retrying. |
| `conflict response` | The server's rejection of a stale command. Includes no state change. The client reconciles by consuming the event stream to reach the current state. |
| `optimistic concurrency control` | The mechanism by which the state version enforces serialization of concurrent commands without locking: only the first matching command wins; all others are rejected and must reconcile. |

---

## 6. Scoring & Ranking Terms

| Term | Definition |
|---|---|
| `game score` | The numeric score a player receives at the end of a game. The winner receives 0. All others receive a negative value equal to the sum of card values remaining in their hand (number cards at face value; Skip/Reverse/Draw Two at −20; Wild/Wild Draw Four at −50). |
| `card-point burden` | The non-negative version of a player's game score used in tournament tie-breaking: the absolute sum of remaining card values. A game score of −22 yields a card-point burden of 22. Preferred term when discussing tie-breaks to avoid sign confusion. |
| `cumulative card-point burden` | The sum of a player's card-point burdens across all games played in a match. Used as the first tie-breaker when players are equal on match wins. |
| `cumulative cards remaining` | The sum of cards remaining in a player's hand across all games played in a match. Used as the second tie-breaker when players are equal on both match wins and cumulative card-point burden. |
| `match wins` | The count of individual games won by a player within a match. The primary ranking criterion for tournament advancement. |
| `placement` | A player's ordered finish rank within a specific scope: `game placement` (1st through last within a single game), `room placement` (final standing in a room after a match), `tournament placement` (1st = champion, down to all Round 1 eliminees). |
| `advancement` | Qualification from the current tournament round into the next. The top 3 players by room placement advance. If 3 or fewer active players remain, all advance unconditionally. |
| `casual Elo` | The global Elo rating that applies exclusively to casual (Quick Play) games. Starting value: 1,000. Updated after each completed casual game. |
| `tournament-placement Elo` | The separate Elo rating that applies exclusively to tournament participation. Starting value: 1,000. Updated once after the entire tournament concludes. |
| `K-factor` | The Elo sensitivity multiplier. For casual Elo: 32 (< 20 games played), 16 (20–99 games), 12 (100+ games). For tournament-placement Elo: always 40. |
| `points bonus` | A +3 Elo delta bonus applied when a player's card-point burden is at most 80% of the room average (i.e., they performed at least 20% better than average). The winner always qualifies. |

---

## 7. Event & Integration Terms

| Term | Definition |
|---|---|
| `domain event` | An immutable record of something that happened within the domain, named in past tense (e.g., `CardPlayed`, `GameCompleted`). Domain events are the primary mechanism for cross-context communication. |
| `command` | A request to change domain state, submitted by a client or another context. Commands may be accepted (producing one or more domain events) or rejected (producing a conflict or validation error). |
| `event stream` | The ordered sequence of domain events for a specific game or context, delivered to subscribed clients and consumers. Events within a single game are delivered in strict causal order enforced by the state version. |
| `game log` | The complete, immutable post-game record of all events in a game: every card played, drawn, penalized, all Uno! calls, challenge outcomes, forfeit events, and final standings. Publicly accessible after the game completes. Not accessible during an active game. |
| `read model` | A denormalized, query-optimized projection derived from domain events. Examples: leaderboard, bracket view, player statistics. Read models may lag behind the event stream due to async propagation. |
| `projection` | The process of building or updating a read model by consuming domain events in order. |
| `at-least-once delivery` | The event delivery guarantee assumed by the platform: every event will be delivered to every consumer at least once, but may be delivered more than once. Consumers must be idempotent. |

---

## 8. Security & Moderation Terms

| Term | Definition |
|---|---|
| `rate limit` | A cap on the number of actions a client or user may submit within a given time window. Enforced at multiple layers: per IP, per user, per game action type. |
| `abuse escalation` | The multi-stage response to repeated rate limit violations: `ActionRateLimitExceeded` → `PlayerAbuseWarningIssued` (after 5 violations in 10 minutes) → `PlayerSessionSuspended` (after 3 warnings in 24 hours, 15-minute cooldown) → admin review. |
| `audit log` | A separate, append-only record of all admin actions (tournament creation, game result override, player suspension, etc.). |
| `flagged game` | A game marked by a player or spectator for admin review due to a suspected incorrect result or suspicious behavior. |
| `session takeover` | An abuse scenario where an attacker attempts to authenticate as another player. Mitigated by JWT + server-side `valid_sessions_from` invalidation. |

---

## 9. Anti-Ambiguity Notes

These clarifications exist because certain terms are used differently in casual UNO contexts or could be confused across scopes.

| Potentially ambiguous term | Correct usage in this domain |
|---|---|
| "win" / "winner" | Always qualify the scope: **game win** (first to empty hand in a single game), **match win** (a game win credited toward Bo3 standing), **room qualifier** (one of the top 3 players advancing from a tournament room — NOT called a "winner"), **Tournament Champion** (winner of the Final Room). Never use "win" or "winner" unqualified. In tournament rooms, the players who advance are **qualifiers**, not winners. |
| "score" | Ambiguous alone. Use **game score** (0 or negative, per game) or **card-point burden** (non-negative, for tie-breaking). Never use "score" to mean Elo or placement. |
| "points" | In game context: card point values (face value, 20, or 50). In Elo context: Elo delta. Always qualify. |
| "round" | In game context, there are no rounds within a single game. "Round" refers exclusively to a tournament elimination tier. |
| "draw" | May mean: drawing a card from the draw pile (player action), or a tie outcome. Use **draw a card** and **tie** respectively to avoid confusion. |
| "penalty" | Cards drawn as punishment (Uno! challenge failure, Wild Draw Four effect, AFK forfeit — note: AFK forfeit removes the player; it does not impose a card draw). Use **penalty cards** for the former. |
| "timer" | Three distinct server-side timers exist: **turn timer** (45s), **challenge window** (5s for Uno! or WD4), **reconnection window** (60s). Always name the specific timer. |
| "challenge" | Two distinct challenge types: **Uno! challenge** (any opponent, after second-to-last card played) and **Wild Draw Four challenge** (only the affected next player, after WD4 played). Never use "challenge" without specifying which type. |
| "lobby" | Refers to the pre-game room state where the countdown is active. Not a synonym for "room" in general. |
| "elimination" | In tournament context: a player who forfeits or fails to advance is eliminated from the tournament. Not used to mean losing a single game in a casual room. |
