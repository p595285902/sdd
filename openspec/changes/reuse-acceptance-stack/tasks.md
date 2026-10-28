## 1. Baseline and lifecycle boundaries

- [ ] 1.1 Record multiple cold and repeated source-of-truth full-suite timings on one host, along with suite pass/fail results and startup versus scenario time; keep a comparable scenario set for post-change measurements.
- [ ] 1.2 Add focused tests for warm project identity, exclusive crash-recoverable lock, project ownership, and an explicit acceptance-only teardown; preserve PID-scoped default/CI teardown.
- [ ] 1.3 Add and document an opt-in local runner command that retains a healthy backend, rejects concurrent use, and releases its lock on normal failure or interruption.
- [ ] 1.4 Implement and test provenance for relevant backend/frontend build inputs and acceptance configuration, including uncommitted changes; automatically rebuild/restart only the owned acceptance stack on drift.
- [ ] 1.5 Implement and test project-scoped in-place reset and verification of database/initial administrator, development workspaces, mail, and preview workloads before every warm invocation, including filtered and interrupted runs; abort with explicit recovery on failure.
- [ ] 1.6 Confirm scenario-owned fixtures do not depend on execution order and keep a fresh browser context for each scenario; update acceptance-tests/README.md for warm, fresh, and recovery commands.

## 2. Step definitions — each pending step fails for the right reason, then passes, then is committed

- [ ] 2.1 Warm lifecycle: define `Given an opt-in warm acceptance stack completed a test run` — red → green → commit.
- [ ] 2.2 Reset fixtures: define `And that run left acceptance data, a development workspace, captured mail, and a preview workload` — red → green → commit.
- [ ] 2.3 Reuse invocation: define `When the next full acceptance run starts without source or configuration changes` — red → green → commit.
- [ ] 2.4 Reuse assertion: define `Then the same backend is reused` — red → green → commit.
- [ ] 2.5 Clean-store assertion: define `And database records, development workspaces, captured mail, and preview workloads from the earlier run are absent before scenarios execute` — red → green → commit.
- [ ] 2.6 Initial-state assertion: define `And the initial acceptance administrator is available` — red → green → commit.
- [ ] 2.7 Filtered-run fixture: define `Given an opt-in warm acceptance stack completed a test run with persisted state` — red → green → commit.
- [ ] 2.8 Filtered invocation: define `When a filtered acceptance run starts on that stack` — red → green → commit.
- [ ] 2.9 Filtered reset assertion: define `Then persisted state from the earlier run is absent before its scenario executes` — red → green → commit.
- [ ] 2.10 Browser assertion: define `And the scenario receives a fresh browser context` — red → green → commit.
- [ ] 2.11 Reset-failure fixture: define `Given an opt-in warm acceptance stack has state that cannot be reset or verified` — red → green → commit.
- [ ] 2.12 Failed-start invocation: define `When an acceptance run starts on that stack` — red → green → commit.
- [ ] 2.13 Failure assertion: define `Then no scenario executes` — red → green → commit.
- [ ] 2.14 Recovery assertion: define `And the runner reports the failed reset and how to recover with a fresh acceptance stack` — red → green → commit.
- [ ] 2.15 Drift fixture: define `When backend, frontend, or acceptance configuration inputs change locally` — red → green → commit.
- [ ] 2.16 Drift invocation: define `And another acceptance run starts` — red → green → commit.
- [ ] 2.17 Refresh assertion: define `Then the acceptance stack is rebuilt and restarted with the changed inputs` — red → green → commit.
- [ ] 2.18 Refresh reset assertion: define `And its persistent state is verified clean before scenarios execute` — red → green → commit.
- [ ] 2.19 Exclusive ownership fixture: define `Given an acceptance run owns the opt-in warm stack` — red → green → commit.
- [ ] 2.20 Concurrent invocation: define `When another run tries to use the same warm stack` — red → green → commit.
- [ ] 2.21 Rejection assertion: define `Then the second run fails with a stack-in-use error` — red → green → commit.
- [ ] 2.22 Non-interference assertion: define `And the first run's state is not reset or stopped` — red → green → commit.
- [ ] 2.23 Default-run fixture: define `Given an opt-in warm acceptance stack exists` — red → green → commit.
- [ ] 2.24 Default invocation: define `When the default acceptance suite runs` — red → green → commit.
- [ ] 2.25 Isolation assertion: define `Then it starts in a separate fresh acceptance project` — red → green → commit.
- [ ] 2.26 Teardown assertion: define `And it tears down only its own project after execution` — red → green → commit.
- [ ] 2.27 Preservation assertion: define `And the opt-in warm acceptance stack remains available` — red → green → commit.

## 3. Completion

- [ ] 3.1 Extract and lint specs; dry-run effective composition to confirm no duplicate, archived, or superseded scenarios.
- [ ] 3.2 Run focused lifecycle tests, the full effective acceptance suite after every code change, and the source-of-truth regression suite; require zero pending/undefined steps and an HTML report.
- [ ] 3.3 Exercise full and filtered warm reruns, code/config drift, failed reset, interrupted run, and concurrent invocation against an owned acceptance project; verify normal development resources remain untouched.
- [ ] 3.4 Repeat the same full-suite profile used for the baseline several times; record wall times and verify median warm repeat time improves by at least 30%, every suite is green, and no new flakes appear. If not, leave the opt-in workflow disabled or revise the approach.
