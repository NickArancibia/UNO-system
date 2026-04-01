# UnoArena - Edge Cases and Failure Paths

This document structures mandatory failure-path coverage from the assignment.

---

## 1. Concurrent Conflicting Actions

| Scenario | Expected domain behavior | Events emitted |
|---|---|---|
| Two players submit jump-in simultaneously | First valid command by state version wins; others rejected | `JumpInAccepted`, `ActionRejectedConflict` |
| Two players challenge Uno simultaneously | First valid challenge processed; duplicates rejected | `UnoChallengeResolved`, `ActionRejectedDuplicateWindow` |
| Stale play command after turn advanced | Reject with conflict, no mutation | `ActionRejectedConflict` |

---

## 2. Disconnections and Late Rejoin

| Scenario | Expected domain behavior | Events emitted |
|---|---|---|
| Player disconnects mid-game | Start reconnection window; turns skipped | `PlayerDisconnected`, `ReconnectWindowStarted` |
| Player reconnects within window | Restore active participation and state sync | `PlayerReconnected`, `GameStateResyncCompleted` |
| Reconnect attempt after window expiry | Reject rejoin; player already forfeited | `PlayerForfeited`, `ReconnectRejectedWindowExpired` |

---

## 3. Stale and Replayed Commands

| Scenario | Expected domain behavior | Events emitted |
|---|---|---|
| Command with old state version | Reject with conflict, include current version hint | `ActionRejectedConflict` |
| Duplicate command id sent again | Return original result, no duplicate mutation | no new event or `DuplicateCommandAcknowledged` |
| Same user sends repeated rapid actions | Domain-level one-action-per-turn invariant blocks extras | `ActionRejectedInvalidTurnAction` |

---

## 4. Partial Failures Between Contexts

| Scenario | Expected domain behavior | Events emitted |
|---|---|---|
| `GameCompleted` delivered late to Ranking | Eventual consistency; ranking updates once consumed | `CasualEloUpdated` (late but once) |
| Ranking consumer crashes after compute before persist | Retry idempotently using event id | `RankingUpdateRetried` then rating event |
| Tournament cancel arrives while ranking queue pending | Cancel policy wins; suppress tournament Elo updates | `TournamentCancelled`, `TournamentEloUpdateSuppressed` |

---

## 5. Security and Abuse Scenarios

| Scenario | Expected domain behavior | Events emitted |
|---|---|---|
| Session takeover by new login | Old session invalidated immediately | `PlayerSessionInvalidated`, `PlayerDisconnected` (if in game) |
| Action flood from one actor | Rate limit and escalation policy applied | `ActionRateLimitExceeded`, `PlayerAbuseWarningIssued`, `PlayerSessionSuspended` |
| Unauthorized admin action attempt | Reject and audit | `AdminActionRejectedUnauthorized` |

---

## 6. Spectator Privacy Violations

| Scenario | Expected domain behavior | Events emitted |
|---|---|---|
| Spectator requests player hand identities | Reject; return only allowed projection | `SpectatorDataAccessDenied` |
| Projection pipeline leaks hidden fields | Detect schema violation and quarantine projection update | `ProjectionPolicyViolationDetected`, `ProjectionUpdateBlocked` |
| Player attempts to query via spectator channel | Enforce role-based read policy | `UnauthorizedDataRequestRejected` |

---

## 7. Bo3-Specific Edge Cases

| Scenario | Expected domain behavior | Events emitted |
|---|---|---|
| Tie at top-3 cutoff after both tie-breakers | Apply deterministic fallback policy (to be finalized) | `AdvancementTieRequiresFallback` |
| Match timeout during Game 2 | Resolve active game instantly, award match win, end match | `TournamentMatchTimeoutReached`, `MatchWinAwarded`, `TournamentMatchCompleted` |
| Forfeit leaves one active player | End match immediately, auto-advance active player | `PlayerForfeited`, `TournamentMatchCompleted`, `AdvancementResolved` |

---

## 8. Remaining Gaps

1. Final deterministic fallback policy for unresolved Bo3 ties.
2. Exact audit payload minimums for dispute replay.
3. Operational response policy for projection corruption incidents.

