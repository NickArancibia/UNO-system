# UnoArena - Domain Glossary

This glossary is the authoritative ubiquitous language for the project.
When terms differ from generic UNO usage, this file wins.

---

## 1. Core Terms

| Term | Definition |
|---|---|
| `game` | One individual UNO session that ends when a player empties their hand (or terminal exception applies). |
| `match` | Tournament-room Best-of-Three (Bo3) series of up to 3 games with the same active players. |
| `round` | One elimination tier in a tournament; players are redistributed into new rooms each round. |
| `tournament` | Full multi-round competition that ends with a Final Room and one champion. |
| `room` | Runtime container where players compete or spectate; includes lobby and active play states. |
| `active player` | Player currently participating in gameplay and not forfeited. |
| `forfeit` | Permanent removal from the current game or tournament progression, depending on mode. |
| `placement` | Ordered finish rank for a player in a game, match, room, or tournament context. |
| `advancement` | Qualification from current tournament round into the next round. |
| `state version` | Monotonic game state counter used for optimistic concurrency control. |
| `idempotency key` | Client-provided UUID that guarantees duplicate command replay safety. |

---

## 2. Scoring and Ranking Terms

| Term | Definition |
|---|---|
| `game score` | Per-game numeric score where winner gets `0` and others get negative values based on hand card values. |
| `card-point burden` | Non-negative sum of remaining card values used for tie-break reasoning. A game score of `-22` contributes burden `22`. |
| `match_wins` | Number of games won by a player inside a tournament Bo3 match. |
| `room ranking` | Final order of players in a tournament room used to decide top-3 advancement. |
| `tie-break` | Ordered deterministic rules applied when primary ranking metric is equal. |

---

## 3. Timer and Window Terms

| Term | Definition |
|---|---|
| `turn timer` | 45-second timer for turn action in normal gameplay. |
| `Uno challenge window` | 5-second window where opponents may challenge missed Uno call. |
| `WD4 challenge window` | 5-second window for next player to challenge Wild Draw Four legality. |
| `reconnection window` | 60-second window after disconnect before automatic forfeit. |
| `match timeout` | 20-minute hard cap for full tournament Bo3 match duration. |

---

## 4. Boundary Terms

| Term | Definition |
|---|---|
| `Room Gameplay context` | Context owning in-game mechanics, rule enforcement, and per-game outcomes. |
| `Tournament Orchestration context` | Context owning rounds, room assignment, advancement, and tournament lifecycle. |
| `Ranking context` | Context owning casual Elo and tournament-placement Elo calculations and persistence. |
| `Identity/Session context` | Context owning accounts, sessions, and login invalidation semantics. |
| `Spectator View context` | Read-only projection context that exposes only public gameplay information. |

---

## 5. Ambiguity Guardrails

- Do not use `round` to mean repeated turns inside one game.
- Do not use `score` without clarifying `game score` or `card-point burden`.
- Do not use `winner` without scope (`game winner`, `match winner`, `tournament champion`).
- `match` is tournament-only; casual mode uses one `game` with no match layer.

