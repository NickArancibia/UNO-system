# ADR-001 — Client Connection Protocol

**Status:** Accepted  
**Context:** API Gateway; active players; spectators  
**Decided:** Phase 0 (R1)

---

## Context

UnoArena requires real-time, bidirectional communication between clients and the server for active gameplay (game commands and event pushes) and spectator observation (read-only event stream). The chosen protocol must:

- Support **sub-second event delivery** (5-second Uno! challenge window requires the gateway to push the window-open event to clients in well under 1 second).
- Support **server-initiated pushes** without client polling (timer expiry side effects, opponent moves).
- Be compatible with the **single-active-session** push-invalidation requirement (the gateway must be able to close a stale connection proactively).
- Scale to **1,000,000 concurrent active players and up to 10,000,000 spectators** at peak.
- Work across mobile and desktop browsers as well as native clients.

---

## Options Considered

### Option A — HTTP polling (short-poll)

Clients send repeated HTTP requests (e.g., every 500ms) to fetch new events.

**Strengths:** Simple to implement; stateless servers; compatible with every HTTP/1.1 infrastructure.

**Weaknesses:**
- 500ms polling interval = 500ms average delivery latency. The 5-second challenge window requires push, not polling; a 500ms lag consumes 10% of the window. At 1M players, 500ms polling = 2M requests/second at steady state — entirely from polling overhead, with no user intent behind any single request.
- Server-initiated session close is impossible; the gateway cannot terminate a stale connection — it can only reject the *next* poll. The old connection is gone, but the client continues functioning until it polls again.

**Verdict:** Rejected. Latency and load characteristics are incompatible with challenge-window precision and session invalidation requirements.

---

### Option B — Server-Sent Events (SSE, one-way)

Server pushes events over a persistent HTTP connection. Clients send commands via separate HTTP POST requests.

**Strengths:** Simpler server-side fan-out (chunked HTTP, no frame parsing); automatic reconnect built into browsers.

**Weaknesses:**
- **Half-duplex.** Commands and events use different connections, requiring correlation between them. State version mismatch handling becomes more complex (the command POST and the event SSE stream are on different TCP connections with no ordering guarantee between them).
- **Connection count.** Each active player holds two persistent connections (one for commands, one for SSE). At 1M players, that is 2M persistent connections at the gateway, doubling resource usage versus WebSocket.
- **Session invalidation.** The gateway can close the SSE stream, but the client's command channel is a new HTTP connection on every request — the gateway cannot preemptively block the old command connection; it can only validate the JWT on the next command arrival.

**Verdict:** Rejected. Half-duplex doubles the connection overhead and weakens the session-invalidation path relative to WebSocket.

---

### Option C — WebSocket (full-duplex, selected)

A single persistent bidirectional connection per client. Commands flow client→server; events flow server→client. Both share one TCP connection.

**Strengths:**
- **Full-duplex on one connection:** A single connection per player handles both commands and events. At 1M players, 1M connections (not 2M).
- **Server-initiated close:** The gateway issues a WebSocket close frame to terminate a stale session. The client is disconnected immediately — no waiting for the next command. This is the correct primitive for the single-active-session invariant.
- **Sub-millisecond push latency:** Events can be pushed immediately after the DB commit, with no polling interval overhead.
- **Browser and native client support:** WebSocket is universally supported. The `wss://` scheme provides TLS encryption identical to HTTPS.
- **Per-game ordering:** The single connection per player means the gateway delivers events to the player in the order it sends them — no reordering between command response and subsequent event pushes.

**Weaknesses:**
- **Stateful at the gateway:** The gateway maintains an in-memory connection registry (`player_id → WebSocket`) required for the session-invalidation push path. This is a deliberate architectural choice (see ADR-005) and is bounded to the active session count.
- **Long-poll fallback complexity:** Hostile networks (HTTP proxies that close idle connections) require a fallback. The chosen fallback is application-layer heartbeat (ping/pong every 30s) rather than a full long-poll fallback tier, avoiding the complexity of maintaining two protocol paths.

**Verdict:** Selected.

---

## Decision

**Use WebSocket (`wss://`) for active player connections and spectator connections.** Long-poll is not implemented as a fallback; instead, a 30-second application-layer ping/pong heartbeat keeps connections alive through proxies.

REST over HTTPS is used for non-realtime traffic: registration, login, tournament registration, analytics queries, admin commands.

---

## Rationale

1. **Challenge window precision:** A 5-second window requires the gateway to push the `ChallengeWindowOpened` event to all players in the game within a fraction of a second. WebSocket delivers this immediately after the outbox relay publishes the event — no polling interval overhead.

2. **Session invalidation completeness:** The gateway holds a WebSocket close primitive that can terminate the old connection in milliseconds after `SessionInvalidated` arrives via Redis Pub/Sub. SSE and polling cannot provide an equivalent server-side termination mechanism for the command channel.

3. **Connection efficiency:** One persistent connection per player is better than two (SSE + command) or many (polling) for the same throughput target. At 1M concurrent players, each connection saved is significant for gateway memory and file-descriptor limits.

4. **Operational simplicity:** One protocol for realtime traffic (WebSocket) versus two (SSE for events + REST for commands) reduces gateway complexity and eliminates cross-connection correlation edge cases.

---

## Consequences

- **API Gateway must be WebSocket-capable.** Standard reverse proxies (nginx, Envoy) support WebSocket upgrade natively; no special infrastructure is required.
- **Gateway holds connection state.** The in-memory `player_id → WebSocket` registry is scoped to active sessions (bounded by concurrent player count). On gateway restart, clients reconnect via the standard reconnect path.
- **Spectator WebSocket.** Spectator connections follow the same WebSocket model but are routed to `spectator-service`. Spectators are read-only: the gateway rejects any inbound frame from a spectator connection.
- **Load balancer sticky sessions are NOT required.** The connection registry is per-gateway-instance; Redis Pub/Sub fans the session-invalidation signal to all instances. However, for spectator delivery, all WebSocket connections for a given `game_id` on the same gateway instance share one Redis Stream read loop (efficient). Sticky sessions at the load balancer improve Redis read efficiency for spectators but are not correctness-critical.
