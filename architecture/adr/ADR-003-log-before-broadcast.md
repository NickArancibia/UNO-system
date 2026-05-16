# ADR-003 — Log-Before-Broadcast Mechanism

**Status:** Accepted  
**Context:** Room Gameplay service  
**Decided:** Phase 1

---

## Context

Every accepted game command must be durably written to the immutable game log **before** any client or downstream service can observe the resulting state change. This is a non-negotiable invariant from the design: if the service crashes between writing the log and broadcasting the event, the event must not be lost, and no broadcast must precede the log write.

The system must also guarantee that events reach Kafka at-least-once (for downstream consumers) while the game log in PostgreSQL is the single source of truth.

---

## Options Considered

### Option A — Direct dual-write (command handler writes to both DB and Kafka)

The command handler updates PostgreSQL, then publishes to Kafka in the same code path.

**Problem:** If the process crashes after the PostgreSQL commit but before the Kafka publish, the event is lost from Kafka but present in the log — inconsistency. If Kafka is written first and then PostgreSQL commit fails, the event appears in Kafka without being in the log — a false broadcast. There is no atomic operation spanning both systems.

**Verdict:** Rejected. The dual-write problem is unsolvable without a distributed transaction, which would couple Room Gameplay to Kafka's transaction protocol and add significant complexity and latency.

---

### Option B — Full event sourcing (write only to event store; derive state from events)

All commands produce events appended to an event store. Aggregate state is never stored directly — it is rehydrated from the event log on each command. Kafka publishing is driven from the event store.

**Strengths:** True single source of truth; natural audit log; log-before-broadcast is inherent.

**Weaknesses:**
- Rehydrating `GameSession` state (108-card deck, 10 players, 7 cards each, turn state) from an event log on every command adds significant read amplification. A game with 200 turns has 400–1000 events; rehydrating each command requires reading all of them.
- Snapshots are required to bound rehydration cost, adding infrastructure.
- Operational complexity of an event store (schema evolution, snapshot management, replay on migration) is high.

**Verdict:** Rejected for this system. The game state is complex and command-intensive; the rehydration cost would directly increase per-command latency. The outbox achieves the same correctness guarantees with simpler infrastructure.

---

### Option C — Transactional outbox (selected)

The command handler executes a **single PostgreSQL transaction** that writes:
1. Updated aggregate state (`game_sessions` row).
2. Immutable event record(s) (`game_events` rows — the game log).
3. Relay target(s) (`outbox` rows — one per event to be broadcast).

A background thread (outbox-relay-worker) independently reads undelivered outbox rows and publishes them to Kafka using an idempotent producer. Only after Kafka ACK does the relay mark the row delivered.

---

## Decision

**Use the transactional outbox pattern.**

---

## Rationale

The outbox achieves all three requirements simultaneously:

1. **Log-before-broadcast atomicity:** The `game_events` row and the `outbox` row are written in the same PostgreSQL transaction. If the transaction commits, both exist. If it rolls back, neither exists. There is no window in which a broadcast can precede the log entry.

2. **At-least-once delivery to Kafka:** The relay worker replays from the last undelivered row on restart. Combined with Kafka's idempotent producer (`enable.idempotence=true`), duplicate relay attempts are safe — Kafka deduplicates by producer sequence number.

3. **Simplicity over event sourcing:** The `game_sessions` row holds current aggregate state (JSONB), allowing O(1) command processing — acquire row lock, read state, validate, update, commit. No rehydration cost. The `game_events` table is the append-only log for audit and dispute resolution; it does not participate in the command processing hot path.

---

## Consequences

- **Latency:** The relay introduces a small delay between `COMMIT` and Kafka delivery (typically 10–100ms depending on poll interval). Clients receive their own command result immediately (the Gateway forwards the response after commit); other consumers see events slightly later. This is acceptable — the 5-second challenge window gives ample time for spectators to see the event.
- **Relay lag monitoring:** Kafka consumer lag on `game-events` is the primary health signal for the relay. An alert on lag > 1,000 messages triggers on-call investigation.
- **Outbox table growth:** Delivered rows can be deleted after a configurable retention window (e.g., 24h) by a background cleanup job. This keeps the table small without affecting correctness.
- **Exactly-once semantics for consumers:** Not provided by the relay (at-least-once). All consumers must implement idempotency (documented per-event dedup keys in `design/CONSISTENCY_RECOVERY.md`).

---

## PostgreSQL Schema (reference)

```sql
-- Current aggregate state
CREATE TABLE game_sessions (
    game_id       UUID PRIMARY KEY,
    room_id       UUID NOT NULL,
    state_version INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL,          -- initializing | in_progress | completed
    state         JSONB NOT NULL,         -- full GameSession aggregate as JSONB
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Immutable game log (never updated or deleted)
CREATE TABLE game_events (
    id            BIGSERIAL PRIMARY KEY,
    game_id       UUID NOT NULL,
    state_version INTEGER NOT NULL,
    event_type    TEXT NOT NULL,
    payload       JSONB NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (game_id, state_version, event_type)
);

-- Outbox (relay targets; deleted after delivery + retention window)
CREATE TABLE outbox (
    id            BIGSERIAL PRIMARY KEY,
    game_id       UUID NOT NULL,
    event_type    TEXT NOT NULL,
    payload       JSONB NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered     BOOLEAN NOT NULL DEFAULT false,
    delivered_at  TIMESTAMPTZ
);

CREATE INDEX ON outbox (delivered, id) WHERE delivered = false;
```
