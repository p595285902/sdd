## Why

The acceptance runner already shares its main stack, but repository-configuration transitions still recreate the backend and per-scenario cleanup leaves database, workspace, and background state behind. Replace those restarts with a verified state-reset boundary so normal scenarios run serially on one unchanged real stack, without confusing this change with mocked responses, warm Python fixtures, or cross-run persistence.

## What Changes

- Start one fresh project-scoped stack for each normal scenario-suite invocation; retain its backend, database, preview-controller, and stack volumes until final teardown. No between-scenario restart, recreation, or extra lifecycle-probe stack is permitted.
- Add acceptance-only, run-authenticated reset/status APIs that quiesce old work, remove scenario-owned resources, reset database/workspace/agent state, restore the declared baseline, and acknowledge only verified completion.
- Apply acceptance repository-configuration changes through verified scenario overrides rather than changing container environment or recreating services. Production configuration behavior remains unchanged.
- Preserve fresh browser/request contexts. Reset only between scenarios, not between fixture operations that intentionally share a scenario's data.
- Fail the invocation and tear down its owned resources if reset, configuration verification, or service-identity checks fail; do not restart and silently continue.
- **BREAKING (test harness):** move lifecycle probes out of the normal scenario suite into separately reported serial lifecycle validation. The complete acceptance gate must execute both disjoint effective-scenario groups; a standalone normal-suite run is explicitly partial validation.
- Preserve real chat-preview start/restart/expiration behavior. Removing disposable preview workloads during reset is not a restart of the long-lived application stack.

## Capabilities

### New Capabilities

- `acceptance-state-reset`: Protected, bounded, idempotent reset of acceptance-owned mutable state with quiescence, baseline verification, and safe failure behavior.

### Modified Capabilities

- `acceptance-stack-reuse`: One unchanged stack for serial normal scenarios, API-backed configuration transitions, and fresh-run lifecycle coverage executed separately without silently omitting effective scenarios.

## Impact

- Runner lifecycle/hooks, API helpers, page objects, effective-profile selection, reporting, and CI acceptance targets.
- Acceptance-only backend reset coordination, turn/setup/preview admission and drain tracking, canonical database reseeding, confined workspace/agent storage cleanup, and an internal controller reset interface. Docker ownership stays with the controller.
- Acceptance Compose configuration gains run-scoped reset credentials and ownership/storage configuration; no new fixture microservice or arbitrary-script endpoint is required.
- Existing `reuse-acceptance-preview-inputs` and `use-git-for-preview-change-detection` changes remain separate. Reset must not preserve mutable chat state or stale observations; verified immutable run-local preparation may survive when its complete-input contract remains satisfied.
- No production reset API, scenario concurrency, cross-run stack retention, warm-import optimization, or database schema teardown. Record matched normal-suite and complete-gate timings separately; the prior POC's speedups do not measure this proposal.
