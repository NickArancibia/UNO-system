# UnoArena — Platform Business Rules & Constraints

This document defines all non-ruleset business rules and constraints for the UnoArena platform. It covers player identity, room lifecycle, game mechanics, spectators, Elo, and game logging. Game card rules are in [RULESET.md](./RULESET.md). Tournament-specific rules are in [TOURNAMENT_RULES.md](./TOURNAMENT_RULES.md).

---

## 1. Player Accounts & Identity

- **Registration is required**. There are no guest or anonymous players.
- Every player has a persistent profile containing at minimum: unique ID, username, region, Elo rating, and game statistics.
- **Regional matching**: when placing players into rooms, the system prefers players from the same region to reduce latency. Cross-region matching is allowed when regional pools are insufficient.
- A player may not participate as an active player in more than one game simultaneously.
- A player may spectate any number of games while not actively playing.

---

## 2. Room System

### 2.1 Room Properties

- Rooms support **2 to 10 active players**.
- All rooms are **public**: any player may find and spectate a room by its ID.
- A **Quick Game** matchmaking option is available, which automatically assigns a player to an available open room or creates a new one.
- All rooms are identified by a unique ID.

### 2.2 Pre-Game Lobby

The lobby phase determines when a game starts. The system uses a **presence-based lobby with a countdown timer**.

**Casual rooms:**
1. When a room is created, it enters the **lobby state** and accepts players.
2. The countdown timer does **not** begin until **at least 5 players** are present in the lobby.
3. Once 5 players are present, a **5-minute countdown** begins.
4. If the room fills to the **maximum capacity (10 players)**, the timer is immediately reduced to **10 seconds** (if not already below that).
5. When the timer expires, the game starts with all players currently in the lobby, provided at least **2 players** are present.
6. If the timer expires with fewer than 2 players, the lobby is cancelled.
7. Players cannot join a game that is already **in progress** as active players. They may join as spectators only.

**Tournament rooms:**
- Tournament rooms are assembled by the matchmaking system, which **maximizes the number of players per room** before triggering the lobby timer.
- The lobby timer only begins once the matchmaking system determines the room cannot be filled further (or is at maximum capacity).
- See [TOURNAMENT_RULES.md](./TOURNAMENT_RULES.md) for full detail.

### 2.3 Turn Timer

- Each player's turn has a **45-second turn timer**.
- When the timer expires, the system automatically executes **Option B** on the player's behalf (draw one card, end turn). This counts as a turn taken.
- The AFK counter increments each time the turn timer expires for a player **consecutively**.
- The AFK counter **resets to zero** after any successful action submitted by the player.

### 2.4 AFK Detection & Automatic Forfeit

- If a player's turn timer expires **3 consecutive times**, they are considered **AFK** and are **automatically forfeited** from the game.
- An AFK forfeit is treated identically to a voluntary forfeit in all respects (Elo, tournament elimination, etc.).

### 2.5 Disconnection & Voluntary Forfeit

- A player may voluntarily disconnect at any time, which **immediately forfeits** their participation in the current game.
- If a player **loses connection** without voluntarily forfeiting:
  - They remain registered in the game.
  - Their turn timer continues to run normally.
  - They may **reconnect** and resume participation as long as they have not yet been forfeited via the AFK mechanism.
  - Once forfeited (AFK), reconnection is not possible for that game.
- Any forfeit — voluntary or AFK — is permanent. A forfeited player cannot re-enter the same game.

### 2.6 Effect of a Forfeit on the Game

- When a player forfeits, **their hand is discarded** and removed from the game. Their cards are not scored.
- The game continues normally with the remaining players.
- If a forfeit leaves only **1 active player** in the room, that player is declared the **winner of the current round** immediately.
- If a forfeit leaves **0 active players**, the game is voided.

### 2.7 Room Lifecycle States

| State | Description |
|---|---|
| `waiting` | Room created, accepting players, timer not yet started |
| `lobby` | 5+ players present, countdown active |
| `in_progress` | Game running, rounds being played |
| `completed` | Game finished, winner determined |

---

## 3. Game Format — Casual

- A casual game consists of **multiple rounds** played until one player reaches **500 cumulative points**.
- The first player to reach or exceed 500 points at the end of any round wins the game.
- Scoring follows the rules in [RULESET.md — Section 9](./RULESET.md).
- After each round, cards are collected, reshuffled, and a new round begins with all remaining active players.
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

### 4.2 Wild Draw Four Challenge Reveal

- When a Wild Draw Four challenge is initiated, the **accused player's full hand is revealed exclusively to the challenger**.
- No other player — including spectators — sees the hand during the challenge.

### 4.3 Spectator View

- Spectators see the **same view as players** with one exception: spectators **cannot see any player's hand** (card identities).
- Spectators **can** see all hand counts, the discard pile, turn order, scores, and all game events.
- Spectators **cannot** interact with the game in any way.
- Spectators may join any game at any time, including mid-game.
- There is **no limit** on the number of spectators per room.
- All rooms are publicly spectatable by ID — there are no private games.

---

## 5. Elo & Ranking System

### 5.1 Elo Rating

- Every player has a single **global Elo rating**.
- There is no separate casual vs. tournament Elo — one number covers all game modes.
- **Starting Elo**: 1,000 (for all newly registered players).
- Elo is updated **after a full game completes** (not after individual rounds).

### 5.2 Elo Calculation Inputs

- The Elo update formula takes as inputs:
  - **Finish position** of each player (1st, 2nd, ... last).
  - **Cumulative points** scored by each player during the game.
- The exact multi-player Elo formula is to be defined during the design phase, but must account for both position and score relative to all opponents in the same game.

### 5.3 Forfeit Impact on Elo

- Any forfeit — whether voluntary disconnect or AFK — counts as a **full loss** for Elo purposes (last place finish, zero points).
- There is no reduced penalty for early disconnection.

### 5.4 Leaderboard

- A **global leaderboard** ranks all players by their current Elo rating.
- There are **no named ranking tiers** (e.g., no Bronze/Silver/Gold). Elo is expressed as a plain numeric value.

---

## 6. Game Log & Disputes

- The complete **event log** of every game (all card plays, draws, penalties, Uno calls, score events) is **publicly accessible** to anyone after the game ends.
- The log includes the final scores and finish positions of all players.
- Any player or spectator may **flag a game** for admin review if they believe a result was incorrect or suspicious.
- Flagged games are reviewed by a platform admin who may void or override results.

---

## 7. Tournament Rules

Tournament-specific rules — including phase structure, phase-start thresholds, match format, advancement, and disconnection — are defined in [TOURNAMENT_RULES.md](./TOURNAMENT_RULES.md).
