# UnoArena — Lightweight Threat Model

This document applies a STRIDE analysis to the most security-sensitive surfaces of the UnoArena platform. For each threat, it names the affected component, the attack vector, and the existing architectural mitigation.

---

## Scope

**In scope:** Public API Gateway (REST + WebSocket), Identity/Session service (authentication), Room Gameplay service (game command integrity), session invalidation path, rate limiting bypass, Kafka event integrity.

**Out of scope:** Physical infrastructure security, cloud provider IAM, DDoS at the network layer (handled at the load balancer / CDN layer upstream of the gateway).

**Trust boundaries:**

1. **Public internet → API Gateway** (TLS, JWT)
2. **API Gateway → internal services** (mTLS, no JWT forwarding)
3. **Internal services → Kafka** (mTLS)
4. **Internal services → PostgreSQL / Redis** (VPC-internal, auth via connection string)

---

## STRIDE Analysis

### S — Spoofing

#### S1. JWT Spoofing — Forged Game Commands

**Threat:** An attacker forges a JWT to impersonate another player and submit game commands (`PlayCard`, `DrawCard`, etc.) on their behalf.

**Affected surface:** API Gateway JWT validation path.

**Mitigation:**
- All JWTs are signed with the Identity service's private key (RS256 or ES256). The gateway validates the signature locally using the public key loaded at startup.
- The gateway additionally checks `valid_sessions_from` against the Redis cache on every authenticated request. Even if an attacker obtains a valid JWT, they cannot use it after the session is invalidated.
- Signed JWTs cannot be forged without the private key, which never leaves the Identity service pod.

**Residual risk:** If the private key is compromised (key material exposure), all JWTs in circulation are forgeable until the key is rotated. Mitigation: short JWT TTL (15 minutes); key rotation procedure documented.

---

#### S2. Player Identity Spoofing — WebSocket Command Injection

**Threat:** An attacker who shares a gateway pod's WebSocket connection (e.g., a co-tenant exploiting a vulnerability in the WebSocket upgrade handler) injects commands with a spoofed `player_id`.

**Mitigation:**
- The gateway extracts `player_id` from the JWT on WebSocket upgrade and stores it in the connection context. All subsequent frames on that connection are tagged with the context `player_id` — the client cannot override it via the frame payload.
- Intra-cluster communication uses mTLS; external parties cannot send frames directly to room-gameplay-service.

---

#### S3. Session Token Replay After Logout

**Threat:** An attacker captures a JWT (e.g., via XSS on a companion web UI or a MITM on an unencrypted channel) and replays it after the legitimate player logs out.

**Mitigation:**
- `valid_sessions_from` is updated on logout/new-login. The gateway's Redis cache is invalidated (key DELeted) on logout. Any replayed JWT with `issued_at < valid_sessions_from` is rejected.
- JWT transport is enforced over TLS (`wss://`, `https://`). Non-TLS connections are refused at the load balancer.

---

### T — Tampering

#### T1. Game Event Tampering — Forged Kafka Events

**Threat:** An attacker injects a forged `GameCompleted` event into the `game-events` Kafka topic to alter Elo rankings or tournament standings.

**Affected surface:** Kafka topic, Ranking consumer, Tournament Orchestration consumer.

**Mitigation:**
- Kafka cluster is accessible only within the VPC (no public listener). Producers authenticate via mTLS certificates issued per-service.
- Each service has a dedicated producer credential; room-gameplay-service cannot produce to `tournament-events`, and vice versa.
- `GameCompleted` events carry a `game_id` that must correspond to a known `game_sessions` row in Room Gameplay's PostgreSQL. Consumers that receive an unknown `game_id` treat the event as invalid and send it to a DLQ for investigation — they do not silently process it.

**Residual risk:** A compromised internal service pod with mTLS credentials could inject events. Mitigation: regular credential rotation; pod-level network policies restricting which pods can connect to Kafka.

---

#### T2. Game State Tampering — Stale State Version Replay

**Threat:** An attacker (or a buggy client) replays an old game command with a stale `state_version` to rewind the game state.

**Mitigation:**
- The `SELECT … FOR UPDATE` on `game_sessions` reads the current `state_version`. Any command carrying a version number different from the current version is rejected with `409 Conflict`. The PostgreSQL row lock prevents two commands from racing to apply stale versions simultaneously.
- The `game_events` table is append-only. Even if a command is incorrectly accepted (which the row-lock prevents), the prior events remain in the log.

---

#### T3. Outbox Relay Tampering — Kafka Message Modification

**Threat:** A compromised outbox relay process modifies event payloads before publishing to Kafka.

**Mitigation:**
- The outbox relay reads `payload` (JSONB) directly from the PostgreSQL `outbox` table. The relay does not parse or modify the payload — it publishes bytes. A bug in the relay could drop events (delivery failure) but cannot inject new events without first writing to the outbox table, which requires a valid DB transaction.
- Outbox rows are written by the main application logic; the relay has `SELECT` and `UPDATE` access to the outbox table only, not `INSERT`.

---

### R — Repudiation

#### R1. Admin Action Repudiation

**Threat:** An admin claims they did not issue a `VoidGameResult` or `BanPlayer` command after the fact.

**Mitigation:**
- Every corrective admin action writes to `admin_actions` (append-only audit log) in the same PostgreSQL transaction as the downstream effect. The `admin_id` (from the admin's JWT) is stored alongside the action payload and timestamp.
- Admin JWTs are issued with a separate claim (`role: admin`) and a shorter TTL (5 minutes). Admin commands require a `role: admin` JWT — standard player JWTs cannot invoke admin endpoints.
- The audit log is shipped to a WORM-equivalent cold store (append-only S3 bucket with object lock) on a nightly basis.

---

#### R2. Player Cheating Repudiation

**Threat:** A player claims they did not play a certain card or challenge a Uno! call, disputing their Elo loss.

**Mitigation:**
- `game_events` is an immutable, append-only log. Each event records the `player_id`, the action, the `state_version`, and the server-assigned timestamp.
- Game log read path (see PERSISTENCE.md §1.6): Moderation can retrieve the full event log, including hand state at each decision point, to adjudicate disputes.
- All events are produced by the server (`room-gameplay-service`) based on commands received from the authenticated player's WebSocket connection. The player's client cannot produce events directly.

---

### I — Information Disclosure

#### I1. Spectator Hand Data Leakage

**Threat:** A spectator-facing API or WebSocket push includes card identities from a player's hand, allowing spectators to cheat by relaying hand information to players.

**Affected surface:** Spectator service; `PublicGameView` read model; Redis Streams.

**Mitigation:**
- Privacy whitelist filter is applied in `spectator-game-consumer-worker` before any data is written to the Redis Stream or Redis Hash. The filter is a static allowlist of public fields; all unlisted fields are dropped.
- The `public_game_logs` PostgreSQL table schema has no columns for hand card identities (structurally excluded).
- Spectator WebSocket connections are explicitly read-only at the gateway level; no command path exists from spectator connections to game state.

**Defense-in-depth:** A second filter at the spectator WebSocket send layer validates outbound messages. If a field unexpectedly appears in the Redis model (e.g., due to a filter regression), the send-layer filter drops it before delivery.

---

#### I2. JWT Payload Information Disclosure

**Threat:** JWT payload contains sensitive fields (email, device fingerprint) readable by any client that holds the token.

**Mitigation:**
- JWT payload contains only: `player_id` (UUID pseudonym), `issued_at`, `expires_at`, `role`. No PII in the JWT payload.
- Email is stored hashed in `player_profiles`; it is never included in tokens or event payloads.

---

#### I3. Game Command Interception (MITM)

**Threat:** An attacker intercepts WebSocket frames to read game commands or injected events.

**Mitigation:**
- All connections are over `wss://` (TLS). The load balancer enforces TLS 1.2 minimum; TLS 1.3 preferred.
- Certificate pinning is **recommended** for native (mobile/desktop) clients. In a competitive game where MITM access gives a card-reading advantage (reading spectator events or intercepting another player's resync snapshot), pinning raises the bar from generic TLS interception to device-level compromise. Browser clients rely on standard CA infrastructure; pinning is not applicable.

#### I4. Kafka Broker Compromise — Event Replay or Forgery

**Threat:** An attacker gains access to the Kafka broker (via compromised broker credentials or a broker-pod exploit) and publishes forged events (e.g., `GameCompleted` with manipulated outcomes) or replays previously consumed events to trigger duplicate Elo updates.

**Affected surface:** All downstream consumers (Ranking, Tournament Orchestration, Spectator View, Analytics).

**Mitigation:**
- Per-service mTLS producer credentials: only `room-gameplay-service` can produce to `game-events`; only `tournament-service` can produce to `tournament-events`. A compromised broker cannot produce events without a valid client certificate.
- Kafka ACLs restrict producers to their designated topics; cross-topic publishing is blocked at the broker level.
- Consumers apply idempotency checks using `(game_id, player_id)` or `(tournament_id)` keys, so replayed events are silently deduplicated — the replay does not cause duplicate Elo updates or duplicate tournament advancements.
- Downstream consumers validate event payload coherence: Ranking rejects `GameCompleted` events referencing unknown `game_id` values (sends to DLQ).

**Residual risk:** A broker with valid producer credentials could forge events that pass idempotency checks (novel `game_id` values). Mitigation: event payload signing (HMAC or payload hash included in the event, verified by consumers using a shared secret) would detect tampering, but adds operational complexity. Current mitigation relies on broker access control + regular credential rotation.

---

### D — Denial of Service

#### D1. WebSocket Flood — Unauthenticated Connection Exhaustion

**Threat:** An attacker opens thousands of WebSocket connections without authenticating, exhausting the gateway's file descriptor limit.

**Mitigation:**
- Per-IP connection limit enforced at the load balancer (max 10 concurrent WebSocket connections per IP).
- WebSocket upgrade requires a valid JWT. Connections that fail the upgrade JWT check are immediately closed with a `401 Unauthorized` WebSocket close code.
- Unauthenticated REST request rate limiting: 60 requests/min per IP via Redis fixed-window counter.

---

#### D2. Game Command Flood — Replay Attack on a Live Game

**Threat:** An attacker sends thousands of commands in rapid succession to a live game to exhaust room-gameplay-service request handling capacity.

**Mitigation:**
- Per-game-action rate limiting: 30 commands/min per player per action type (Redis fixed-window, enforced at API Gateway + room-gameplay-service).
- `SELECT … FOR UPDATE` serializes commands per game; concurrent flood of commands for the same game is serialized, not parallelized — the attacker cannot multiply their DB load by sending commands in parallel.
- Idempotency key reuse: replaying the same command with the same idempotency key returns the cached result (no additional DB write).

---

#### D3. Tournament Registration Flood

**Threat:** An attacker registers thousands of bot accounts for a tournament to fill slots and prevent legitimate players from participating.

**Mitigation:**
- Per-user rate limiting for `RegisterForTournament`: 10 registration actions/min per `player_id`.
- Account creation requires email verification (not modeled in this architecture but assumed per `specs/ASSUMPTIONS.md` §4). Fake accounts cannot be created in bulk without a valid email.
- Tournament organizers can set a registration verification gate (moderation-service `SetTournamentRegistrationPolicy`).

---

### E — Elevation of Privilege

#### E1. Player Invoking Admin Endpoints

**Threat:** A regular player calls `POST /v1/admin/games/{game_id}/void` to void their own game result.

**Mitigation:**
- Admin endpoints require `role: admin` claim in JWT. Standard player JWTs carry `role: player`. The gateway rejects requests to `/v1/admin/*` paths unless the JWT contains `role: admin`.
- Admin JWTs are issued only via a separate Identity/Session endpoint requiring a privileged login (separate admin credentials, not player credentials).

---

#### E2. Rate Limit Bypass via JWT Rotation

**Threat:** An attacker rotates JWTs rapidly (logging in on new devices) to reset the per-user rate limit counter, since the counter is keyed by `player_id`.

**Mitigation:**
- Rate limit keys use `player_id` (invariant) not `session_id` or `jwt_id`. JWT rotation does not change `player_id`; the rate limit counter persists across sessions.
- Login itself is rate-limited per IP (60 requests/min) and per `player_id` (via Identity/Session: 5 concurrent login attempts/min per `player_id`).

---

#### E3. Spectator → Player Privilege Escalation

**Threat:** A spectator connection attempts to submit game commands (PlayCard, DrawCard) to influence a game they are spectating.

**Mitigation:**
- The API Gateway enforces connection role at the WebSocket upgrade step. Connections upgraded at `wss://.../v1/spectator/*` are tagged `role: spectator` in the gateway's connection context.
- Any inbound frame on a spectator connection is rejected with a `1003 Unsupported Data` WebSocket close code. The frame is never forwarded to room-gameplay-service.
- room-gameplay-service additionally verifies that `player_id` from the JWT is a participant of `game_id` before accepting any command.

---

## Summary of Critical Mitigations

| Threat | Primary mitigation | Secondary |
|---|---|---|
| JWT spoofing | RS256/ES256 signature + `valid_sessions_from` check | Short JWT TTL + key rotation |
| Game state tampering | Optimistic concurrency (`state_version` + row lock) | Immutable `game_events` log |
| Spectator hand leakage | Privacy filter at Kafka consumption (before read model) | Send-layer whitelist defense-in-depth |
| Admin repudiation | Append-only `admin_actions` + WORM cold storage | Short-TTL admin JWTs |
| Command flood | Per-action rate limiting (gateway + service) | `SELECT FOR UPDATE` serialization |
| Privilege escalation | Connection-role tagging at WebSocket upgrade | Service-level participant verification |
| Kafka event injection | VPC-only listeners + per-service mTLS producer certs | Unknown `game_id` → DLQ |
