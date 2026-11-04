## 2. Step definitions — one task per pending step; each = fails for the right reason → implement → passes → commit

The JavaScript acceptance project already exists; no first-time scaffolding is needed. The planning dry run discovered 22 change scenarios and 93 distinct undefined step texts. Re-discover before applying; reuse the existing bindings for unchanged step texts rather than adding ambiguous definitions.

Each checkbox includes the real implementation and focused tests needed by that step, not just its binding. Keep steps intent-level; put requests, resource inspection, fixtures, and process supervision in page/API helpers. Proposed new flow files are `acceptance-tests/support/pages/acceptance-reset-page.js`, `acceptance-lifecycle-page.js`, and `acceptance-gate-page.js`, with normal and dedicated-validation step/support imports. The existing `features/support/world.js` remains thin.

Backend work belongs in the existing testing-route registration, `backend/app/core/config.py`, and a proposed `backend/app/services/acceptance_reset.py`, with admission/completion integration in `develop_turns.py`, `develop_agent.py`, `develop_workspace.py`, and the Develop routes. Controller work belongs in `backend/app/services/preview_controller.py`; the backend calls through `develop_preview_runtime.py`, never through a Docker socket. Supply fixed run identity, independent high-entropy credentials, and confined storage through `acceptance-tests/compose.yml` and `features/support/app-lifecycle.js`.

Normal steps must not start nested acceptance stacks. Dedicated validation uses separate World/support imports without the normal `BeforeAll` stack hook. Terminal fault injection is bounded and confined to owned isolated test invocations, not exposed as an arbitrary-script API. Command-validation fixture inventories must not include their own command-validation cases recursively.

For each step: demonstrate the relevant failure, implement its supporting behavior, verify the step, and run the acceptance suite after every code change. The project-wide green-suite rule takes precedence over committing an incrementally passing step: do not commit or consider code complete while the complete effective gate is red or pending. Commit specs separately with authorization before entering the code zone; do not edit specs during implementation except task checkboxes. Other active changes remain in effective discovery and must not be silently filtered to manufacture green results.

### Protected controls and ownership

- [x] 2.1 Implement `separate lifecycle validation has started the application without acceptance reset mode` — add the dedicated lifecycle World/profile and real owned startup helper; capture backend/controller registration and resource baselines without the normal main stack.
- [x] 2.2 Implement `a client requests acceptance reset or configuration controls` — add ResetPage requests for reset, state, and configuration, plus the unpublished controller control; keep credentials out of URLs and browser contexts.
- [x] 2.3 Implement `those controls are unavailable` — mode-gate registration in backend and controller; verify each control is absent outside acceptance mode with focused route tests.
- [x] 2.4 Implement `application data and resources remain unchanged` — compare real data/files/resource snapshots after rejected non-acceptance requests and clean up only the validation invocation.
- [x] 2.5 Implement `an acceptance stack contains scenario data and workspace files` — seed observable real fixtures through existing API/fixture helpers and record the server-validated run scope.
- [x] 2.6 Implement `reset is requested without the current run's valid reset credential` — exercise missing and incorrect run credentials, independent of database-user authentication.
- [x] 2.7 Implement `reset is rejected before any data or resource is changed` — authenticate before admission/state mutation and verify rejection leaves database, files, provider state, and resources intact.
- [x] 2.8 Implement `the stack remains usable with its existing state` — perform real application reads/operations after rejection and verify unchanged service identities.
- [x] 2.9 Implement `an acceptance stack and unrelated project resources contain distinct state` — create explicitly labeled unrelated sentinel resources in the flow and record both ownership scopes; never touch pre-existing development resources.
- [x] 2.10 Implement `an authenticated reset request supplies a different run identity or resource scope` — send wrong-run and prohibited database/path/project selectors; validate actual owned startup configuration rather than trusting caller scope.
- [x] 2.11 Implement `the request is rejected before mutation` — cover backend/controller ownership and request-schema rejection before cleanup or admission changes.
- [x] 2.12 Implement `both sets of resources remain unchanged` — assert both scope snapshots are intact and dispose only the test's sentinel resources.

### Quiescence and admission barrier

- [x] 2.13 Implement `a scenario has an active Agent Turn and scenario-owned preview or workspace setup work` — create real generation-owned work with explicit bounded synchronization, including delayed provider/completion or preparation work, not sleeps as proof of activity.
- [x] 2.14 Implement `authenticated scenario reset is requested` — add the protected coordinator request with run/reset identifiers and expected generation, serialized phase transitions, finite total deadline, and client/hook timeout margin.
- [x] 2.15 Implement `admissions close and the prior work is stopped and joined before state is removed` — track cancellation and actual completion through encompassing finally blocks for turns, provider calls, streamed completion, setup, preview preparation/launch, and controller maintenance; assert cleanup ordering.
- [x] 2.16 Implement `no prior operation recreates data or consumes replies after reset completes` — add generation checks and bounded late-write/reply/resource probes; verify registry clearing or agent-process exit alone cannot satisfy the drain barrier.
- [x] 2.17 Implement `the next scenario can start a new turn with baseline capacity` — restore admission counts/timers/subscribers only after drain, then exercise a real new turn with canonical user concurrency.
- [x] 2.18 Implement `authenticated scenario reset is in progress` — hold a known reset phase through bounded test synchronization and inspect authenticated status while health remains available.
- [x] 2.19 Implement `another request attempts to start a turn, set up a workspace, or launch a preview` — issue each mutating request through real application routes while admissions are closed.
- [x] 2.20 Implement `that request is rejected until the reset boundary completes` — guard all relevant mutating entry points, including conflicting reset/configuration requests; test reopen only after verification.
- [x] 2.21 Implement `it does not create partially reset scenario state` — inspect real database, workspace, provider, and preview state after rejected attempts and add focused admission-race tests.

### Canonical database baseline

- [x] 2.22 Implement `a scenario has created users, items, chats, and messages` — seed representative committed records and record schema/migration metadata before reset.
- [x] 2.23 Implement `has changed the bootstrap administrator's credentials or privileges` — exercise modified credentials, active/superuser flags, concurrency settings, and deleted-admin variants without making reset depend on that user.
- [x] 2.24 Implement `authenticated scenario reset completes` — coordinate controller cleanup, confined file cleanup, owned database restoration, provider/configuration reset, and independent verification before acknowledging success.
- [x] 2.25 Implement `only the declared database baseline remains` — drain pooled/request database work, remove all mutable application records in a controlled reset transaction, and avoid internally committing CRUD helpers in that transaction; add rollback/failure tests.
- [x] 2.26 Implement `the bootstrap administrator can authenticate with the baseline permissions and concurrency settings` — restore every canonical administrator field and verify real login/privileged operations and turn capacity.
- [x] 2.27 Implement `the database schema and migration version remain unchanged` — compare schema/version observations and prove reset does not drop schema or mounted database storage.

### Confined workspace and agent storage

- [x] 2.28 Implement `a scenario has left a checkout without a database chat row` — create a real owned orphan checkout and demonstrate discovery is independent of surviving chat rows.
- [x] 2.29 Implement `has persisted agent-session data and temporary credential files in acceptance-owned storage` — verify the installed OpenCode CLI's HOME/XDG writes using an isolated real turn, confine acceptance subprocess storage, and seed owned session/credential fixtures.
- [x] 2.30 Implement `those files and session data are absent` — remove owned checkouts, fixture outputs, credential-temp paths, and agent state after consumers stop; add fixed-root, symlink, unrelated-directory, and orphan-discovery tests.
- [x] 2.31 Implement `mounted workspace storage remains available on the same stack` — preserve volume/root identities and permissions and create a new workspace on the unchanged storage.
- [x] 2.32 Implement `the next scenario does not inherit the previous agent session or credentials` — execute a new real agent session and verify fresh identifiers/trusted baseline configuration with no prior credentials or CLI state.

### Controller-owned preview cleanup

- [x] 2.33 Implement `a scenario has left preview resources outside its page helper's tracked list` — create owned workload/helper/network/socket-volume/image orphans independently of page tracking and database rows.
- [x] 2.34 Implement `an unrelated project has its own preview resources` — create and record separate labeled preview sentinels through the lifecycle/resource flow.
- [x] 2.35 Implement `every scenario-owned preview resource and routing entry is removed` — add authenticated internal controller drain/reset, enumerate project/chat-owned resource families, and clear routing/failure/activity maps only after handlers and maintenance join.
- [x] 2.36 Implement `unrelated preview resources remain unchanged` — verify ownership filters and explicitly preserved long-lived/shared control resources with focused controller tests and real sentinel inspection.
- [x] 2.37 Implement `the same backend, database, and preview-controller services remain running` — compare service/container/process boot identities, health, restart counters, and mounted volumes; retain Docker ownership solely in the controller.

### Verified baseline, context isolation, and retries

- [x] 2.38 Implement `a scenario has modified database records, workspace files, fake-provider state, and acceptance configuration` — seed cross-domain contamination including replies/request logs/timing overrides and non-baseline repository mode.
- [x] 2.39 Implement `authenticated scenario reset reports verified completion` — independently verify every declared baseline after old work drains, return redacted phase/status evidence, and refuse success on partial cleanup or verification failure.
- [x] 2.40 Implement `the reset acknowledgement identifies the current run and its new baseline generation` — validate run/reset/generation values and prevent a stale acknowledgement from being treated as a clean new boundary.
- [x] 2.41 Implement `the next scenario sees only the declared baseline through real application operations` — verify canonical data, empty owned workspace/preview/agent state, reset provider defaults, and baseline effective configuration through real operations.
- [x] 2.42 Implement `it uses a fresh browser and request context on the unchanged stack` — update hooks, ApiClient, and World disposal so log capture/disposal precede reset, reset includes the first scenario, and new contexts open only after verified completion.
- [x] 2.43 Implement `reset has completed but its acknowledgement was lost before new scenario work started` — retain bounded verified reset metadata and simulate response loss in the client without undoing the real completed reset.
- [x] 2.44 Implement `the same authenticated reset identifier is retried` — retry the identical run/reset/generation request through ResetPage.
- [x] 2.45 Implement `the verified completion is returned without conflicting cleanup or additional baseline records` — safely reuse the verified result only before new-generation activity; add duplicate/conflicting request and transaction tests.
- [x] 2.46 Implement `the stack services and mounted volumes remain unchanged` — audit unchanged identities and restart counters across retry, not just equal container names.
- [x] 2.47 Implement `a verified reset has completed and the next scenario has created new state` — record accepted new-generation work and persist real new scenario fixtures.
- [x] 2.48 Implement `the previous reset identifier is retried` — send the old identifier/expected generation after that new work starts.
- [x] 2.49 Implement `the stale request is rejected` — reject stale or conflicting reset/configuration requests before changing current admission/data state.
- [x] 2.50 Implement `the new scenario's data and work remain unchanged` — verify new fixtures and active work survive the stale retry, with focused generation/race tests.

### Terminal reset-failure validation

- [x] 2.51 Implement `separate lifecycle validation runs an isolated acceptance invocation with work that cannot quiesce within its reset deadline` — add owned, bounded drain-failure fixtures in the dedicated profile without starting a normal-suite background stack.
- [x] 2.52 Implement `that invocation requests scenario reset` — supervise the real child runner/reset request and collect redacted phase, exit, scenario-start, and identity evidence.
- [x] 2.53 Implement `reset reports failure and no later scenario starts` — keep failed admissions closed and add fatal reset supervision that prevents subsequent scenario bodies.
- [x] 2.54 Implement `the invocation fails without restarting or replacing its stack services` — remove restart recovery for reset/identity/health failure and update `app-lifecycle.test.cjs` from recreation expectations to abort semantics.
- [x] 2.55 Implement `final teardown removes its owned resources without changing unrelated projects` — audit both Compose and preview ownership families after failure; preserve unrelated sentinels and never use unscoped Docker cleanup.
- [x] 2.56 Implement `separate lifecycle validation runs an isolated acceptance invocation whose workspace or preview cleanup cannot complete` — exercise bounded filesystem/controller partial-failure variants within dedicated owned invocations.
- [x] 2.57 Implement `the failed cleanup phase is reported without a successful baseline acknowledgement` — test phase-specific failures and secret redaction while no successful generation/baseline is published.
- [x] 2.58 Implement `the invocation fails and tears down rather than continuing on contaminated state` — verify nonzero status, closed admissions, no later body, no replacement stack, and final cleanup after each partial-failure variant.

### Single-stack reuse and configuration transitions

- [x] 2.59 Implement `a normal acceptance scenario suite has recorded its stack service and volume identities` — record the single owned startup's service boot/container/volume identities and restart counters in the normal-run flow.
- [x] 2.60 Implement `successive scenarios complete with a verified reset between them` — exercise serial real scenario boundaries with disposal then protected reset; do not reset between fixture commands within one scenario.
- [x] 2.61 Implement `all scenarios use the same healthy stack services and mounted volumes without restarts` — verify identities and effective health at every boundary and fail the invocation on mismatch instead of recreating services.
- [x] 2.62 Implement `no additional acceptance stack is started inside the normal suite` — audit project/startup events and move existing lifecycle probes out of `acceptance-stack-reuse.steps.js` into the dedicated lifecycle flow.
- [x] 2.63 Implement `the scenarios execute without overlapping one another` — enforce serial runner/group execution and assert bounded scenario-start/end/reset event ordering.
- [x] 2.64 Implement `neither configuration transition restarts a stack service` — replace `configureDemoRepository()` environment mutation/force recreation with the protected mode API and effective-state verification; update existing configured/unconfigured step bindings and lifecycle unit assertions.
- [x] 2.65 Implement `a scenario has database and workspace fixtures in the shared stack` — seed fixtures before configuration changes and preserve their identifiers/content for comparison.
- [x] 2.66 Implement `that scenario changes the effective demo-repository configuration and restores it` — support only declared baseline/unavailable modes, drain config-sensitive work, and keep production environment resolution unchanged.
- [x] 2.67 Implement `its existing fixtures remain available throughout those configuration changes` — verify transitions do not run the database/workspace reset and add resolver/configuration-focused tests.
- [x] 2.68 Implement `the scenario finishes with the demo repository unavailable` — leave the effective acceptance override non-baseline without changing Docker environment or recreating the backend.
- [x] 2.69 Implement `scenario state is reset` — reuse the protected ResetPage boundary and restore provider/timing/effective repository controls only after quiescence.
- [x] 2.70 Implement `the next scenario observes the declared demo-repository baseline on the same backend` — verify real setup/configuration behavior and unchanged boot/container identity rather than inspecting stale `Config.Env` values.

### Separate fresh-run, failure, and cancellation coverage

- [x] 2.71 Implement `dedicated acceptance lifecycle validation runs separately from the normal scenario suite` — classify stable requirement/scenario identities and select dedicated support imports; require normal teardown before validation starts.
- [x] 2.72 Implement `it completes two fresh acceptance lifecycle invocations serially` — move existing real probe helpers into LifecyclePage and execute two bounded owned starts/stops without the normal `BeforeAll` hook.
- [x] 2.73 Implement `those invocations use distinct project-scoped stacks` — compare run/project and service identities and prove no cross-invocation reuse.
- [x] 2.74 Implement `each completed invocation leaves no owned containers, networks, or volumes` — verify Compose and dynamic preview cleanup, including owned orphan resources; do not equate cached images with leaked mounted stack resources.
- [x] 2.75 Implement `neither invocation modifies unrelated project resources` — compare unrelated sentinels before/after each serial lifecycle probe.
- [x] 2.76 Implement `dedicated lifecycle validation has started an isolated acceptance invocation` — reuse the owned child lifecycle supervisor with real startup and bounded cleanup in finally.
- [x] 2.77 Implement `unrelated project resources exist` — create explicit validation-owned sentinel fixtures rather than modifying or relying on the user's development stack.
- [x] 2.78 Implement `that acceptance invocation fails during execution` — inject a controlled child assertion failure and preserve exit/log evidence before teardown.
- [x] 2.79 Implement `the failed invocation removes its owned stack and preview resources` — verify actual owned-resource absence after the failing runner exits.
- [x] 2.80 Implement `unrelated project resources remain unchanged` — verify sentinels survive failed and cancelled child cleanup, then dispose only those fixtures.
- [x] 2.81 Implement `that invocation receives a supported cancellation signal` — supervise supported process cancellation with finite deadlines and finally-based owned teardown.
- [x] 2.82 Implement `it reports cancellation and removes its owned stack and preview resources` — assert cancellation outcome and both resource-label audits without claiming cleanup after host loss or uncatchable termination.
- [x] 2.83 Implement `it does not start a replacement stack` — verify startup/identity event histories contain no restart/recovery invocation after cancellation.

### Complete-gate discovery and reporting

- [x] 2.84 Implement `separate command validation has freshly composed an isolated effective-spec inventory containing normal and lifecycle scenarios` — add GatePage fixture inventories using the same extractor/composer and bounded real runners; exclude recursive command-validation cases by fixture construction, never by skipping repository scenarios.
- [x] 2.85 Implement `the complete acceptance command executes that test inventory` — add the serial complete-gate entry point and package commands for complete effective, complete source-only, and explicitly partial normal/lifecycle runs.
- [x] 2.86 Implement `every test-inventory scenario is assigned to and executed in exactly one reported group` — classify fresh stable identities, reject duplicate/incomplete discovery, and audit the outer repository invocation independently after both groups finish.
- [x] 2.87 Implement `the normal suite finishes and tears down before separate lifecycle validation starts` — verify real fixture-run start/stop ordering and no normal stack remains when dedicated validation begins.
- [x] 2.88 Implement `the combined status fails if either group fails` — exercise normal failure, lifecycle failure, and fatal abort fixtures; report assigned-but-unexecuted cases as failed/incomplete rather than false complete green.
- [x] 2.89 Implement `the HTML reporting identifies both groups without silently skipped coverage` — preserve composition exclusions and produce group assignments/results plus combined HTML/status, labeling standalone targets partial.
- [x] 2.90 Implement `separate command validation has added an effective scenario to its isolated test inventory since the previous report` — extend a fresh fixture inventory while retaining an older report, including source-only/effective and active-delta replacement fixtures.
- [x] 2.91 Implement `the complete acceptance command freshly discovers that test inventory's validation groups` — refresh extraction and classification on every invocation, retaining existing archived/superseded exclusions.
- [x] 2.92 Implement `the new scenario appears exactly once in the appropriate group` — verify fresh inventory completeness and correct group assignment with no duplicate or silently omitted cases.
- [x] 2.93 Implement `historical reports do not determine the scenario inventory` — prove stale or missing reports cannot remove newly discovered cases; timings may be observations, not inventory authority.

## 3. Completion

- [x] 3.1 Run the full complete effective suite: every effective scenario in both groups passes, zero pending/undefined steps, HTML reports and combined assignments/status generated; all active changes remain composed.
- [x] 3.2 Run focused backend/controller and JavaScript lifecycle/discovery tests covering authentication, owned scope, true drain, transaction recovery, confined paths, reset generation/retries, no-restart failures, reporting, and production-mode/configuration non-regression.
- [x] 3.3 Run the complete source-of-truth-only regression with both groups; verify no active delta executes and existing fresh-run coverage is preserved before sync.
- [x] 3.4 Re-run extraction/lint and dry-run composition/group audits: no archived/superseded cases loaded, complete/disjoint identities, no duplicate or historical-inventory omission, and explicit partial-target labeling.
- [x] 3.5 Audit healthy normal-run service/container/boot/volume identities and zero restart/recreation events; verify cross-scenario baseline isolation and final absence of owned Compose/preview containers, networks, and volumes after success, failure, and controlled cancellation.
- [x] 3.6 Record matched serial normal-suite and complete-gate timings separately, with startup/reset phases/configuration/scenario/lifecycle/teardown costs and equal fresh inventories; report regressions honestly without attributing earlier warm-import POC gains to this design.
- [x] 3.7 Document complete versus partial commands, report locations, ownership/authentication, finite deadlines, safe failure behavior, and rollback in `acceptance-tests/README.md`. The user confirmed on 2026-11-04 that no CI exists; consuming-job integration is not applicable to this change and no deployed CI coverage is claimed. If CI is introduced later, its acceptance job must use the complete-gate command and verify both groups are required.
- [x] 3.8 Verify the installed OpenCode HOME/XDG confinement and trusted baseline restoration are proven by real session tests; do not declare agent-state reset complete if any writable storage escapes the owned roots.
- [x] 3.9 Recheck compatibility with the independent preview-input-reuse and Git-observation changes, preserving only permitted complete-input-verified immutable run-local preparation and never stale mutable observations, chat state, or credentials; sync/archive only after the full effective gate is green and a separate request authorizes it.
