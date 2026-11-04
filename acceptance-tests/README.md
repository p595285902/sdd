# Acceptance tests

This independent JavaScript project freshly extracts OpenSpec Markdown scenarios
and executes them against the real application with fake repository/provider
credentials. Docker, Node, the installed Playwright browser, and the backend
build prerequisites must be available.

```sh
npm --prefix acceptance-tests install
npx --prefix acceptance-tests playwright install chromium
```

## Complete acceptance gate

```sh
# Effective source of truth plus every active delta
npm --prefix acceptance-tests test

# Source-of-truth-only regression, excluding active deltas
npm --prefix acceptance-tests run test:specs
```

Both commands use `acceptance-gate.cjs` and freshly discover their inventory.
They run two required groups **serially**:

1. **Normal:** one fresh real Compose stack, one scenario at a time, verified
   state reset before every scenario, fresh browser/request contexts.
2. **Lifecycle/command validation:** separate real, serial invocations proving
   fresh startup, teardown, failure, cancellation, closed reset failures,
   production-mode exclusion, and complete-command discovery/reporting.

The normal runner must exit and finish owned teardown before the dedicated
runner starts. A nonzero child exit, missing/duplicate/conflicting result,
non-passed scenario, or changing specification fails the combined gate. A
normal failure prevents the dedicated group from starting and explicitly marks
its assigned cases incomplete. Both groups must pass for complete acceptance
verification. No concurrency or automatic scenario retry is enabled.

Active MODIFIED/REMOVED requirements replace/exclude the source requirement
through the existing effective composer. Exclusions are announced on stderr;
superseded, archived, and backlog scenarios do not enter the executable inventory
or inflate pending/skipped coverage. Historical reports never select scenarios.

## Partial and discovery commands

These commands are explicitly **not complete acceptance gates**:

```sh
npm --prefix acceptance-tests run test:normal
npm --prefix acceptance-tests run test:lifecycle
npm --prefix acceptance-tests run test:specs:normal
npm --prefix acceptance-tests run test:specs:lifecycle
npm --prefix acceptance-tests test -- --dry-run
npm --prefix acceptance-tests run test:specs -- --dry-run
npm --prefix acceptance-tests test -- --name '^User updates a repository through OpenCode$'
PWDEBUG=1 npm --prefix acceptance-tests run test:normal -- --name '^User updates a repository through OpenCode$'
```

Direct `cucumber-js` profiles also run only a group and print a partial-validation
notice. Use the package commands above for complete verification.

Extract/lint without running the application:

```sh
npm --prefix acceptance-tests run lint:specs
```

## Reports

Every gate execution produces reports under `acceptance-tests/reports/`:

- `cucumber-report.html`: combined status and complete/disjoint assignments.
- `cucumber-normal.html`, `cucumber-lifecycle.html`: Cucumber group reports.
- `cucumber-summary.json`: group outcomes, missing coverage, wall times.
- `cucumber-results.json`: combined Cucumber results.
- `cucumber-manifest.json`: freshly extracted inventory and fingerprint.
- `cucumber-{normal,lifecycle}-events.ndjson`: startup, reset-phase timing,
  scenario, identity, cancellation, and owned-teardown evidence.

Source-only runs use the prefix `cucumber-specs`. To retain independent evidence:

```sh
npm --prefix acceptance-tests test -- --report-prefix my-effective-run
```

A dry-run reports discovery/binding status, not passing real behavior. An
incomplete or failed run must not be used for sync/archive. Nested command
validation emits independent `fixture-*` reports without recursively executing
the repository's command-validation scenarios.

## Reset, ownership, and credentials

Each normal invocation creates a unique
`sdd-acceptance-<pid>-<random>` Compose project and an independent random reset
token. There is no cross-run persistence. Backend, database, preview-controller,
and mounted stack volumes retain their Docker identities, start timestamps,
restart counters, and mount identities throughout normal execution; backend
process boot identity is checked too. A healthy replacement still fails this
check. Disposable chat preview workloads are scenario-owned resources, not the
long-lived stack.

The backend starts with the declared demo repository available. Protected
acceptance-only overrides transition between that baseline and unavailable,
without modifying Docker environment or recreating the backend. A configuration
transition preserves existing database/workspace fixtures. The next scenario
reset restores the declared configuration.

Protected server-side controls are:

- `GET /api/v1/testing/acceptance/state`
- `POST /api/v1/testing/acceptance/reset`
- `PATCH /api/v1/testing/acceptance/configuration`

They require acceptance mode plus reset enablement, the independent Bearer run
token, and the matching `X-Acceptance-Run`. Reset additionally checks run ID,
expected generation, and a reset ID. A database-user JWT is not a reset
credential. Wrong credentials, generation, identity, or resource selectors are
rejected before destructive mutation. These controls are absent outside
acceptance mode. Tokens never belong in URLs, browser contexts, frontend
responses, committed files, or diagnostic output.

The reset closes mutation admissions, cancels **and joins** old work, drains the
preview controller, removes owned chat/orphan preview resources, cleans confined
workspace and agent storage, transactionally restores the database, restores
provider/timing/configuration controls, independently verifies the baseline and
identities, then opens the next generation. The canonical database retains
schema/migration metadata and exactly one administrator with declared credentials,
flags, and defaults. Agent HOME/XDG/TMP paths are confined beneath the owned
`/acceptance-agent-state` mount. Only ownership markers survive storage reset.
Real session validation invokes the installed OpenCode CLI to consume an owned
configuration and credential-store fixture, then verifies the trusted effective
configuration fingerprint, credential absence, and new session after reset.
Configuration/credential contents stay private; reports expose fingerprints and
booleans only. Repeated process/descendant environment and writable-descriptor
observations support confinement checks, but are not syscall-complete tracing.

The backend has no Docker socket. The preview controller attests the actual
owned Compose database, services, named mounts, networking, and run before bulk
operations. Scope is fixed; this is not an arbitrary database/path/script reset
API. Completed lost-response reset retries are safe only before new scenario
work; stale or conflicting operations reject.

The default total server reset deadline is **60 seconds**. The HTTP caller allows
15 seconds of margin; Cucumber normal steps allow 90 seconds. Dedicated failure
validation deliberately uses a one-second deadline and a bounded real PostgreSQL
lock, not a reset fault endpoint. Startup readiness probes are bounded; runner-owned Compose subprocesses have a
180-second timeout that terminates only their CLI process, followed by owned
failure cleanup. Group and child lifecycle hooks/supervisors have separate
startup/teardown deadlines. Cancellation handlers are installed before startup
and wait for in-flight creation to settle before teardown.

Real complete-command fixture subprocesses have a ten-minute execution deadline
and a three-minute cancellation-cleanup deadline. Deadline/cancellation sends
SIGTERM and joins actual exit. If cleanup cannot be proven by its deadline, the
supervisor reports failure, retains the unfinished child, and refuses another
invocation; it does not claim cleanup or silently abandon owned resources.

Dedicated cleanup validation runs three isolated variants serially: ambiguous
controller ownership rejected before deletion, descriptor exhaustion during
bounded owned filesystem cleanup, and a volume deletion refused after owned
preview workload/network deletion. Fixed local fixtures are not public fault APIs.
A complete-command fixture also verifies a fatal normal-scenario reset boundary
blocks later scenario bodies and the lifecycle group while final teardown runs.

## Failure, cancellation, and safe teardown

A reset/identity failure closes the invocation, aborts later scenario admission,
and never starts a replacement stack. Logs identify the failed phase without
credentials. Normal assertion failures also fail-fast and retain incomplete
assignment reporting. Supported SIGINT/SIGTERM cancellation initiates owned
teardown; host loss or SIGKILL cannot promise graceful cleanup.

Final teardown stops backend/controller producers first, cleans project-owned
preview resources, removes the owned Compose stack and its volumes, and audits
resource absence. A dynamic cleanup failure does not skip Compose teardown;
cleanup errors still fail validation even when a final audit finds no resources.
Do not touch a development stack, pre-existing mailpit, or unrelated resources.

For inspection, substitute the exact project emitted in the run's events:

```sh
docker compose --project-name <exact-run-project> \
  --file compose.yml --file acceptance-tests/compose.yml ps --all
```

Never run an unscoped `docker compose down`, broad Docker prune, or label-wildcard
cleanup. Run-owned preview resources carry `sdd.preview.project=<exact-run-project>`;
Compose resources carry `com.docker.compose.project=<exact-run-project>`.

Rollback is a separate code-zone change: inspect and revert only this
implementation's code commit(s), restoring runner/backend/controller/Compose
behavior together. Do not mix a code rollback with OpenSpec edits, discard user
changes, or restore a replacement-stack fallback into this design. Spec
sync/archive needs a green complete effective gate and separate authorization.

## Focused regression checks

Focused checks support diagnosis but do not replace either complete gate:

```sh
node --test \
  acceptance-tests/features/support/app-lifecycle.test.cjs \
  acceptance-tests/features/support/hooks.test.cjs \
  acceptance-tests/support/pages/acceptance-lifecycle-page.test.cjs \
  acceptance-tests/support/bounded-command.test.cjs \
  acceptance-tests/acceptance-gate.test.cjs \
  acceptance-tests/support/acceptance-inventory.test.cjs

uv run --directory backend --no-sync pytest --confcutdir=tests/services \
  tests/services/test_acceptance_reset.py \
  tests/services/test_develop_agent.py \
  tests/services/test_develop_workspace.py \
  tests/services/test_develop_turns.py \
  tests/services/test_preview_controller_reset.py -q
```

## CI integration status

The complete command for an acceptance-consuming CI job is
`npm --prefix acceptance-tests test`, not `test:normal` or a direct Cucumber
profile. The job must preserve that command's nonzero exit and retain combined
and both group HTML/JSON/event reports, including failure reports.

No actual acceptance-consuming CI job has been located in this checkout during
this implementation. Deployed CI coverage is **not verified**. Documentation and
local gate behavior alone do not complete the consuming-job integration
requirement; that job must be located, updated, and observed running both groups.

## Historical timing evidence

The following measurements predate the no-restart state-reset implementation.
They are retained as historical evidence, not current performance claims.
Backend recreations exclude initial startup.

| Version | Run | Scenarios | Steps | Result | Backend recreations | Wall time (s) |
| --- | ---: | ---: | ---: | --- | ---: | ---: |
| Before reuse | 1 | 88 | 514 | Passed | 62 | 1111.78 |
| Before reuse | 2 | 88 | 514 | Passed | 62 | 1113.66 |
| After reuse | 1 | 88 | 514 | Passed | 2 | 422.61 |
| After reuse | 2 | 88 | 514 | Passed | 2 | 423.26 |

Those matched runs reduced the observed median from 1112.72 to 422.94 seconds.
A separate earlier effective run passed 91 scenarios/534 steps in 496.90 seconds
with four backend recreations and is not an equal-inventory comparison.

## State-reset candidate measurements

The following single-sample observations were collected on 2026-11-03 **before
the final task-audit fixes**. They are not final-tree completion evidence or a
speedup claim. Frozen-control and source-treatment inventories were freshly
compared by full stable scenario IDs, including step text, not counts alone.

| Matched inventory | Clock | Frozen control (s) | Reset candidate (s) | Observed change |
| --- | --- | ---: | ---: | ---: |
| 90 source normal scenarios | Cucumber elapsed | 486.325 | 674.301 | +38.65% |
| 91 complete source scenarios | Invocation wall | 565.563 | 750.273 | +32.66% |

The normal control passed all 90 scenarios; its original post-run report audit
failed because relative report URIs were resolved against the wrong checkout.
An independent corrected audit verified all assignments and results. Its wrapper
wall duration was not saved, so the normal comparison uses **only Cucumber's
clock on both sides**, not a reconstructed wrapper duration.

The separate expanded effective gate passed 110 scenarios in 1541.923 seconds:
102 normal in 824.238 seconds and 8 lifecycle/command validations in 717.556
seconds. This is not an equal-inventory comparison with the 91-scenario control.
Deliberately failing nested fixtures are successful outer failure-propagation
checks, not green nested invocations.

For that effective run, normal startup was 20.255 seconds, teardown 11.748
seconds, and admitted scenario-body/After spans totalled 595.349 seconds.
The 112 recorded helper resets totalled 210.601 seconds (median 1.835, maximum
8.708). Recorded server phase totals were: ownership 2.066 seconds, quiescence
8.390, previews 24.173, files 0.161, database 7.455, controls 0.001, and verification
19.406. Seven configuration transitions occurred; that older event format did
not measure their duration separately. Current configuration events include
`milliseconds` for future measurements.

Scenario spans include internal reset/configuration work, and server phase
spans overlap client reset spans: **do not sum these as disjoint costs**. Reports
`reset-effective-latest-*` and `reset-source-latest-*` under `reports/` retain
these candidate observations locally; reports are gitignored. Final verification
uses new report prefixes rather than overwriting this evidence. Expanded coverage,
failed/incomplete runs, and prior warm-import POCs are not evidence of a speedup
from this architecture.

## Latest effective verification

After the task-audit fixes, `reset-final-effective-*` records a complete real
**110/110 scenario pass**, zero pending/undefined results, and both group HTML
reports. Normal validation passed 102 scenarios in 829.146 seconds; separate
lifecycle/command validation passed 8 in 868.752 seconds. Complete invocation
wall time was **1697.989 seconds**. The independent `reset-final-effective-audit.json`
verified serial normal boundaries, one healthy unchanged normal stack with zero
restarts, and no remaining exact-owned labeled resources across 20 invocation
projects, including failed/cancelled children and nested command fixtures.
This does not claim absence of unidentified historical anonymous volumes.

Measured normal costs: startup 19.440 seconds, teardown 12.371, scenario-body/After
spans 599.176, 112 helper reset calls 214.284 (median 1.868, maximum 8.863), and
7 configuration transitions 4.388. Server phase totals were: ownership 2.248
seconds, quiescence 8.230, previews 24.887, files 0.112, database 7.136, controls
0.001, and verification 19.188. These nested spans overlap and must not be added
as disjoint costs. Expanded effective validation is not an equal-inventory
performance comparison with the frozen source-only control.

Focused verification passed 174 backend/controller and 42 JavaScript tests.
Reset-module type checks and changed-file Ruff passed. Full-app type checking
still reports 57 diagnostics verified present in the frozen baseline; the 67
introduced diagnostics were fixed without suppressions. Whole-app Ruff also
retains two pre-existing missing-newline errors in unchanged files. This is not
a claim that the entire project's static-check suite is green.

The final source-only regression uses the separate `reset-final-source-*` prefix;
inspect its combined summary for completion rather than treating the earlier
source measurement or targeted four-scenario pass as final regression evidence.
Actual consuming-CI integration remains unverified as described above.
