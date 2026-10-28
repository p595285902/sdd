## Context

The JavaScript acceptance runner starts a PID-named Compose project in `BeforeAll`, runs database prestart, waits for the backend, and removes that project's volumes in `AfterAll`. The backend image contains both backend and frontend source; a fresh Playwright context and preview-workload cleanup occur per scenario, but application records and named volumes remain until suite teardown. The initial-data script migrates/seeds; it does not reset an existing database. The suite currently builds/checks images at startup, not per scenario.

The target is faster repeated local runs without changing the existing default/CI lifecycle. A warm stack must remain acceptance-only, tolerate runner crashes without trusting leftover data, and fail before scenarios if it cannot prove a clean start.

## Goals / Non-Goals

**Goals:**

- An explicit local command keeps one healthy backend alive between test invocations, including filtered invocations.
- Each warm invocation exclusively owns its stack, refreshes changed application/config inputs, then resets and verifies every persistent state store before running scenarios.
- Default and CI runs remain fresh and project-scoped; failures are visible and recoverable.
- Establish repeatable cold/repeat full-suite timing and only accept the change if median repeat time improves by at least 30% without new flakes.

**Non-Goals:**

- Parallel Cucumber workers, multiple shared warm projects, or changes to the normal development stack's behavior.
- Reusing data, mail, previews, or browser contexts across invocations; bypassing the full acceptance gate.

## Decisions

### Separate explicit warm lifecycle from the default lifecycle

Expose an opt-in local runner command plus an explicit acceptance-only teardown/recovery command. Identify its project by a stable checkout-specific acceptance identity rather than process ID; keep its allocated port and non-secret provenance discoverable across processes. Check actual Docker project ownership/labels and health before any reset or teardown. Never infer ownership from a user-provided Compose name alone. Keep PID-scoped projects and volume-removing `AfterAll` for default/CI. Do not silently turn on warm reuse in CI.

Alternative: automatically reuse every test invocation. Rejected because it changes CI and existing test expectations and makes dirty-state failures harder to diagnose.

### Serialize warm invocations and fail closed

Acquire an exclusive lock before inspecting, starting, resetting, or rebuilding the warm project; hold it through the test run and release it even on failure. Lock ownership must recover when the runner process dies, rather than permanently blocking subsequent invocations. A competing command reports stack-in-use without mutating the first run's project. Do not reset or stop an unknown or normal development project.

Alternative: let processes share one backend. Rejected because one process's reset can invalidate another's scenarios.

### Reset in place, then verify, before any scenario

On every warm run, first stop leftover preview workloads and wait for their cleanup. Reset application-owned database records (preserving migrations and reseeding the initial acceptance administrator), development workspaces, and captured mail if the mail service/store exists. Restrict destructive operations to the verified acceptance project and its named resources. Verify the required baseline and absence of prior-run state in all stores, including after an interrupted run; any error aborts the run with an explicit fresh-stack recovery instruction. Keep the backend process running if inputs and configuration are unchanged. Maintain per-scenario browser contexts and independent, scenario-owned fixtures. Do not replace whole stateful volumes on the normal reuse path.

Alternative: destroy and recreate volumes on each invocation. Rejected for the warm path because it requires restarting dependencies and may forfeit much of the intended speedup; it remains a safe manual recovery path.

### Refresh only when build/config inputs change

Record a digest of relevant Docker build inputs (including changed and untracked source), acceptance Compose/runtime configuration, and the inputs that control the baked backend/frontend and preview-controller images. Exclude generated outputs and the warm-run metadata itself. Never store credentials or their raw values in the provenance file. If provenance is missing, inputs cannot be evaluated, or a stack is unhealthy, do not claim a warm hit: rebuild/recreate the acceptance-only stack or report a clear error. On detected changes, build and restart that stack, run required initialization, then perform the same reset/verification before scenarios. Capture the effective acceptance configuration so a still-running backend never serves an older configuration.

Alternative: rely only on `git HEAD` or `--build` cache checks. Rejected because uncommitted changes and configuration drift can leave a running container with stale code.

### Validate speed and behavior independently

Use focused runner/lifecycle tests with controlled Docker process boundaries for locking, reset failures, drift, recovery, and unchanged default teardown. Implement delta acceptance steps without recursively launching the entire acceptance suite for each scenario. Run the effective suite and source-of-truth regression, exercise a warm full run and filtered rerun, and compare several identical clean cold/full and warm/full runs on the same host. Record durations and calculate the median repeat-run improvement against baseline; a green suite alone does not meet the 30% target.

Alternative: enable Cucumber `--parallel` now. Rejected because workers would share application state, preview naming can escape project scoping, and Mailpit declares global container name/ports. Parallelism requires separately approved isolated projects and measurement showing scenario time is the remaining bottleneck.

## Risks / Trade-offs

- [Incomplete reset or a crashed test leaves hidden state] -> Reset and verify all stores at the start of every invocation; fail closed and provide project-scoped recovery.
- [A warm backend holds stale DB connections, configuration, or code] -> Verify readiness and effective inputs, recreate when needed, and exercise an interrupted-run recovery test.
- [A second process resets a live run] -> Exclusive process-lifetime locking and ownership checks before Docker mutations.
- [Image/input fingerprint misses an untracked or ignored build input] -> Derive provenance from actual build/config inputs, test both tracked and untracked edits, and refuse uncertain reuse.
- [Warm mode complicates the suite yet saves less than expected] -> Baseline first, retain the default path, and enforce the measured 30% median improvement before adopting it.

## Migration Plan

1. Baseline cold and repeat full-suite timings without changing the default runner.
2. Add focused lifecycle tests and opt-in warm mode; verify an interrupted run, stale inputs, concurrent use, failed reset, and protected non-acceptance projects.
3. Run full effective and source-of-truth suites, repeat warm/full runs, and publish timing results. If the threshold or reliability gate fails, leave default/CI unchanged and do not recommend warm mode.
4. Roll back by stopping only the verified acceptance warm project and returning to the existing default command.

## Open Questions

- The exact safe database reset and initial-data verification must account for current migrations, session pools, and background tasks; validate it against real acceptance data before implementing.
- Confirm which mail and preview services are actually started by the acceptance profile so a missing service is checked as absent rather than mistakenly counted as a successful cleanup.
