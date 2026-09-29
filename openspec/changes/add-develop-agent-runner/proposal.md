## Why

A ready Development Workspace needs deterministic agent execution before long-lived turn coordination and streaming can be introduced. This change follows `add-develop-workspace-setup` and isolates external CLI integration and its security boundaries.

## What Changes

- Add a production command runner with process-group cancellation, stderr draining, timeout, failure, and blocking support.
- Exercise the production runner and real OpenCode process against a programmable local OpenAI-compatible fake LLM in acceptance tests.
- Run exploration inside only the owning chat's Development Workspace.
- Normalize newline-delimited `opencode` events and persist bounded activity, response text, and validated session continuity.
- Scrub configured secrets from logs, errors, events, and persisted output.

## Capabilities

### New Capabilities

- `develop-agent-runner`: Deterministic external-agent execution, event normalization, session continuity, output bounds, cancellation primitives, and secret scrubbing.

### Modified Capabilities

None.

## Impact

- Agent service, production command runner, process fixtures, event fixtures, settings, persistence integration, and focused backend tests.
- Acceptance support runs real OpenCode against a programmable local fake LLM and never calls an external provider.
- Requires `add-develop-workspace-setup` to be implemented first.
