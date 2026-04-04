# UnoArena — DDD Specification

Domain-Driven Design specification for **UnoArena**: a global real-time UNO platform supporting casual Quick Play rooms and massive elimination tournaments of up to 1,000,000 players.

The focus of this repository is behavior-complete domain modeling using EventStorming, with rigorous treatment of concurrency, edge cases, and cross-context consistency.

---

## Document Map

### Platform Rules (source of truth for all domain logic)

| Document | Contents |
|---|---|
| [specs/RULESET.md](specs/RULESET.md) | Complete UNO game rules: card set, turn mechanics, special cards, Draw Two stacking, jump-in, Wild Draw Four challenge, Uno! call, scoring, and win conditions |
| [specs/CONSTRAINTS.md](specs/CONSTRAINTS.md) | Platform-wide business rules: player accounts, room lifecycle, turn timer, AFK detection, disconnection and forfeit policies, state visibility, Elo system, game log, admin capabilities, rate limiting |
| [specs/TOURNAMENT_RULES.md](specs/TOURNAMENT_RULES.md) | All tournament-specific rules: elimination rounds, Bo3 match format, advancement and tie-breaks, match timeout, phase-start thresholds, tournament Elo |
| [specs/ASSUMPTIONS.md](specs/ASSUMPTIONS.md) | Explicit design assumptions (connection semantics, concurrency model, Elo rationale, auth mechanism) and open decisions deferred to implementation |

### DDD Design Deliverables

| # | Document | Contents |
|---|---|---|
| 1 | [design/GLOSSARY.md](design/GLOSSARY.md) | Authoritative ubiquitous language: all domain terms with precise definitions and anti-ambiguity notes |
| 2 | [design/CONTEXT_MAP.md](design/CONTEXT_MAP.md) | Bounded contexts, upstream/downstream relationships, event boundary contracts, Spectator View privacy treatment |
| 3 | [design/DOMAIN_MODEL.md](design/DOMAIN_MODEL.md) | Aggregates, entities, value objects, key invariants, and consistency boundaries |
| 4 | [design/COMMANDS_EVENTS.md](design/COMMANDS_EVENTS.md) | Full command and domain event catalog: preconditions, causality, idempotency, stale-version behavior |
| 5 | [design/EVENT_FLOWS.md](design/EVENT_FLOWS.md) | End-to-end event sequence narratives for room lifecycle, tournament round advancement, and Elo updates |
| 6 | [design/FAILURE_PATHS.md](design/FAILURE_PATHS.md) | Edge cases and failure-path analysis: concurrent conflicts, disconnections, stale commands, security/abuse, spectator privacy violations |
| 7 | [design/CONSISTENCY_RECOVERY.md](design/CONSISTENCY_RECOVERY.md) | Consistency and recovery strategy: retry/deduplication, compensation/saga decisions, invariant protection, projection reconciliation |
| 8 | [design/ASCII_FLOW.md](design/ASCII_FLOW.md) | EventStorming diagrams: room lifecycle, tournament round progression, disconnect/reconnect/forfeit flow, turn lifecycle |
| 9 | [design/REQUIREMENTS_TRACEABILITY.md](design/REQUIREMENTS_TRACEABILITY.md) | One-to-one traceability from assignment deliverable bullets to document sections; validated vs open decisions |

---

## Recommended Reading Order

1. [RULESET](specs/RULESET.md) — understand the game mechanics first
2. [CONSTRAINTS](specs/CONSTRAINTS.md) — understand platform rules and policies
3. [TOURNAMENT_RULES](specs/TOURNAMENT_RULES.md) — understand tournament structure
4. [GLOSSARY](design/GLOSSARY.md) — establish shared vocabulary
5. [CONTEXT_MAP](design/CONTEXT_MAP.md) — understand domain boundaries
6. [DOMAIN_MODEL](design/DOMAIN_MODEL.md) — understand consistency ownership
7. [COMMANDS_EVENTS](design/COMMANDS_EVENTS.md) — understand the behavioral contract
8. [EVENT_FLOWS](design/EVENT_FLOWS.md) — trace end-to-end flows
9. [ASCII_FLOW](design/ASCII_FLOW.md) — visualize the EventStorming outcomes
10. [FAILURE_PATHS](design/FAILURE_PATHS.md) — analyze every deviation
11. [CONSISTENCY_RECOVERY](design/CONSISTENCY_RECOVERY.md) — understand recovery strategy
12. [ASSUMPTIONS](specs/ASSUMPTIONS.md) — review assumptions and open decisions
13. [REQUIREMENTS_TRACEABILITY](design/REQUIREMENTS_TRACEABILITY.md) — verify completeness

---

## Key Design Decisions

- **EventStorming** is the primary discovery and analysis technique used to identify aggregates, commands, events, and policies.
- **Optimistic concurrency** via monotonic state version numbers serializes all game commands without distributed locking.
- **Eventual consistency** across bounded contexts via idempotent domain event consumers; no distributed transactions.
- **At-least-once delivery** assumed for all server-to-client and cross-context event propagation.
- **Server-authoritative timers** for all time-sensitive windows (turn timer, challenge windows, reconnection window).
- **Separate Elo ratings** for casual and tournament play; casual updated per game, tournament updated once post-tournament.
