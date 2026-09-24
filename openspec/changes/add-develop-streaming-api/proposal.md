## Why

Managed Agent Turns need an authenticated transport that supports ordered live events and replay without changing the application's bearer-token authentication model. This change follows `add-develop-turn-lifecycle` and exposes that lifecycle through FastAPI.

## What Changes

- Add bearer-authenticated SSE endpoints for starting and reattaching to Agent Turns.
- Emit normalized events with heartbeats, no-cache headers, and proxy buffering disabled.
- Add JSON endpoints for Presence Mode updates and explicit stop operations.
- Preserve indistinguishable not-found responses for missing and foreign chats.
- Regenerate the typed client for JSON operations while keeping SSE in one hand-written adapter.

## Capabilities

### New Capabilities

- `develop-streaming-api`: Authenticated JSON and SSE contracts for managed Agent Turns, replay, heartbeats, stopping, and presence updates.

### Modified Capabilities

None.

## Impact

- FastAPI routes, SSE serialization, JWT authorization, OpenAPI output, generated client, and API tests.
- Requires `add-develop-turn-lifecycle` to be implemented first.
