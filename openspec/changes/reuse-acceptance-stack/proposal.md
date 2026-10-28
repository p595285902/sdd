## Why

Repeated local acceptance runs currently create and tear down an isolated Compose stack on every invocation, even when the application image and configuration have not changed. We want faster feedback without hiding stale code, retaining test data, or weakening the default and CI suite.

## What Changes

- Measure cold and repeated full-suite wall time before and after the change; ship warm reuse only if median full-suite repeat time improves by at least 30% while the full suite stays green without new flakes.
- Provide an opt-in local workflow that keeps an acceptance-only backend running across invocations and resets and verifies persistent test state before every invocation, including filtered runs.
- Detect changes to relevant source and configuration, including uncommitted changes, and automatically rebuild/restart the acceptance stack rather than testing stale code.
- Reject concurrent use of the same warm stack; fail clearly when reset or verification cannot establish a clean run.
- Preserve fresh isolated stacks for the default runner and CI. Defer parallel workers and the Compose isolation they would require.

## Capabilities

### New Capabilities

- `acceptance-stack-reuse`: Local acceptance stack lifecycle, clean-state guarantees, freshness, concurrency, and performance validation.

### Modified Capabilities

None.

## Impact

- Acceptance runner hooks, application lifecycle, reset/verification helpers, documentation, and focused runner tests.
- Docker Compose orchestration of the acceptance project and its database, workspaces, preview workloads, and optional mail store.
- No production application API or normal development Compose behavior changes; parallel execution is out of scope.
