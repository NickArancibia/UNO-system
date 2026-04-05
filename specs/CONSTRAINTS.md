# UnoArena — Platform Business Rules & Constraints

This document defines all non-ruleset business rules and constraints for the UnoArena platform. It covers player identity, room lifecycle, game mechanics, spectators, Elo, and game logging. Game card rules are in [RULESET.md](./RULESET.md). Tournament-specific rules are in [TOURNAMENT_RULES.md](./TOURNAMENT_RULES.md).

---

## 1. Player Accounts & Identity

- **Registration is required**. There are no guest or anonymous players.
- Every player has a persistent profile containing at minimum: unique ID, username, region, Elo rating, and game statistics.
- **Regional matching**: when placing players into rooms, the system prefers players from the same region to reduce latency. Cross-region matching is allowed when regional pools are insufficient.
- A player may not participate as an active player in more than one game simultaneously.
- A player may spectate any number of games while not actively playing.
- **Session management**: each player may hold only one active session at a time. A new login from any device immediately invalidates the previous session. If the invalidated session was an active participant in a running game, that player is treated as having lost connection — the standard 60-second reconnection window applies (see Section 2.5). On the new session, the player is offered the option to reconnect to any game they are currently registered in.
- **Player statistics** tracked on each profile: games played, win rate (wins / completed casual games), total cumulative points scored, and tournaments won.

---

## 2. Room System

### 2.1 Room Properties

- Rooms support **2 to 10 active players**.
- All rooms are **public**: any player may find and spectate a room by its ID.
- **Players do not create rooms directly.** All rooms are created and managed by the matchmaking system.
- Players enter a **Quick Play queue** to find a casual match (see Section 2.2).
- All rooms are identified by a unique ID.

### 2.2 Casual Matchmaking & Pre-Game Lobby

The matchmaking system assembles rooms from the Quick Play queue. Rooms are not created manually by players.

**Matchmaking criteria (applied in priority order):**
1. **Regional proximity**: players from the same or geographically adjacent regions are matched first to minimize latency. Cross-region matching activates when the regional pool is insufficient to fill a room within the matchmaking window (see Section 8 for region definitions).
2. **Elo proximity**: among regionally compatible candidates, players with similar casual Elo ratings are grouped together.

**Lobby flow for casual rooms:**
1. The matchmaking system assembles a room from queued players; the room enters the **lobby state**.
2. The countdown timer does **not** begin until **at least 5 players** are assigned to the lobby.
3. Once 5 players are assigned, a **5-minute countdown** begins.
4. If the room fills to the **maximum capacity (10 players)**, the timer is immediately reduced to **10 seconds** (if not already below that).
5. When the timer expires, the game starts with all players currently in the lobby, provided at least **2 players** are present.
6. If the timer expires with fewer than 2 players, the room is cancelled and all queued players are returned to the matchmaking pool.
7. Players cannot join a game that is already **in progress** as active players. They may join as spectators only.

**Tournament rooms:**
- Tournament rooms are assembled by the matchmaking system, which **maximizes the number of players per room** before triggering the lobby timer.
- The lobby timer only begins once the matchmaking system determines the room cannot be filled further (or is at maximum capacity).
- See [TOURNAMENT_RULES.md](./TOURNAMENT_RULES.md) for full detail.

### 2.3 Turn Timer

- Each player's turn has a **45-second turn timer**.
- When the timer expires for a **connected** player, the system automatically executes **Option B** on the player's behalf (draw one card, end turn). This counts as a turn taken. For disconnected players, turns are skipped instead (see Section 2.5).
- The AFK counter increments each time the turn timer expires for a player **consecutively**.
- The AFK counter **resets to zero** after any successful action submitted by the player.
- The **Uno! challenge window** (5 seconds — see [RULESET.md — Section 8](./RULESET.md)) runs concurrently within the next player's 45-second turn timer. It does not pause or reset the turn timer.

### 2.4 AFK Detection & Automatic Forfeit

- If a connected player's turn timer expires **3 consecutive times**, they are considered **AFK** and are **automatically forfeited** from the game.
- The AFK counter **only accumulates for connected players**. Turns skipped due to disconnection do not count toward the AFK counter.
- An AFK forfeit is treated identically to a voluntary forfeit in all respects (Elo, tournament elimination, etc.).

### 2.5 Disconnection & Voluntary Forfeit

- A player may **explicitly forfeit** at any time by submitting a forfeit command. This **immediately and permanently** ends their participation in the current game.
- If a player's connection drops for any reason — whether they intentionally closed their client or experienced an involuntary disconnect:
  - They remain registered in the game.
  - A **60-second reconnection window** begins immediately.
  - During the window, the disconnected player's **turns are skipped** (as if they passed). The turn timer does not run and the AFK counter does not accumulate.
  - If the window expires, the player is **automatically forfeited**. If the window expires during the player's turn, the forfeit is immediate.
  - A player who **reconnects within the window** resumes with their original hand intact. A reconnection is considered complete only once the session is re-established **and** the game state is fully synchronized. Their AFK counter resets to zero.
- Any forfeit — explicit, AFK, or reconnection-window expiry — is permanent. A forfeited player cannot re-enter the same game.

### 2.6 Effect of a Forfeit on the Game

- When a player forfeits, **their hand is discarded** and removed from the game. Their cards are not scored.
- The game continues normally with the remaining players.
- If a forfeit leaves only **1 active player** in the room, that player is declared the **winner of the current game** immediately. No further rounds are started.
- If a forfeit leaves **0 active players**, the game is **voided**: no scores are recorded and **no Elo changes are applied** to any player.

### 2.7 Room Lifecycle States

| State | Description |
|---|---|
| `waiting` | Room created, accepting players, timer not yet started |
| `lobby` | 5+ players present, countdown active |
| `in_progress` | Game running, rounds being played |
| `completed` | Game finished, winner determined |

---

## 3. Game Format — Casual

- A casual game runs continuously until one player empties their hand. Cards are dealt once at the start; the draw pile is replenished from the discard pile as needed (see [RULESET.md — Section 11](./RULESET.md)) but there is no re-deal between rounds.
- The player who empties their hand wins the game and receives **0 points**. All other players receive a negative score equal to the sum of card values remaining in their hand (see [RULESET.md — Section 9](./RULESET.md)).
- Players are ranked from highest (0 points, the winner) to lowest (most negative). There is no cumulative point threshold — emptying your hand is the only way to win.
- **Tiebreak for equal point totals** (non-winner positions):
  1. **Fewest cards remaining** → ranks higher.
  2. **Still tied**: ranking among tied players is **randomized**.
- There is no maximum game duration for casual games.

---

## 4. State Visibility

### 4.1 Player View

- A player can see:
  - Their own hand (card identities and count).
  - All other players' **hand counts** (number of cards held), but not card identities.
  - The full discard pile (top card always visible; full history accessible).
  - The draw pile size.
  - Current turn order, direction, and whose turn it is.
  - All game events (cards played, draws, skips, penalties, Uno calls, etc.).
  - Current cumulative scores.

- A player **cannot** see:
  - Any other player's card identities.

### 4.2 Wild Draw Four Challenge

- When a Wild Draw Four challenge is initiated, the server **verifies the accused player's hand internally**. No hand is revealed to the challenger or any other player — including spectators — during the game.
- The outcome of the challenge (guilty or innocent) and the verified hand composition are recorded and become visible in the **public post-game log** after the game ends (see [ASSUMPTIONS.md — Section 5](./ASSUMPTIONS.md)).
- **Timing**: the Wild Draw Four challenge window (5 seconds) opens immediately when the Wild Draw Four is played and runs **before** the next player's 45-second turn timer starts. The next player must decide to challenge or draw within this 5-second window. After the window resolves (challenge outcome determined, or no challenge and the player draws), the 45-second turn timer starts for the player whose turn it now is.
- **When the Wild Draw Four is the player's second-to-last card**: a combined Uno! + Wild Draw Four window applies — see [RULESET.md — Section 8](./RULESET.md) for the full combined window rules.

### 4.3 Spectator View

- Spectators see the **same view as players** with one exception: spectators **cannot see any player's hand** (card identities).
- Spectators **can** see all hand counts, the discard pile, turn order, scores, and all game events.
- Spectators **cannot** interact with the game in any way.
- Spectators may join any game at any time, including mid-game.
- There is **no limit** on the number of spectators per room.
- All rooms are publicly spectatable by ID — there are no private games.

---

## 5. Elo & Ranking System

### 5.1 Elo Ratings

Every player has two separate Elo ratings:

- **Global Elo**: applies to **casual (ad-hoc) games only**. Starting value: **1,000** for all new players. Updated after each completed casual game.
- **Tournament-placement Elo**: applies to **tournament games only**. See [TOURNAMENT_RULES.md — Section 8](./TOURNAMENT_RULES.md) for details.

### 5.2 Casual Elo Calculation

UnoArena uses a **placement-based multi-player Elo extension** for casual games. For a completed game with N players ranked in positions 1 (winner) through N (last):

1. **Actual score**: `S_i = (N − rank_i) / (N − 1)`
2. **Expected score**: `E_i = [Σ_{j≠i} P(i beats j)] / (N − 1)`, where `P(i beats j) = 1 / (1 + 10^((R_j − R_i) / 400))`
3. **Elo delta**: `ΔR_i = K × (S_i − E_i)`
4. **K-factor**: 32 for players with fewer than 20 completed casual games; 16 for 20–99 games; 12 for 100+ games.
5. **Points bonus**: since points are 0 or negative, "above the room average" means a smaller absolute deficit. If a player's absolute card-value deficit is at most **80% of the room average absolute deficit** (i.e., they performed at least 20% better than average), `ΔR_i` is increased by +3. The winner (0 points) always qualifies if the room average is negative.

Forfeiting players are assigned rank N (last place) regardless of when they forfeited. See also [ASSUMPTIONS.md — Section 3](./ASSUMPTIONS.md) for full derivation rationale.

### 5.3 Forfeit Impact on Elo

- Any forfeit — whether voluntary disconnect, AFK, or reconnection-window expiry — counts as a **full loss** for Elo purposes (last place finish, zero points). This applies to both casual Elo and tournament-placement Elo.
- There is no reduced penalty for early disconnection.
- **Exception**: if a game is voided (all players forfeit), no Elo changes are applied to any player (see Section 2.6).

### 5.4 Leaderboards

- A **global casual leaderboard** ranks all players by their current casual Elo rating.
- A **separate tournament leaderboard** ranks all players by their current tournament-placement Elo rating.
- There are **no named ranking tiers** (e.g., no Bronze/Silver/Gold). Both ratings are expressed as plain numeric values.

---

## 6. Game Log & Disputes

- The complete **event log** of every game (all card plays, draws, penalties, Uno calls, score events, and Wild Draw Four hand reveals from challenges) is **publicly accessible** to anyone after the game transitions to the `completed` state. The log is **not accessible** during an active game — players and spectators observe the game via the real-time event stream, which enforces visibility rules (see Section 4).
- The log includes the final scores and finish positions of all players.
- Any player or spectator may **flag a game** for admin review if they believe a result was incorrect or suspicious.
- Flagged games are reviewed by a platform admin who may void or override results.

---

## 7. Admin Capabilities

- **Who are admins**: designated platform administrators with elevated privileges, separate from regular player accounts.
- Admins may **create and schedule tournaments** (see [TOURNAMENT_RULES.md — Section 9](./TOURNAMENT_RULES.md)).
- Admins may **cancel a running tournament** at any time. When a tournament is cancelled, no Elo updates are applied to any participant for any games played within that tournament.
- Admins **may not force-end an individual game** mid-progress.
- Admins may **review flagged games** and void or override results. If a game result is voided or overridden by an admin, any Elo changes already applied from that game are reversed.
- All admin actions are recorded in a separate audit log.

---

## 8. Regions

Each player is assigned a **home region** at registration (self-selected). The matchmaking system uses region as the primary criterion for grouping players.

Defined regions:

| Region ID | Name |
|---|---|
| `NA-W` | North America — West |
| `NA-E` | North America — East |
| `SA` | South America |
| `EU-W` | Europe — West |
| `EU-E` | Europe — East |
| `ME` | Middle East |
| `AF` | Africa |
| `RU` | Russia / CIS |
| `AS-E` | Asia — East (Korea, Japan, China) |
| `AS-S` | Asia — South & Southeast |
| `OCE` | Oceania |

**Cross-region matching adjacency** (used when same-region pools are insufficient): NA-W ↔ NA-E ↔ SA; EU-W ↔ EU-E ↔ ME ↔ AF ↔ RU; AS-E ↔ AS-S ↔ OCE. Truly global cross-region matching (across adjacency groups) is the final fallback.

---

## 9. Concurrency Control

Game state is **versioned**. Each game has a monotonically increasing **state version number** that increments with every accepted state change (card played, card drawn, turn advanced, penalty applied, etc.).

**Command protocol:**
- Every command submitted by a client must include the **last state version** the client observed.
- If the server's current version does not match the submitted version, the command is rejected with a **conflict response** and no state change occurs.
- The client reconciles by consuming the event stream to reach the current state, then retries if the action is still valid.

**Idempotency:**
- Every command carries a **client-generated UUID** (idempotency key).
- If the server receives the same UUID twice, it returns the original outcome without reprocessing.
- This protects against duplicate submissions from at-least-once delivery retries.

**Race resolution for multi-player first-come-first-served actions (`JumpIn`, `ChallengeUno`):**

Pure packet-arrival order disadvantages players with higher network latency (e.g., cross-region rooms). To ensure fairness, the server uses **RTT-adjusted effective submission timestamps** for these actions:

1. The server maintains a server-measured rolling RTT per player session (`PlayerSession.latency_profile`). Client clocks are never trusted.
2. For each submission in a race, the server computes: `effective_submission_time = server_arrival_time − RTT/2`
3. Submissions arriving within a **150ms server-arrival window** are treated as part of the same race. The submission with the earliest effective time wins.
4. If the two earliest effective times are within **±20ms** of each other (measurement uncertainty), or if any participant's RTT measurement is unavailable, the winner is chosen by **server-side RNG** with equal probability — the same RNG mechanism used for all other random outcomes in the game.
5. A `RaceResolved` event is appended to the immutable game log before any effect is applied, recording the resolution method (EffectiveTimestamp or RNG) and full per-submission detail for audit purposes.

This mechanism applies **only** to `JumpIn` and `ChallengeUno` — the two commands where multiple players are simultaneously eligible. All other game commands have a single eligible submitter and are serialized by `state_version` alone.

---

## 10. Rate Limiting

Multi-layer rate limits protect the platform from abuse and command flooding.

**Domain-level limits (enforced by game invariants):**
- A player may submit at most **1 game action per turn** (enforced by turn ownership and sequence numbers).
- At most **1 Uno! challenge** may be issued per challenge window, per game.
- At most **1 Wild Draw Four challenge** may be issued per Wild Draw Four event.

**Request-level limits:**
- **Per IP**: 60 requests/minute on unauthenticated endpoints; 120 requests/minute on authenticated endpoints.
- **Per user**: 30 game-action commands/minute; 10 queue join/leave operations/minute; 5 game-flag submissions/hour.

**Abuse escalation (emitted as domain events):**
1. Each violation emits `ActionRateLimitExceeded` (attributed to player and action type).
2. After **5 violations within a 10-minute window**, `PlayerAbuseWarningIssued` is emitted and the player is notified.
3. After **3 warnings within 24 hours**, `PlayerSessionSuspended` is emitted — the player's session is terminated for a **15-minute cooldown**.
4. Repeated suspensions within 7 days escalate to admin review and potential permanent account ban.

---

## 11. Tournament Rules

Tournament-specific rules — including phase structure, phase-start thresholds, match format, advancement, and disconnection — are defined in [TOURNAMENT_RULES.md](./TOURNAMENT_RULES.md).
