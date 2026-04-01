# UnoArena - Consistency and Recovery Strategy

This document defines domain-level consistency and recovery behavior.
It avoids infrastructure implementation specifics and focuses on business correctness.

---

## 1. Consistency Principles

1. Aggregate-local invariants are strongly consistent at command handling time.
2. Cross-context consistency is eventual and event-driven.
3. Event consumers must be idempotent.
4. Recovery uses additive compensating events, not history mutation.

---

## 2. Command-Side Consistency Controls

- Optimistic concurrency via `expected_state_version`.
- Idempotency via `command_id`.
- Hard rejection for stale or invalid commands.
- Deterministic conflict resolution where race conditions occur.

---

## 3. Event-Side Recovery Controls

- At-least-once event handling assumption.
- Consumer dedup by immutable event id.
- Retry on transient consume/persist failures.
- Dead-letter with manual replay path for permanent failures.

---

## 4. Compensation Policies

| Failure type | Compensation approach |
|---|---|
| Admin voids completed game after Elo update | Emit `GameResultVoidedByAdmin`, then `EloAdjustmentReverted` |
| Tournament cancelled after partial progress | Emit `TournamentCancelled`; suppress or revert pending tournament Elo updates |
| Projection drift from source events | Rebuild projection from event history; emit `ProjectionRebuilt` |

---

## 5. Bo3 Consistency Rules

- Match ranking data must include:
  - `match_wins`
  - cumulative card-point burden
  - cumulative cards remaining
  - forfeit state
- Advancement decision must be reproducible from persisted match snapshot.
- Timeout and forfeit terminal rules must produce one and only one `TournamentMatchCompleted`.

---

## 6. Reconciliation Procedures

### 6.1 Read model lag
- Source-of-truth aggregates remain authoritative.
- Read model catches up asynchronously.
- User-facing projections may be stale but must converge.

### 6.2 Event replay
- Replay by aggregate stream or time slice.
- Dedup remains active during replay to avoid double side effects.

### 6.3 Drift detection
- Periodic consistency checks compare aggregate snapshots to read models.
- On mismatch, trigger projection rebuild and audit event.

---

## 7. Open Recovery Decisions

1. Maximum acceptable staleness window for leaderboard projections.
2. Policy for replay ordering across independent context streams.
3. Automated vs manual trigger policy for rebuild on drift detection.

