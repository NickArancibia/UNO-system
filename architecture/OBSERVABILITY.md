# UnoArena — Observability Architecture

This document specifies the logging, metrics, tracing, and alerting architecture for UnoArena. Observability is a first-class concern given the 5-second Uno! challenge window, the 60-second reconnection timer, the 100K-room round kickoff surge, and the single-active-session push-invalidation requirement — all of which require sub-second detection of anomalies.

---

## 1. Three Pillars

| Pillar | Technology | Scope |
|---|---|---|
| Structured logs | Fluentd / Loki | Per-request and per-event logs from all service pods |
| Metrics | Prometheus + Grafana | Per-service RED metrics (Rate, Errors, Duration); domain-specific counters |
| Distributed traces | OpenTelemetry → Jaeger / Tempo | Correlation across async (Kafka) and sync (HTTP) flows via `correlation_id` |

Each service pod includes a sidecar:
- **Metrics sidecar:** Prometheus exporter (scrapes `/metrics` endpoint on the service).
- **Log shipper sidecar:** Fluentd agent (collects stdout structured logs; ships to Loki).
- **Trace agent:** OpenTelemetry Collector (receives spans from the service SDK; batches to Jaeger/Tempo).

Services emit structured logs to stdout only. No log files. The sidecar handles forwarding.

---

## 2. Correlation IDs

Every request and event carries a `correlation_id` that traces the full causal chain across services.

### 2.1 Propagation Rules

| Context | `correlation_id` value | Propagation path |
|---|---|---|
| Game command | `game_id` | Set by Gateway on WebSocket upgrade; forwarded in `X-Correlation-ID` HTTP header to room-gameplay-service; written to `outbox` rows; carried in Kafka message headers |
| Tournament lifecycle | `tournament_id` | Set on `CreateTournament` command; propagated through tournament-events, tournament-kickoff, and into room-gameplay-service room-creation commands |
| Session lifecycle | `session_id` | Set on Login; propagated through identity-events; used in reconnection window rows |
| Admin action | `action_id` | Set on admin command receipt; propagated through moderation-events |

### 2.2 Kafka Message Headers

Every Kafka message includes:
```
correlation_id: <game_id | tournament_id | session_id>
event_type: <GameCompleted | PlayerForfeited | …>
producer_service: <room-gameplay-service | identity-service | …>
schema_version: <integer>
produced_at: <ISO-8601 timestamp>
```

Consumers extract `correlation_id` from the Kafka header and attach it to all log entries and child spans for that message.

---

## 3. Structured Log Schema

All service logs are JSON lines to stdout. Mandatory fields:

```json
{
  "timestamp": "2026-05-16T14:30:00.123Z",
  "level": "INFO",
  "service": "room-gameplay-service",
  "pod": "room-gameplay-7d9b4c-xkp2q",
  "correlation_id": "game_id:G-abc123",
  "player_id": "P-def456",
  "event": "command_accepted",
  "command_type": "PlayCard",
  "state_version_before": 14,
  "state_version_after": 15,
  "duration_ms": 23
}
```

### 3.1 Key Log Events Per Service

**room-gameplay-service:**

| Event name | Level | Fields |
|---|---|---|
| `command_accepted` | INFO | `game_id`, `player_id`, `command_type`, `state_version_before`, `state_version_after`, `duration_ms` |
| `command_rejected_version_mismatch` | WARN | `game_id`, `player_id`, `command_type`, `expected_version`, `received_version` |
| `command_rejected_illegal_play` | WARN | `game_id`, `player_id`, `command_type`, `reason` |
| `timer_set` | INFO | `game_id`, `timer_type` (`turn` | `challenge`), `token`, `ttl_ms` |
| `timer_fired` | INFO | `game_id`, `timer_type`, `token`, `is_relevant` (bool: token match result) |
| `timer_cancelled` | INFO | `game_id`, `timer_type`, `token` |
| `outbox_relay_published` | INFO | `outbox_id`, `topic`, `partition`, `offset`, `duration_ms` |
| `outbox_relay_failed` | ERROR | `outbox_id`, `topic`, `attempt`, `error` |

**identity-service:**

| Event name | Level | Fields |
|---|---|---|
| `session_created` | INFO | `player_id`, `session_id`, `device_hint` |
| `session_invalidated` | INFO | `player_id`, `session_id`, `reason` |
| `reconnect_window_opened` | INFO | `player_id`, `game_id`, `expires_at` |
| `reconnect_window_expired` | INFO | `player_id`, `game_id` |
| `reconnect_window_cancelled` | INFO | `player_id`, `game_id` |

**API Gateway:**

| Event name | Level | Fields |
|---|---|---|
| `websocket_connected` | INFO | `player_id`, `connection_id`, `role` (`player` | `spectator`) |
| `websocket_closed` | INFO | `player_id`, `connection_id`, `reason` (`client_close` | `session_invalidated` | `jwt_expired` | `rate_limit`) |
| `session_invalidation_received` | INFO | `player_id`, `invalidated_at`, `connections_closed` (int) |
| `rate_limit_exceeded` | WARN | `player_id`, `ip`, `limit_type`, `limit_value` |

---

## 4. Metrics

All metrics are exposed at `/metrics` in Prometheus format.

### 4.1 Universal RED Metrics (per service)

| Metric | Labels | Notes |
|---|---|---|
| `http_requests_total` | `service`, `method`, `path`, `status_code` | All HTTP endpoints |
| `http_request_duration_seconds` | `service`, `method`, `path` | Histogram with buckets 5ms, 10ms, 25ms, 50ms, 100ms, 250ms, 500ms, 1s |
| `websocket_connections_active` | `service`, `role` | Gauge; active WebSocket connections |
| `kafka_consumer_lag` | `consumer_group`, `topic`, `partition` | Sourced from Kafka JMX / Consumer Group API |
| `kafka_messages_consumed_total` | `consumer_group`, `topic`, `event_type` | Counter |
| `kafka_messages_produced_total` | `service`, `topic` | Counter |

### 4.2 Domain-Specific Metrics

**room-gameplay-service:**

| Metric | Type | Labels | Alert threshold |
|---|---|---|---|
| `game_commands_total` | Counter | `command_type`, `result` (`accepted` | `rejected_version` | `rejected_illegal`) | — |
| `game_active_total` | Gauge | `game_type` | — |
| `timer_fires_total` | Counter | `timer_type`, `is_relevant` | `is_relevant=false` rate > 5% → investigate ghost timers |
| `outbox_undelivered_age_seconds` | Gauge | — | > 30s → alert: relay is stalled |
| `game_command_duration_seconds` | Histogram | `command_type` | P99 > 200ms → alert |

**tournament-service:**

| Metric | Type | Labels | Alert threshold |
|---|---|---|---|
| `kickoff_rooms_enqueued_total` | Counter | `tournament_id`, `round_number` | — |
| `kickoff_rooms_created_total` | Counter | `result` (`success` | `retry` | `dlq`) | `dlq` rate > 0 → alert |
| `kickoff_consumer_lag` | Gauge | `consumer_group` | > 5,000 messages → alert during round start |
| `match_games_started_total` | Counter | `game_sequence` | — |
| `match_timeout_fires_total` | Counter | — | — |

**identity-service:**

| Metric | Type | Labels | Alert threshold |
|---|---|---|---|
| `session_invalidations_total` | Counter | `reason` | — |
| `reconnect_windows_active` | Gauge | — | — |
| `reconnect_windows_expired_total` | Counter | — | — |
| `vsf_cache_hits_total` | Counter | — | Hit rate < 90% → investigate cache TTL |

**API Gateway:**

| Metric | Type | Labels | Alert threshold |
|---|---|---|---|
| `websocket_connections_active` | Gauge | `role` | > 1.1M active players → capacity alert |
| `session_invalidations_processed_total` | Counter | — | — |
| `rate_limit_hits_total` | Counter | `limit_type` | Sudden spike → DDoS indicator |

**Kafka consumer lag (cross-service):**

| Consumer group | Alert threshold | Rationale |
|---|---|---|
| `tournament-game-cg` | > 10,000 messages | Match state may be delayed during round surge |
| `spectator-game-cg` | > 5,000 messages | Spectator updates > ~5s delayed |
| `analytics-game-cg` | > 500,000 messages | Analytics catching up post-restart; not time-critical |
| `ranking-cg` | > 1,000 messages | Elo update delay (acceptable to ~60s) |

---

## 5. Distributed Tracing

### 5.1 Trace Propagation

Every inbound HTTP request to the API Gateway generates a root span. `correlation_id` is set as a trace attribute. The span context (W3C `traceparent` header) is forwarded:
- On HTTP calls: via `traceparent` header.
- On Kafka messages: via `traceparent` Kafka header alongside `correlation_id`.

### 5.2 Key Trace Spans

**PlayCard hot path trace (end-to-end):**

```
[Gateway: websocket_frame_received]  5ms
  └── [Gateway: jwt_validate]  2ms
  └── [Gateway → room-gameplay: http_post]  3ms
        └── [room-gameplay: db_lock_acquire]  10ms
        └── [room-gameplay: command_validate]  2ms
        └── [room-gameplay: db_transaction]  15ms
              └── [db: game_sessions_update]
              └── [db: game_events_insert]
              └── [db: outbox_insert]
        └── [room-gameplay: response_send]  1ms
  └── [Gateway: websocket_push_to_client]  1ms
[outbox_relay: kafka_publish]  (async, separate trace linked by correlation_id)
```

**GameCompleted → EloUpdated cross-context trace:**

The Kafka message header carries the `traceparent` from the Room Gameplay transaction. The Ranking service creates a child span linked to the parent trace, enabling the full causal chain to be visualized in Jaeger across two services connected only by Kafka.

### 5.3 Sampling Strategy

| Traffic type | Sampling rate | Rationale |
|---|---|---|
| PlayCard (hot path) | 1% | At 50K cmd/s, 1% = 500 traces/s; sufficient for latency analysis |
| Session invalidation | 100% | Low frequency; always trace for security audit |
| Timer fires (relevant) | 100% | Low frequency; full trace for correctness verification |
| Timer fires (irrelevant / no-op) | 10% | Detect ghost timer anomalies |
| Tournament kickoff (per room) | 10% | At 100K rooms, 10% = 10K traces |
| `GameCompleted` processing | 5% | At 100K/round, 5% = 5K traces for round analysis |

---

## 6. Tournament Round Health Dashboard

This Grafana dashboard is the primary operational view during a tournament round. Panels:

| Panel | Metric source | Alert condition |
|---|---|---|
| Active matches | `game_active_total{game_type="tournament"}` | < expected rooms for round phase |
| Kickoff progress | `kickoff_rooms_created_total` / `kickoff_rooms_enqueued_total` | Progress < 90% after 120s of round start |
| Kickoff DLQ count | `kickoff_rooms_created_total{result="dlq"}` | > 0 |
| Kickoff consumer lag | `kickoff_consumer_lag` | > 5,000 messages |
| game-events Kafka lag (tournament-game-cg) | `kafka_consumer_lag{consumer_group="tournament-game-cg"}` | > 10,000 messages |
| Match completions/min | Rate of `MatchCompleted` events | Below expected rate for round duration |
| Outbox relay age | `outbox_undelivered_age_seconds` | > 30s |
| Game command P99 latency | `http_request_duration_seconds{p99}` | > 200ms |
| WebSocket active connections | `websocket_connections_active` | Sudden drop (mass disconnect) |
| Session invalidations/min | `session_invalidations_total` | Spike > 10× baseline → investigate |

---

## 7. Alerting Runbook Summary

| Alert | Service | Likely cause | First action |
|---|---|---|---|
| `outbox_undelivered_age > 30s` | room-gameplay | Kafka unavailable or relay crashed | Check Kafka broker health; check relay pod logs |
| `kickoff_consumer_lag > 5000` | tournament/room-gameplay | Room Gameplay pods overwhelmed during surge | Scale room-gameplay pods; check PostgreSQL connection pool |
| `kickoff_rooms_created_total{result=dlq} > 0` | tournament | Room creation failing after retries | Check DLQ topic; investigate room-gameplay errors for affected room IDs |
| `game_command P99 > 200ms` | room-gameplay | PostgreSQL lock contention or slow query | Check `pg_stat_activity` for long-running lock holders; check index health |
| `vsf_cache_hits < 90%` | identity/gateway | Redis cache miss spike (thundering herd on session start) | Check Redis memory; verify TTL jitter is applied |
| `websocket_connections drop > 20%` | gateway | Gateway pod restart or load balancer issue | Check gateway pod count; client reconnect rate should spike |
| `session_invalidations spike > 10×` | identity | Mass logout event or security incident | Check identity-service logs for cause; if unauthorized, escalate to security |
| `timer_fires{is_relevant=false} > 5%` | room-gameplay | Ghost timers accumulating (cancelled but still firing) | Check Lua conditional delete path; verify `timer_token` fence in PostgreSQL |
