## Context

The selected boundary is strict: one unchanged main application stack for the normal scenario suite, with lifecycle probes moved to separate validation. Each invocation still starts fresh and tears down; there is no cross-run persistence.

Observed implementation:

- `acceptance-tests/features/support/hooks.js` starts/stops the stack in global hooks and creates fresh browser contexts. `ApiClient.resetScenarioState()` resets only the fake provider and turn timing controls. World disposal stops previews registered by that page helper, not all persisted or orphan state.
- `app-lifecycle.js` verifies Docker environment values and force-recreates the backend on repository changes or failed health/identity checks. Its unit test explicitly expects that recovery behavior. Both must change to verified API configuration and fail-closed identity checks.
- `acceptance-stack-reuse.steps.js` contains two child-process lifecycle probes inside a normal scenario. Move their real startup/teardown coverage, not merely their cost or reported scenario count.
- Postgres contains users, items, chats, and messages. User cascades do not clean up runtime/workspace resources. `init_db()` only creates a missing administrator; it does not repair modified credentials or privileges, and `crud.create_user()` commits internally.
- The backend turn manager retains active sessions, timers, subscribers, and weighted capacity. Streamed execution has completion writes and preview startup after the agent process exits. Cancellation acknowledgement is not proof that all work has joined.
- The controller is a separate threaded service with Docker ownership and read-only workspace access. It retains routing/failure/activity maps and creates resources labeled with the preview project/chat. The backend has writable workspace access but no Docker socket. Existing per-chat deletion cannot comprehensively discover orphans.
- Agent execution inherits HOME/XDG storage. Workspace deletion alone does not prove persisted OpenCode state was cleared. Existing testing endpoints are mode-gated but unauthenticated; the new destructive controls require independent run credentials.
- The existing preview-input reuse proposal concerns verified immutable preparation, not live workload or stack retention. The Git-observation proposal remains separate.

No checked-in `.github/workflows/` directory was found. The user confirmed on 2026-11-04 that no CI exists. Repository acceptance commands and documentation are the integration deliverable for this change; creating CI is out of scope and no deployed CI coverage is claimed. Any future acceptance-consuming CI job must use the complete gate defined here.

## Goals / Non-Goals

**Goals:**

- One healthy backend/database/controller stack and the same mounted stack volumes throughout normal serial scenarios.
- Real API-driven reset, with known ownership, actual quiescence, canonical baselines, verification, and bounded failure.
- Repository transitions without restarts or loss of fixtures within the transitioning scenario.
- Explicit separate lifecycle validation while complete effective-spec coverage and CI gating remain intact.
- Independently measured normal-suite, reset, lifecycle-validation, and total acceptance elapsed time.

**Non-Goals:**

- Keeping a stack alive between invocations, concurrent scenarios, or retaining a live preview for another chat.
- Replacing real application behavior with mocks or accepting arbitrary Python/shell scripts through reset APIs.
- Implementing the warm-import worker, Git observer, preview cache, faster health checks, or controller signal POCs.
- Resetting production data, dropping the database schema, deleting mounted stack volumes, or cleaning unrelated resources.
- Guaranteeing automatic teardown after host loss or uncatchable process termination; controlled cancellation is covered.

## Decisions

### 1. Separate the single-stack suite from lifecycle validation, with an explicit complete gate

Create disjoint execution groups from fresh effective-spec discovery. Normal cases run in one Cucumber process with ordinary application hooks. Lifecycle, non-acceptance-mode registration, and intentionally terminal reset-failure cases run in a separately supported validation profile after the normal stack is torn down. That profile does not run the normal `BeforeAll` application hook and cannot accidentally create a third background stack.

Move the current probe helpers into a lifecycle flow/page object with a dedicated World and support imports. It performs real serial fresh startup/teardown invocations, including failure/cancellation cases. Normal steps remain intent-level and do not embed Docker commands. Ordinary preview tests retain their real disposable containers and restart behavior.

Use stable capability/requirement/scenario identities to classify the freshly composed inventory, not a historical timing report or brittle line-number list. `Fresh-run lifecycle remains unchanged`, `Separate validation groups retain complete effective-spec coverage`, the non-acceptance-mode reset-control case, and `Unverified reset fails the invocation without a replacement stack` belong to dedicated validation; other cases belong to the normal suite. Source-of-truth profiles use the same classification so existing lifecycle coverage remains executable before sync.

Command-validation cases invoke the real complete-gate entry point against freshly extracted/composed isolated fixture inventories containing bounded normal and lifecycle scenarios, not against the repository inventory that contains the command-validation cases themselves. This avoids recursive suite invocation and keeps extra stacks out of the normal group. The fixture inventories exercise serial teardown ordering, successful and failing group outcomes, HTML reports, newly added cases, and duplicate/incomplete discovery rejection. They use the same discovery/orchestration implementation and real lifecycle helpers; they do not mark repository cases skipped or claim that fixture success replaces the full repository gate. The outer complete invocation independently audits its own actual assignments/results after both groups finish.

The complete acceptance entry point orchestrates both groups serially, announces assignments, checks a disjoint complete inventory, preserves the existing effective composition/exclusion report, combines status, and emits HTML reporting for both groups. Standalone normal-suite and lifecycle targets are explicitly partial. CI and sync/archive require the complete gate. Do not call a quicker partial target the full suite or report deliberately unexecuted lifecycle coverage as passed/skipped. On fatal execution failure, report the abort and unexecuted assigned cases, return failure, and still perform cleanup.

Alternative rejected: retain nested probes as a documented exception. The user selected strict single-stack normal execution instead. Simply removing/tagging the probes out without separately required coverage is also rejected.

### 2. Add a narrow authenticated acceptance control plane, not a fixture microservice

Proposed backend routes under the existing testing namespace:

- `POST /api/v1/testing/acceptance/reset`: run identity, reset identifier, and expected generation; no caller-selected resource roots.
- `GET /api/v1/testing/acceptance/state`: generation, reset phase, effective configuration mode, quiescence/baseline status, and non-secret diagnostics.
- `PATCH /api/v1/testing/acceptance/configuration`: only the declared demo baseline's available/unavailable mode.

The runner generates a high-entropy reset credential and run identity at startup and supplies them to the backend/controller through acceptance Compose configuration. Authenticate reset/status/configuration independently of application users, so a scenario that deletes the administrator cannot disable cleanup. Never put reset credentials in URLs, browser contexts, normal frontend responses, or diagnostic output. Non-acceptance deployments do not register these routes.

Bind operations to the actual owned acceptance database, named workspace/runtime roots, controller project, and run identity established at startup. Validate the owned Compose database/network configuration before enabling destructive controls; do not infer safety from a client-provided project name or acceptance flag alone. Reject wrong credentials, identity, generation, or resource selection before any mutation. The controller's new internal bulk-reset endpoint has its own acceptance-mode/run-credential gate and remains unpublished on the internal control network. The backend calls it through `PreviewController`; it never gains the Docker socket.

Alternatives rejected: public admin reset using a database-user token, arbitrary SQL/path/project parameters, or an unrestricted script-execution service.

### 3. Treat reset as a bounded state machine with a real drain barrier

A single reset coordinator owns generation, admission state, active-work tracking, reset identifiers, and the declared baseline. Suggested phases are admitting, quiescing, cleaning previews, cleaning files, resetting database, restoring controls, verifying, ready, and failed.

Use a finite total reset deadline (initial design default: 60 seconds) and hook/client deadlines with margin above it. Reject concurrent conflicting reset/configuration requests. Keep health and authenticated diagnostic/reset-status access available while ordinary mutating admissions are closed.

Ordered reset:

1. Close admissions for turn execution, setup, proposal/preview operations, and other mutating requests. Record the current generation and request cancellation.
2. Join all generation-owned execution, provider requests, streamed generators/completion handlers, setup, preview preparation/launch, and relevant controller maintenance. Track worker completion through encompassing `finally` blocks; an HTTP response header, cleared registry, cancellation flag, or exited agent subprocess is insufficient.
3. Ask the controller to remove all scenario-owned preview resources and routing/failure/activity state, including orphans discovered without DB rows. Keep admissions closed through cleanup/verification.
4. Remove confined checkout, credential-temp, fixture-output, and agent runtime state after their consumers have stopped. Preserve mounted roots and ownership metadata.
5. Restore the owned database in a controlled transaction, preserving schema/migration metadata and recreating the canonical administrator and configured defaults. Do not reuse internally committing CRUD helpers as if they were part of one outer reset transaction.
6. Restore fake replies/request logs, timing controls, effective repository configuration, and scenario-local runtime registries only after old work cannot consume or rewrite them.
7. Independently verify the baseline and unchanged main-service identities, then publish the new generation and admit the next scenario.

Generation checks supplement joining; they do not excuse abandoning old workers. If quiescence or cleanup cannot be proven by the deadline, retain failed/closed state and return a phase-specific failure. The runner aborts the invocation, captures redacted evidence, and tears down its resources; it does not repair the failure by restarting and continuing.

Alternatives rejected: truncate first, rely on the controller sweeper, assume serial scenarios mean no background activity, or clear dictionaries while threads can still write.

### 4. Define resettable ownership and baseline contents explicitly

Database baseline is schema/migration metadata plus a login-capable canonical administrator with declared password, active/superuser flags, and concurrency settings. Previous user/item/chat/message fixtures disappear. Pool/request sessions must be finished before the reset transaction; rolling back one test-client session does not reset work committed by the application.

Use run-owned named workspace storage and a separately confined agent-runtime root. Override HOME and XDG data/config/cache paths for acceptance agent subprocesses only. Restore any needed trusted startup configuration from the declared baseline, never from a previous scenario. Enumerate owned orphan checkouts and `.credential-*` paths independently of chat rows, validating paths against fixed roots and refusing unsafe symlink traversal. The exact OpenCode storage paths must be verified against the installed CLI during implementation; no cleanup of arbitrary user HOME is allowed.

Controller discovery uses project/chat ownership checks for workloads, registries/build helpers, private networks, socket volumes, and chat-labeled images. Preserve long-lived control-plane services/volumes and an explicitly allowed project-shared control/egress network where needed. Final teardown must audit both Compose and `sdd.preview.project` ownership, since `compose down` alone does not enumerate dynamic preview resources.

If the independent immutable preparation-cache change is applied, its bounded complete-input-validated entries may remain within this run. Live workloads, credentials, checkout state, routing, failed-chat IDs, and Git observations may not. Fresh suite startup never inherits any of these run-local artifacts.

### 5. Configuration changes and retries must not erase a live scenario

Replace `configureDemoRepository()` environment mutation/recreation with the protected configuration control and effective-state verification. Use an acceptance-only configuration resolver or explicit override; production reads its normal environment-backed settings unchanged. The override chooses the runner's existing demo baseline or unavailable mode, not arbitrary credentials/repositories. Drain configuration-sensitive work before applying it, but do not reset DB/files for a within-scenario configuration transition. Scenario reset restores baseline mode. Update backend verification to inspect effective state and container/process identity, not pretend changed settings appear in Docker `Config.Env`.

A duplicate reset identifier can return a cached verified result only while no next-scenario work has begun. Once admission has accepted new-generation scenario work, an old identifier/generation is a conflict and cannot delete that work. Bound retained reset metadata to the current run. Success response loss is therefore safely retryable without accepting a stale acknowledgement as a clean environment.

Reset occurs at the next scenario's `Before` boundary, after previous disposal/log capture, including before the first scenario. Do not reset between fixture calls; they intentionally communicate through DB/files. On reset/identity failure, fail-fast supervision prevents any later scenario body from starting. Ordinary assertion failures still yield a failed overall result and owned teardown. Fresh browser/request contexts are recreated after verified reset.

### 6. Preserve observable failures and measure the actual trade-off

Record startup, each reset phase/total, configuration transitions, service boot/container identities and restart counters, scenario execution, lifecycle validation, reports, and final cleanup. Capture failure evidence before reset destroys it and redact credentials. Provide bounded-failure tests through isolated validation invocations, not a deliberate dirty failure inside the reusable normal suite.

Update `app-lifecycle.test.cjs` to reject unexpected replacement/unhealthy state rather than expecting automatic recreation. Add backend/controller focused tests for barriers, transactions, paths, authentication, retry generation, and partial failure, plus real acceptance checks for cross-scenario contamination and unchanged services.

Report matched normal-suite and complete-gate wall time separately, using freshly discovered inventories. Resetting every scenario can cost more than the few existing backend recreations, and moving probes is not a total-CI speedup by itself. Do not reuse the 310.12-second warm-worker result as a benchmark of this architecture.

## Risks / Trade-offs

- Late background writes after reset → complete worker/provider/controller tracking, admission barriers, generation protection, bounded join, and fail-closed abort.
- Destructive cleanup outside the test environment → mode and run authentication, validated database/storage/project ownership, no caller-selected scope, and independent unrelated-resource assertions.
- Partial cross-service cleanup → no success until every baseline is verified; retain failed state and tear down rather than pretend there is a distributed rollback.
- Persisted CLI state outside checkouts → confine acceptance subprocess HOME/XDG and verify installed CLI behavior before deleting only run-owned roots.
- Modified administrator retained as bootstrap → restore all canonical fields, not only an absent-row check.
- New profile split hides tests → fresh complete/disjoint discovery, explicit group reports, both required gates, and source-of-truth/effective parity checks.
- Reset overhead exceeds restart savings → measure reset and complete-gate cost; report negative results instead of weakening isolation.
- Existing active deltas evolve → compose all active requirements; keep cache/Git work independent and recheck compatibility before apply.

## Migration Plan

1. Finish and commit this specs-only change before any implementation-zone work. Do not modify source-of-truth specs or apply code in this proposal task.
2. Implement the reset control plane and focused tests behind acceptance-only configuration, with production behavior unchanged.
3. Add the real reset/configuration page flow and hook boundary; replace recreation assertions with effective-state and unchanged-identity checks.
4. Move lifecycle/terminal mode checks into dedicated support/profile execution and wire complete versus partial commands/reporting. The complete gate remains required while the split is introduced.
5. Run composition/lint checks, focused tests, source-of-truth regression, and the complete effective gate after code changes. Record matched timings and resource audits; sync/archive only after all effective cases pass.
6. Rollback removes the acceptance reset integration and restores the previous runner/probe execution together with its matching spec contract. No data migration is required because each invocation owns disposable fresh data. Never fall back to restarting mid-run under the new no-restart contract.

## Open Questions

- Which HOME/XDG locations does the installed OpenCode CLI actually write, and does it honor the proposed acceptance-only overrides? Verify by an isolated turn/session test; if storage cannot be confined, reset cannot claim a verified agent baseline.
- CI integration is resolved for this change: the user confirmed no CI exists. Consuming-job integration is not applicable, and local complete-gate verification does not imply deployed CI coverage. If CI is introduced later, wire the complete-gate command and verify both groups are required before claiming deployed coverage.
- Reset deadline/performance tuning requires measured worst-case drain and cleanup times. The finite deadline and fail-closed behavior are decided; tuning must not remove required work or identity/isolation checks.
