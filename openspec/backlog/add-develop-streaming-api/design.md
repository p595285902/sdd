## Context

This change follows `add-develop-turn-lifecycle`. The process-local manager can coordinate and replay turns, but clients need an authenticated live transport. Existing authentication uses bearer JWTs, which browser `EventSource` cannot attach.

## Goals / Non-Goals

**Goals:**

- Expose start and reattachment streams with existing bearer authentication.
- Preserve normalized event order, replay-before-live behavior, and ownership.
- Keep idle streams alive and prevent proxy buffering.

**Non-Goals:**

- WebSockets or bidirectional messaging.
- Frontend presentation and cache behavior.
- Distributed stream routing.

## Decisions

### Use fetch-based SSE

FastAPI returns `StreamingResponse` with `text/event-stream`, no-cache headers, proxy buffering disabled, and 15-second heartbeats. The frontend later consumes it with `fetch` so it can attach `Authorization: Bearer`.

Alternative considered: browser `EventSource`. It cannot carry the application's bearer header. WebSockets add a bidirectional protocol without a requirement.

### Keep one normalized wire format

Serialize `session`, `status`, `text`, `error`, `idle`, and `done` events. Reattachment subscribes through the manager, emits buffered events first, and then forwards live events until terminal completion.

Alternative considered: expose manager objects directly. That couples clients to internal concurrency state.

### Reuse ownership-scoped lookup

Resolve every stream and control request by chat ID plus current User ID. Missing and foreign resources return the same response. Disconnect cleanup always unregisters the subscriber.

## Risks / Trade-offs

- [Proxy buffering hides incremental events] -> Set no-buffering headers and document proxy requirements in the runtime change.
- [Idle infrastructure closes streams] -> Emit configurable heartbeats.
- [Disconnect leaks subscribers] -> Unsubscribe in generator finalization and cover cancellation paths.

## Migration Plan

Add JSON controls and SSE routes, API tests, generated JSON client operations, and a hand-written stream adapter contract, then implement the reattachment scenario. Rollback unregisters routes without affecting active manager internals.

## Open Questions

None.
