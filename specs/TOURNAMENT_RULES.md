# UnoArena — Tournament Rules

This document defines all rules specific to tournament mode. General platform rules (Elo, rooms, forfeits) are in [CONSTRAINTS.md](./CONSTRAINTS.md). Game card rules are in [RULESET.md](./RULESET.md).

---

## 1. Overview

- Tournaments support up to **1,000,000 players**.
- A tournament consists of **sequential elimination rounds**, each reducing the active player pool by approximately 70%. The actual number of rounds is computed dynamically from the confirmed player count at tournament start (see Section 2).
- There are **no fixed brackets**. Before each round, all qualifiers are **reshuffled** and distributed randomly into new rooms. Players never face the same seeded opponents.
- In each room, players compete in a **best-of-three match** (up to 3 individual games). The **top 3 players by game wins** advance to the next round; the rest are eliminated.
- The tournament ends when **10 or fewer players remain**, at which point a **Final Room** is created. The winner of the Final Room is the **Tournament Champion**.

---

## 2. Round Structure

The number of rounds is computed at tournament start from the confirmed player count using the formula:

> **rounds = ceil(log(confirmed\_players / 10) / log(10/3))**

This reflects the approximately 3× reduction per round (top 3 out of 10 advance).

The full table for maximum scale (1,000,000 players) is:

| Round | Players entering | Rooms | Qualifiers |
|---|---|---|---|
| 1 | 1,000,000 | 100,000 | 300,000 |
| 2 | 300,000 | 30,000 | 90,000 |
| 3 | 90,000 | 9,000 | 27,000 |
| 4 | 27,000 | 2,700 | 8,100 |
| 5 | 8,100 | 810 | 2,430 |
| 6 | 2,430 | 243 | 729 |
| 7 | ~729 | ~73† | ~219 |
| 8 | ~219 | ~22† | ~66 |
| 9 | ~66 | ~7† | ~21 |
| 10 | ~21 | ~2–3† | ~7–9 |
| **Final** | **≤10** | **1** | **1 (Champion)** |

†From round 7 onward, player counts are not exact multiples of 10. Partial rooms are formed and all active players in a partial room advance (see Section 4).

- Rooms always target **10 players** but may run with as few as **2 players** if insufficient qualifiers are available.
- Player counts entering each round may be lower than projected due to forfeit, disconnection, or no-shows.
- **Minimum to start**: 1,000 confirmed players, guaranteeing at least 5 competitive rounds before the Final.

---

## 3. Match Format in Tournaments

Each room plays a **fixed three-game match**: always exactly 3 individual games. Each individual game uses a **modified win condition** compared to casual:

- A player wins a **game** by being the first to either:
  1. **Empty their hand** (play their last card), OR
  2. **Reach 400 cumulative points** across rounds within that game.
- Both conditions are checked at the end of each round. Whichever is triggered first ends the game immediately.
- Scoring per round follows [RULESET.md — Section 8](./RULESET.md).

The match proceeds as follows:
1. All players in the room **always play exactly 3 games**, regardless of intermediate win counts. The match ends early only if the 20-minute timeout is reached (see Section 3.1) or all players but one have forfeited.
2. After all 3 games are completed (or the match timeout is reached), each player's **game win count** (0, 1, 2, or 3) is recorded.
3. The **top 3 players by game wins** advance (see Section 4 for tiebreaks and partial rooms).

### 3.1 Match Timeout

- Each tournament room has a **20-minute hard timeout** covering the **entire match** (all games combined).
- If the timeout is reached during an active game, that game is resolved immediately:
  1. **Most cumulative points** → winner of that game.
  2. Tiebreak (equal points): **fewest cards remaining in hand** → winner.
  3. Second tiebreak (equal cards): **earliest turn order position** (closest to 1st in the current turn sequence) → winner.
- After timeout resolution, game wins are tallied and advancement is determined normally.

---

## 4. Advancement

- The **top 3 players by game wins** within a match advance to the next round.
- **Tiebreak rules** (when two or more players are tied on game wins):
  1. **Lower cumulative card-point total** across the games in which those tied players had an equal number of wins (i.e., only the games contributing to the tie are counted) → advances.
  2. Still tied: **earliest time of final game completion** → advances.
- **Partial rooms**: if a room ends with **3 or fewer active players** (due to forfeits or disconnections during the match), all active players advance regardless of win count.
- Players eliminated from the tournament may freely **spectate any active room** in the current or subsequent rounds.

---

## 5. Round-Start Thresholds (Early Room Formation)

The system does not wait for **all** rooms in the current round to finish before forming rooms for the next round. Rooms are formed progressively as qualifiers arrive.

To ensure sufficient randomness in room assignments, the system waits until a **minimum number of qualifiers** are available before beginning room formation for the next round:

| Round completing | Qualifiers expected | Minimum to begin forming next-round rooms |
|---|---|---|
| 1 | 300,000 | 3,000 (1%) |
| 2 | 90,000 | 9,000 (10%) |
| 3 | 27,000 | 2,700 (10%) |
| 4 | 8,100 | 4,050 (50%) |
| 5 | 2,430 | 2,430 (100% — wait for all) |
| 6+ | ≤729 | 100% — wait for all |

- Once the threshold is reached, the matchmaking system begins assembling rooms immediately, maximizing player count per room before triggering the lobby timer.
- Players who qualify after rooms have already been formed will be placed into partially-filled rooms or new rooms as availability dictates.
- **Additional rule**: if the expected qualifier count for any round drops below **100 players**, the system always waits for all qualifiers before beginning room formation, regardless of round number.

---

## 6. Pre-Game Lobby for Tournament Rooms

Tournament rooms use a **matchmaking-driven lobby**:

1. The matchmaking system assembles rooms by pulling from the pool of available qualifiers, always aiming to fill rooms to 10 players.
2. The lobby timer only begins once the matchmaking system has determined the room cannot be filled further (room is at capacity, or the remaining qualifier pool is exhausted for that batch).
3. Once the timer starts, it follows the same presence-based rules as casual rooms (see [CONSTRAINTS.md — Section 2.2](./CONSTRAINTS.md)).
4. A tournament room starts with a minimum of 2 players.

---

## 7. Disconnection & Forfeit in Tournaments

Tournament disconnection follows the same rules as casual games ([CONSTRAINTS.md — Section 2.4 and 2.5](./CONSTRAINTS.md)), with one additional consequence:

- **Any forfeit** — whether voluntary disconnect, AFK, or reconnection-window expiry — **permanently eliminates the player from the current tournament**. They do not re-enter any subsequent round.
- A forfeiting player's hand is discarded. The match continues with remaining players.
- If a forfeit reduces the room to **3 or fewer active players**, all remaining active players advance (see Section 4).
- The eliminated player may continue to spectate any active rooms in the tournament.
- **Lone qualifier**: if, after all rooms have been formed for a round, a single qualifier cannot be placed into any room (minimum room size is 2 players), that player **automatically advances** to the next round without playing.

---

## 8. Tournament-Placement Elo

- Every player has a **tournament-placement Elo** rating, entirely separate from the casual global Elo.
- **Starting value**: 1,000 for all newly registered players.
- Elo is updated **once, after the entire tournament concludes**, so all metrics (final placement, rounds reached, match and game win rates) are available for the calculation.
- **Formula inputs**:
  - Final placement across all tournament participants (1st = champion, down to all Round 1 eliminees).
  - Number of rounds reached.
  - Cumulative match win rate and game win rate across the tournament.
- **Formula**: placement-based multi-player Elo — actual score `S_i = (T − p_i) / (T − 1)` where T = total participants and p_i = final placement; expected score `E_i` computed from pairwise Elo comparisons against all other participants; `ΔR_i = K × (S_i − E_i)` with **K = 40** for tournament play. Players eliminated in the same round share a placement bucket resolved by cumulative match win rate, then game win rate.
- Forfeits (voluntary, AFK, or reconnection-window expiry) count as the **worst placement within the player's elimination round** for tournament-placement Elo purposes.
- See [ASSUMPTIONS.md — Section 3](./ASSUMPTIONS.md) for full derivation rationale.

---

## 9. Tournament Creation & Registration

- **Who creates tournaments**: platform admins only. Tournaments may be created manually or scheduled in advance (e.g., a recurring Christmas tournament always starting on December 25th).
- **Registration**: players must register for a tournament before it begins. A registration window opens and closes at defined times set by the tournament organizer.
- **Minimum players to start**: **1,000 registered and active players**. A tournament does not begin if fewer than 1,000 players are confirmed at start time.
- **Concurrent participation**: a player may only be actively participating in one tournament at a time (they may spectate others).
- Players who register but are **not present in their assigned Round 1 lobby when that lobby's timer starts** are treated as having forfeited. They are removed from the room before the game begins and are permanently eliminated from the tournament, as if they had voluntarily forfeited during play. This prevents empty seats and does not affect other players in that room.

---

## 10. Summary of Tournament-Specific Rule Differences vs. Casual

| Rule | Casual | Tournament |
|---|---|---|
| Win condition (game) | First to 500 cumulative points | First to empty hand OR reach 400 cumulative points |
| Match format | Single game (multiple rounds) | Fixed three-game match; top 3 by game wins advance |
| Advancement | N/A | Top 3 per room; all active players if ≤3 remain |
| Match timeout | None | 20 minutes per match |
| Timeout resolution | N/A | Most points → fewest cards → turn order position |
| Forfeit consequence | Lose the game | Permanently eliminated from tournament |
| Lobby assembly | Players join manually | Matchmaking-assembled |
| Brackets | None | Reshuffled per round, no fixed seeding |
| Elo updated | Casual Elo (per completed game) | Tournament-placement Elo (once, after tournament concludes) |
