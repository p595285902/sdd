## Why

Agent operations need an explicit lifecycle for concurrency, cancellation, disconnection, and resource limits before they are exposed as durable streams. This change follows `add-develop-agent-runner` and contains the process-local coordination state machine.

## What Changes

- Add one active Agent Turn per Development Chat with explicit stop and timeout handling.
- Add buffered event replay, subscriber tracking, and reattachment support.
- Add `Stop when I leave` and `Continue in background` Presence Modes with grace-period behavior.
- Enforce per-user background limits and weighted global concurrency capacity.
- Stop an active turn before deleting its chat and workspace.

## Capabilities

### New Capabilities

- `develop-turn-lifecycle`: Process-local Agent Turn coordination, replay, cancellation, presence behavior, admission control, and bounded completion persistence.

### Modified Capabilities

None.

## Impact

- Turn manager, concurrency gate, timers, process cancellation, settings, persistence hooks, and focused concurrent tests.
- Initial coordination remains confined to one backend process.
- Requires `add-develop-agent-runner` to be implemented first.
