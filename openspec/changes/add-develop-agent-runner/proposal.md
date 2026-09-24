## Why

A ready Development Workspace needs deterministic agent execution before long-lived turn coordination and streaming can be introduced. This change follows `add-develop-workspace-setup` and isolates external CLI integration and its security boundaries.

## What Changes

- Add production and deterministic fake command runners with process-group cancellation, stderr draining, timeout, failure, blocking, and scripted event support.
- Run exploration inside only the owning chat's Development Workspace.
- Normalize newline-delimited `opencode` events and persist bounded activity, response text, and validated session continuity.
- Scrub configured secrets from logs, errors, events, and persisted output.

## Capabilities

### New Capabilities

- `develop-agent-runner`: Deterministic external-agent execution, event normalization, session continuity, output bounds, cancellation primitives, and secret scrubbing.

### Modified Capabilities

None.

## Impact

- Agent service, command runners, event fixtures, settings, persistence integration, and focused backend tests.
- Acceptance support uses only the fake runner and never external services.
- Requires `add-develop-workspace-setup` to be implemented first.
