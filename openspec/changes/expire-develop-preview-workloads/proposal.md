## Why

Per-chat preview workloads consume resources and must not outlive the chat that owns them.

## What Changes

- Stop an idle chat preview after five minutes without visible Context activity.
- Restart or delete only the selected chat's workload; reconcile orphaned workloads after controller restart.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `develop-preview-runtime`: Add lifecycle and idle expiry to the isolated workload capability.

## Impact

Controller lifecycle, chat deletion cleanup, clock-driven tests. Follows `isolate-develop-preview-controller` after its delta is synced.