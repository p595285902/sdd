## Context

The JavaScript acceptance runner starts a PID-scoped Compose project once per full-suite run and removes that project's volumes in `AfterAll`. Every scenario receives a new browser context, but scenarios in the same run share the backend, database, and development-workspace volume. `configureDemoRepository` currently forces a backend recreation for every request, including repeated requests for the already-active configuration. Most callers request the configured repository; one scenario requests the unconfigured state. Restarting the backend does not clean database records or workspace files, but it does clear process-local test state.

The first observed source-of-truth full run took 20m 5s with one intermittent preview timeout; a later user run took 18m 23s with the six active-delta scenarios still undefined. Neither is a matched, green before/after benchmark. The goal is to remove unnecessary backend recreations during a single run, not to keep a stack running between runs.

## Goals / Non-Goals

**Goals:**

- Avoid a Compose backend recreation when the requested demo-repository configuration already matches the running backend.
- Apply genuine configured-to-unconfigured and unconfigured-to-configured transitions before a scenario uses the backend.
- Preserve scenario behavior and isolation previously provided incidentally by backend restarts, while keeping PID-scoped default and CI teardown.
- Measure comparable full-suite runs and record the actual improvement without requiring a predetermined percentage.

**Non-Goals:**

- Reuse a stack across separate full-suite runs, optimize Docker image builds, or parallelize scenarios.
- Reset all database records, workspaces, mail, or preview workloads between scenarios; retain existing scenario-owned fixtures and cleanup.
- Change production configuration semantics or the normal development Compose project.

## Decisions

### Track the configuration applied to the live backend

Start with an explicit, fixed acceptance demo-repository configuration rather than inheriting an ambiguous host override. Track the effective configuration and backend container identity after successful startup or recreation. If the requested state matches the verified live backend, return without calling Compose. On a genuine change, recreate only the acceptance backend with the requested environment, wait for health, and update the tracked state only after success. If identity or health cannot be established, fail explicitly or recreate the owned backend; never treat uncertain state as an unchanged warm hit.

Alternative: compare only `state.env` or always call `docker compose up`. Rejected because `state.env` alone does not establish what is running, and `up` can still recreate a container or spend time checking it.

### Preserve process-local test isolation explicitly

Audit fixtures that implicitly rely on a forced restart to clear in-memory state, notably fake LLM replies and mutable turn settings. Reset only the affected acceptance-only test state before scenarios that could observe prior state; use the existing acceptance-mode test interface or a narrowly scoped addition if it cannot currently express an empty reset. Wait for scenario-owned background work and preview cleanup before resetting shared state. Keep a fresh browser context and existing scenario cleanup. Do not equate skipping a restart with clearing persistent database or workspace data.

Alternative: skip recreations with no fixture audit. Rejected because scenarios could see stale fake replies or runtime settings despite the correct demo-repository environment.

### Measure matched full-suite runs

Record scenario counts, backend recreation counts, wall times, and pass/fail results for multiple fresh full-suite runs before and after the change on the same host and scenario set. Compare medians without a fixed speed threshold. The suite must be green with zero pending or undefined steps before declaring implementation complete; a transient failure is investigated or reported, not silently counted as a pass. Keep the existing source-of-truth regression and effective-suite gates.

Alternative: infer a percentage gain from startup duration or from a filtered run. Rejected because the optimization targets recreations *during* the scenarios, not only initial startup.

## Risks / Trade-offs

- [Cached configuration disagrees with the live container] -> Confirm backend identity and health, and invalidate cached state when the container changes unexpectedly.
- [A skipped restart leaks process-local test state] -> Audit affected fixtures and add focused consecutive-scenario tests with explicit cleanup.
- [A scenario genuinely needs missing demo credentials] -> Recreate only on that configuration transition and verify the restored state afterward.
- [Persistent data causes order dependence] -> Preserve existing unique fixtures and cleanup; do not claim a database/workspace reset that this change does not implement.
- [No measurable improvement or a flaky suite] -> Record actual results and do not claim a performance or reliability win without matched green runs.

## Migration Plan

1. Establish matched fresh-run timing and recreation-count baselines; identify which scenarios call the configuration helper and rely on process-local resets.
2. Add focused tests, implement configuration-aware backend recreation and any necessary acceptance-only state reset, then validate consecutive scenarios and genuine transitions.
3. Run the effective suite and source-of-truth regression, compare multiple full-suite samples on the same scenario set, and update the acceptance runner documentation. Revert the optimization if it breaks isolation or reliability.

## Open Questions

- Which process-local state beyond fake LLM replies and mutable turn settings was being cleared by unconditional backend recreations? Resolve with focused tests before skipping those restarts.
