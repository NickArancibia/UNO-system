# UnoArena — Tournament Rules

This document defines all rules specific to tournament mode. General platform rules (Elo, rooms, forfeits) are in [CONSTRAINTS.md](./CONSTRAINTS.md). Game card rules are in [RULESET.md](./RULESET.md).

---

## 1. Overview

- Tournaments support up to **1,000,000 players**.
- A tournament consists of **up to 6 sequential phases**, each reducing the active player pool by a factor of 10. The actual number of phases is computed dynamically from the confirmed player count at tournament start (see Section 2).
- There are **no fixed brackets**. Before each phase, all qualifiers are **reshuffled** and distributed randomly into new rooms. Players never face the same seeded opponents.
- Only **1st place** in each room advances to the next phase.
- The last player standing after the final phase is the **Tournament Champion**.

---

## 2. Phase Structure

The number of phases is **not fixed at 6**. It is computed at tournament start from the confirmed player count using the formula:

> **phases = ceil(log₁₀(confirmed_players))**

The full 6-phase table (maximum scale) is:

| Phase | Players entering | Rooms | Players per room | Qualifiers |
|---|---|---|---|---|
| 1 | 1,000,000 | 100,000 | 10 | 100,000 |
| 2 | 100,000 | 10,000 | 10 | 10,000 |
| 3 | 10,000 | 1,000 | 10 | 1,000 |
| 4 | 1,000 | 100 | 10 | 100 |
| 5 | 100 | 10 | 10 | 10 |
| 6 | 10 | 1 | 10 | 1 (Champion) |

For example, a tournament with 5,000 confirmed players begins at Phase 3 (the first phase whose input scale fits 5,000) and runs 4 phases to a champion.

- Rooms always target **10 players** (the platform maximum), but may run with as few as **2 players** if insufficient qualifiers are available for a full room.
- Player counts entering each phase may be lower than projected if players forfeit, disconnect, or fail to appear. The phase proceeds regardless.
- **Minimum to start**: 1,000 confirmed players, guaranteeing at least 3 phases.

---

## 3. Match Format in Tournaments

Tournament matches use a **modified win condition** compared to casual games:

- A player wins the match by being the **first to either**:
  1. **Empty their hand** (play their last card), OR
  2. **Reach 400 cumulative points** across rounds.
- Both conditions are checked at the end of each round. Whichever is triggered first ends the match immediately.
- Scoring per round follows [RULESET.md — Section 9](./RULESET.md).
- These dual win conditions are designed to keep tournament matches fast and to reward consistent point accumulation.

### 3.1 Match Timeout

- Each tournament room has a **20-minute hard timeout**.
- If the timeout is reached before any player satisfies a win condition, the match is resolved immediately:
  1. **Most cumulative points** → winner.
  2. Tiebreak (equal points): **fewest cards remaining in hand** → winner.
  3. Second tiebreak (equal cards): **earliest turn order position** (the player closest to 1st in the turn sequence) → winner.

---

## 4. Advancement

- Only **1st place** per room qualifies for the next phase.
- 2nd place and below are eliminated from the tournament.
- Eliminated players and winners who are waiting for their next phase may freely **spectate any active room** in the current phase.

---

## 5. Phase-Start Thresholds (Early Room Formation)

The system does not wait for **all** rooms in the current phase to finish before forming rooms for the next phase. Rooms are formed progressively as qualifiers arrive.

However, to ensure sufficient randomness in room assignments, the system waits until a **minimum number of qualifiers** are available before beginning room formation for the next phase:

| Phase completing | Qualifiers expected | Minimum to begin forming next-phase rooms |
|---|---|---|
| 1 | 100,000 | 1,000 (1%) |
| 2 | 10,000 | 1,000 (10%) |
| 3 | 1,000 | 100 (10%) |
| 4 | 100 | 50 (50%) |
| 5 | 10 | 10 (100% — wait for all) |

- Phase 6 only has 1 room and always waits for all 10 qualifiers.
- Once the threshold is reached, the matchmaking system begins assembling rooms immediately, maximizing player count per room before triggering the lobby timer.
- Players who qualify after rooms have already been formed will be placed into partially-filled rooms or new rooms as availability dictates.

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

- **Any forfeit** — whether voluntary disconnect or AFK (3 consecutive turn timer expirations) — **permanently eliminates the player from the current tournament**. They do not re-enter any subsequent phase.
- A forfeiting player's hand is discarded. The room continues with remaining players.
- The eliminated player may continue to spectate any active rooms in the tournament.

---

## 8. Tournament Creation & Registration

- **Who creates tournaments**: platform admins only. Tournaments may be created manually or scheduled in advance (e.g., a recurring Christmas tournament always starting on December 25th).
- **Registration**: players must register for a tournament before it begins. A registration window opens and closes at defined times set by the tournament organizer.
- **Minimum players to start**: **1,000 registered and active players**. A tournament does not begin if fewer than 1,000 players are confirmed at start time. This guarantees a minimum of 3 meaningful competitive phases.
- **Concurrent participation**: a player may only be actively participating in one tournament at a time (they may spectate others).
- Players who register but do not appear for their Phase 1 room are treated as having forfeited — they are removed from the bracket before room formation to avoid empty seats.

---

## 9. Summary of Tournament-Specific Rule Differences vs. Casual

| Rule | Casual | Tournament |
|---|---|---|
| Win condition | First to 500 points | First to empty hand OR reach 400 points |
| Match timeout | None | 20 minutes |
| Timeout resolution | N/A | Most points → fewest cards → turn order |
| Forfeit consequence | Lose the game | Eliminated from tournament |
| Lobby assembly | Players join manually | Matchmaking-assembled |
| Brackets | None | Shuffled per phase, no fixed seeding |
