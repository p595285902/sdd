## Why

The completed Develop workflow depends on local CLIs, persistent workspace storage, SSE-compatible proxy behavior, and process-local coordination. This final change follows `add-develop-proposal-workflow` and makes those operational assumptions explicit and deployable.

## What Changes

- Install and verify compatible `git`, `opencode`, and `openspec` executables in the backend runtime image.
- Add persistent Development Workspace storage and documented environment configuration without committing credentials.
- Run the initial backend deployment with one FastAPI worker because turn coordination is process-local.
- Document SSE buffering, heartbeat, and timeout requirements.
- Reject unsafe or incomplete production Develop configuration while preserving deterministic test modes.

## Capabilities

### New Capabilities

- `develop-runtime`: Runtime packaging, persistent workspace storage, startup validation, single-worker topology, and SSE deployment requirements.

### Modified Capabilities

None.

## Impact

- Backend image, Compose configuration, deployment documentation, environment settings, and startup tests.
- Requires `add-develop-proposal-workflow` to be implemented first.
