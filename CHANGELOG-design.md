# Design Changelog

This file documents all changes made to the design package after the Design Checkpoint submission, as required by the Architecture Checkpoint (§6.2). Each entry names the affected artifact, cites the original deliverable number and title, states the reason for the change, and confirms that no Design Checkpoint non-negotiable domain guarantee was weakened.

---

## Post-grading fixes (applied after Design Checkpoint feedback)

### 1. `design/COMMANDS_EVENTS.md` — Deliverable 4: Commands and domain events catalog

**Change:** Added `reason: SkipCard|StackEffect|Disconnect` field to the `PlayerSkipped` event payload.

**Reason:** The evaluator noted that the distinction between a turn skip caused by a Skip card, a Draw Two/WD4 stack effect, and a disconnection-induced skip was only inferrable from context. Making the reason explicit in the payload removes ambiguity for downstream consumers (Spectator View, Analytics) that must differentiate these causes.

**Non-negotiable check:** No domain guarantee affected. The `PlayerSkipped` event already existed; this adds a field that was always implicit in the domain logic.

---

### 2. `design/EVENT_FLOWS.md` — Deliverable 5: Domain event flow narratives

**Change (Flow 4 Phase B):** Added an explicit statement to the reconnection snapshot description clarifying that the resync payload includes the reconnecting player's own hand and all public game state, but never other players' card identities.

**Reason:** The evaluator flagged that the privacy boundary during reconnection was implicit rather than stated. The architecture requires this to be explicit because the resync snapshot is a distinct code path from the normal event stream and must apply the same privacy filter.

**Non-negotiable check:** No domain guarantee weakened. The privacy rule (hands are never visible to other players or spectators) was already enforced; this entry makes it explicit in the reconnection path.

---

### 3. `design/EVENT_FLOWS.md` — Deliverable 5: Domain event flow narratives

**Change (Flow 3 Phase B):** Added a blockquote note at the top of the Tournament Elo Update phase explicitly stating that tournament-placement Elo is entirely separate from casual Elo, is updated once per `TournamentCompleted` (not per game), and that casual Elo is never touched by tournament events.

**Reason:** The evaluator awarded partial credit because the separation, while correct in the domain model, was not stated clearly enough in the flow narrative. The architecture requires this distinction to be unambiguous because the Ranking context routes `GameCompleted` and `TournamentCompleted` events to separate Elo computation paths.

**Non-negotiable check:** No domain guarantee weakened. The separation of casual and tournament Elo was already a non-negotiable in the design; this entry documents it more explicitly in the flow.

---

### 4. `design/DOMAIN_MODEL.md` — Deliverable 3: Aggregates, entities, value objects

**Change (PlayerSession invariant 2):** Reworded to make the session creation sequence explicit: the new JWT is issued first (establishing the new session), then `valid_sessions_from` is updated and `SessionInvalidated` is emitted. The original wording described the result but not the ordering.

**Reason:** The architecture requires this sequence to be unambiguous because the push-invalidation path (Identity/Session → gateway → close old live connections) depends on the new session being valid before the old one is revoked. A gap would leave the player without a valid token.

**Non-negotiable check:** The single-active-session invariant is unchanged. The ordering clarification strengthens rather than weakens the guarantee.

---

## Architecture Checkpoint changes

### 5. `design/CONTEXT_MAP.md` — Deliverable 2: Bounded contexts and context map

**Change:** Fixed incorrect tie-break criterion in Tournament Orchestration responsibilities. Line previously read "cumulative cards remaining" as the third advancement tie-break; corrected to "cumulative finish time" to match `specs/TOURNAMENT_RULES.md` Section 4 and all other design documents.

**Reason:** Copy error from the pre-fix version of the design. The criterion was already correct in every other file after the post-grading fix pass; this file was missed.

**Non-negotiable check:** The correct tie-break order (match wins → card-point burden → cumulative finish time) is now consistent across all documents. No domain guarantee was weakened; the error was a documentation inconsistency, not a model change.

---

### 6. `design/CONTEXT_MAP.md` — Deliverable 2: Bounded contexts and context map

**Change:** Extracted a new **Analytics / Read Models** bounded context (section 2.6; Moderation/Admin renumbered to 2.7). Updated the context overview diagram, the relationships text block, the relationship types table, and the cross-context event contracts table to reflect the new context and its upstream producers.

**Reason:** The Architecture Checkpoint (§6.1) explicitly requires a dedicated treatment of the `game.completed` spike at tournament round end — "partitioning, consumer groups, dedicated projection workers; how the projection pipeline absorbs the burst without pushing backpressure into Room Gameplay writers." The original design distributed this responsibility across Spectator View (real-time projection) and Ranking (leaderboard), neither of which was scoped to absorb a 100,000-event burst or serve historical query-optimized read models. Extracting Analytics gives the architecture a clear, independently scalable home for:

- Player statistics aggregation (games played, win rate, historical game lists)
- Tournament bracket trees and round-by-round standings
- Leaderboard display views (display copies derived from `EloUpdated`; Ranking remains authoritative)
- Absorbing the burst of `GameCompleted` events at round end via dedicated partitioned consumers decoupled from Room Gameplay write throughput

**Non-negotiable check:** No domain guarantee is weakened or moved:
- Authoritative Elo computation remains in Ranking.
- Spectator View retains sole ownership of the real-time, per-turn game stream with its privacy ACL.
- Room Gameplay retains sole ownership of game state and the immutable game log.
- Analytics is a pure downstream projection — it accepts no commands and enforces no invariants. All invariants stay in their original owning aggregates.
