# UnoArena - Bounded Contexts and Context Map

This document defines context boundaries, ownership, and cross-context relationships.

---

## 1. Bounded Context Catalog

| Context | Primary Responsibility | Owns Write Model For |
|---|---|---|
| `Room Gameplay` | Card rules, turn sequencing, penalties, game completion, per-game standings | Game state, hands, discard/draw piles, turn order, per-game results |
| `Tournament Orchestration` | Tournament lifecycle, rounds, matchmaking into tournament rooms, Bo3 progression, advancement | Tournament instance, round state, room assignments, advancement decisions |
| `Ranking` | Casual Elo and tournament-placement Elo updates and leaderboard projections | Rating history, rating current values, leaderboard projections |
| `Identity/Session` | Registration, authentication/session state, single active session policy | Player account, active session tokens, session invalidation |
| `Spectator View` | Read projection for spectators with privacy filters | Public room/game projection only (no private card identities) |
| `Moderation/Admin` | Tournament setup/cancel, dispute review, enforcement actions | Admin decisions, moderation audits, overrides/voids |

---

## 2. Context Relationships

| Upstream | Downstream | Integration Style | Data Contract |
|---|---|---|---|
| Identity/Session | Room Gameplay | synchronous command guard + events | session validity, player identity, reconnect eligibility |
| Room Gameplay | Tournament Orchestration | domain events | game complete outcomes, forfeit outcomes |
| Tournament Orchestration | Ranking | domain events | tournament final placement, cancellation status |
| Room Gameplay | Ranking | domain events | casual game placement and score snapshot |
| Room Gameplay | Spectator View | event projection | public actions only, no hidden hand identities |
| Tournament Orchestration | Spectator View | event projection | room assignment and advancement status |
| Moderation/Admin | Tournament Orchestration, Ranking | command + events | cancel/override/void decisions with audit metadata |

---

## 3. Spectator Boundary Contract

### 3.1 Allowed data
- Player identities
- Hand counts only
- Top discard card and legal public history
- Turn ownership and direction
- Public score/placement information after completion

### 3.2 Forbidden data
- Any private hand card identities
- Any server-side hidden validation details before completion if rules require secrecy

### 3.3 Projection-driving events (minimum)
- `RoomCreated`
- `LobbyCountdownStarted`
- `GameStarted`
- `CardPlayedPublic`
- `CardDrawnPublic`
- `TurnAdvanced`
- `GameCompleted`
- `MatchCompleted`
- `TournamentRoundCompleted`

---

## 4. Ownership Rules

- One invariant has one aggregate owner in one context.
- Cross-context consumers treat events as immutable facts.
- No downstream context rewrites upstream historical facts.
- Compensation is additive (new events), never destructive mutation of event history.

---

## 5. Open Modeling Tasks

1. Freeze final event names and payload shape in `COMMANDS_EVENTS.md`.
2. Define anti-corruption mapping for admin overrides into ranking recalculation.
3. Document projection freshness guarantees for spectator and leaderboard read models.

