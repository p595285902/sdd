## Context

This final change follows `add-develop-proposal-workflow`. Develop depends on external CLIs, persistent local workspaces, long-lived SSE, and a process-local turn manager. The current backend deployment uses four FastAPI workers.

## Goals / Non-Goals

**Goals:**

- Package and verify compatible runtime tools.
- Persist Development Workspaces across container replacement.
- Align worker and proxy topology with process-local coordination.
- Validate production configuration without exposing credentials.

**Non-Goals:**

- Distributed turn coordination or multi-host workspace sharing.
- Automatic workspace quotas and retention.
- Provider-neutral agent packaging.

## Decisions

### Install pinned compatible CLIs in the backend image

Install `git`, `opencode`, and `openspec` using versions compatible with the reference workflow where available. Verify their presence during image build and expose no credentials in image layers.

Alternative considered: install tools at container startup. That adds network dependency and makes deployments nondeterministic.

### Persist the configured workspace root

Mount a named volume at the configured Development Workspace root. Keep repository and provider credentials in runtime environment or secret injection only.

### Run one FastAPI worker initially

Change the backend command from four workers to one. Document that multiple workers or hosts require durable coordination, a shared event log, distributed admission, and shared workspace storage.

Alternative considered: retain four workers with process-local state. Reattach and stop requests could reach a different worker and fail incorrectly.

### Make SSE infrastructure requirements explicit

Disable proxy buffering, set idle timeouts beyond the heartbeat interval, and preserve streaming response headers. Production startup rejects incomplete Develop configuration; acceptance mode rejects real runner selection.

## Risks / Trade-offs

- [One worker reduces request parallelism and availability] -> Accept for initial correctness and defer distributed coordination explicitly.
- [Workspace volume grows] -> Delete with chats and monitor storage; quotas remain future work.
- [CLI package sources drift] -> Pin versions and verify executables in image tests.

## Migration Plan

Build and verify the image, add workspace storage and environment configuration, switch to one worker, document proxy settings, and run full backend/frontend/acceptance validation. Rollback disables Develop routes and restores the prior worker command; do not destructively remove the volume.

## Open Questions

None.
