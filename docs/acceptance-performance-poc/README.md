# Acceptance test performance POCs

Last reviewed: **2026-11-06**. Python fixture batching is **implemented** in
`3ca7070` (`perf(acceptance): batch workspace fixture file writes`). Client stack
snapshots and their identity-comparison code have now been **removed** from the
acceptance harness at the user's request; the complete unchanged retry passed
**88/88 scenarios / 338 visible steps in 430.393 seconds (7m 10s)**.
The earlier Docker identity-batching POC is historical evidence, not a remaining
promotion candidate. Other ideas remain exploratory; these measurements are not
CI performance guarantees.

## Current workload

The complete command is:

```sh
npm --prefix acceptance-tests test
```

It runs **88 scenarios / 338 visible Gherkin steps**, serially, against one fresh
normal stack. Each scenario retains verified state reset and fresh contexts.
There are no assigned lifecycle/command-validation scenarios. The fixture POCs
measured revision `3833a950372a5c39c3faa3e6b0b5e59e6a57e35b`; the installed batching
change retains that exact scenario/step inventory and spec fingerprint. The
identity-batching POC measured `3ca707076e7ad46787bb855165e1aa7bbad77805`, with
file-write batching already installed.

**Earlier POCs predate removal of the test-infrastructure tests.** Their 91- and
110-scenario workloads are not controls for today's suite. In particular, the
historical 381-second lifecycle improvement involved 23 stack invocations;
today's gate has one. Do not reuse those savings, percentages or shard weights.

## Python fixture batching: measured and implemented

### Change tested

An external Node preload collected adjacent workspace-file writes within six
preview-fixture preparation methods and executed each group in one fresh Python
process. It covered instruction, Compose, routing and dependency preparation.
Nested preparations joined their outer batch; write order and overwrites were
preserved. Writes outside these methods remained immediate.

The POC changed no application, runner or spec files. Both variants used the same
measurement wrappers. There was no resident interpreter, scenario concurrency,
reset shortcut or assertion removal.

### Fresh paired rerun — 2026-11-05

A new control and treatment ran back-to-back, without reusing the earlier
control. Both complete runs passed **88/88 scenarios / 338 visible steps**, with
identical stable scenario IDs, step text and all **203 requested file writes**.
All **15 focused POC checks** passed and owned Docker cleanup was verified.

| Measurement | Control | Batched | Difference |
| --- | ---: | ---: | ---: |
| Complete gate | 587.345 s | 543.936 s | **43.409 s faster (7.4%)** |
| Python helper invocations | 276 | 137 | 139 fewer |
| Python helper elapsed total | 137.118 s | 90.158 s | 46.961 s less |
| File-write Python invocations | 203 | 64 | 139 fewer |
| Selected fixture preparations | 32 | 32 | Unchanged |
| Selected fixture-preparation time | 55.927 s | 9.600 s | **46.327 s less (82.8%)** |
| Stack startup | 19.763 s | 19.593 s | 0.170 s less |
| Stack teardown | 11.812 s | 11.688 s | 0.124 s less |

**Conclusion:** batching demonstrated an end-to-end saving of **43.4 seconds**,
with nearly identical startup times. This is a useful improvement, but not a
three-minute saving. Helper and fixture spans overlap scenario time; do not add
the component savings to the complete-gate saving.

**Measurement limits:** one accepted sequential pair, not randomized repeated
samples or a CI guarantee. Sleep prevention remained active and heartbeat checks
passed; maximum wall-clock heartbeat gaps were 1.009 s / 1.002 s. The existing
README diff was preserved and the checkout was checked unchanged. An earlier
fresh control attempt failed after 31 passing scenarios on a 30-second
preview-launch timeout; it was cleaned up, retained and excluded from timing
comparisons. The accepted pair used no timeout or assertion changes.

### Installed implementation

Commit **`3ca7070`** implements this optimization only in `acceptance-tests/`:

- `support/api-client.js`: explicit `withWorkspaceFileBatch(chatId, prepare)` and
  ordered writes in one fresh backend Python process.
- `support/pages/preview-workload-page.js`: the six write-only preparations opt
  in; nested preparation for the same client/chat joins the enclosing batch.
- `support/workspace-file-batching.test.cjs`: 19 checks for immediate standalone
  edits, ordered/Unicode/empty writes, nesting, async/client/chat isolation,
  failures, closed-batch rejection and the nine fixture variants.
- `README.md`: batch boundaries and the focused test command.

All nine fixture variants matched the original file contents and write order.
The **39 harness unit checks** passed. The installed implementation, without the
POC preload, passed the **complete 88-scenario / 338-visible-step gate in
544.316 seconds (9m 4s)**. Inventory/spec fingerprint and exact-owned cleanup
were verified. No application or OpenSpec files changed; the acceptance-only
implementation used the user's explicit no-spec exception.

The first implementation validation timed out after 19 passing scenarios on
"First Context visit starts the original checkout." The unchanged full-suite
retry passed. The timeout's cause remains unresolved; no timeouts, resets or
assertions were weakened to obtain the pass.

### Earlier paused comparison

The original control (2026-11-04) and resumed treatment (2026-11-05) measured
**610.398 → 611.652 s** for the complete gate: no end-to-end gain. Fixture
preparation fell **56.411 → 10.073 s**, but startup rose **20.742 → 85.794 s** for
an unestablished reason. Each variant passed 88/88 cases. This pair was separated
by a pause, reused its completed control, and had no sleep/heartbeat validity
checks; it remains exploratory evidence. The first treatment was cancelled,
cleaned up and excluded.

### Evidence

Reports are gitignored under `acceptance-tests/reports/`:

| Report prefix | Meaning |
| --- | --- |
| `fixture-batching-rerun-qhCR1I-control` / `fixture-batching-rerun-qhCR1I-batch` | Accepted fresh paired rerun. |
| `fixture-batching-rerun-9buaMs-control` | Failed initial control; excluded. |
| `fixture-batching-implementation-retry-20261105-153804` | Passing installed-implementation gate. |
| `fixture-batching-implementation-20261105-153240` | Failed first implementation validation; retained. |
| `fixture-batching-poc-Fn9ERa-control` / `fixture-batching-poc-Fn9ERa-batch-resume-1793889903637` | Earlier paused comparison. |
| `fixture-batching-poc-Fn9ERa-batch` | Cancelled original treatment; excluded. |
| `perf-poc-20261104-baseline` | Separate unchanged 618.659-second pass, overlapped by read-only probes; not a batching control. |

Each prefix has manifest, summary, group results/events and HTML reports.
Temporary POC sources, `comparison.json`, per-run metrics and logs are under
`/private/tmp/sdd-fixture-batching-retry.qhCR1I/` (accepted rerun),
`/private/tmp/sdd-fixture-batching-rerun.9buaMs/` (failed control), and
`/private/tmp/sdd-fixture-batching-poc.Fn9ERa/` (original comparison).
These external experiment files are not durable or installed dependencies.
Fresh trials need new directories and report prefixes; the installed code and
regression checks are in the commit above.

## Client stack snapshot removal

On **2026-11-06**, the user chose to trust the single-stack lifecycle and remove
all client shared-stack snapshots, including the initial snapshot. This is a
coverage trade-off, not an equivalent implementation of identity batching.

Removed from `acceptance-tests/`:

- Per-service Compose ID lookups and Docker identity inspection, `stackSnapshot`,
  `verifyStack`, `backendInfo`, initial identity state and backend-recreation state.
- Container/process/health/mount comparisons around resets and configuration,
  and shared-stack identity payloads in lifecycle events/child IPC.
- Obsolete reuse assertions and their step-definition file. Surviving isolated
  command-fixture assertions now verify acknowledged repository configuration.

Retained: bounded Compose/HTTP startup readiness, one-start lifecycle guards,
protected server-side reset ownership and baseline verification, strict reset
acknowledgements, fatal control/configuration boundaries, fresh scenario contexts,
and exact-owned final cleanup. Unrelated-resource sentinel comparisons still
protect teardown scope; application workspace change-detection snapshots are
untouched. No application or OpenSpec files changed; this test-only work uses
the user's explicit no-spec exception.

**Validation:** all **66 harness unit tests passed**, along with JavaScript
syntax and whitespace checks. The complete unchanged retry, without a POC
preload, passed **88/88 scenarios / 338 visible steps in 430.393 seconds
(7m 10s)**. Its independent audit verified identical stable scenario IDs, step
text and spec fingerprint against the pre-removal inventory, one stack
startup/ready/teardown, 88 successful reset generations, absence of client
identity payloads, and no remaining exact-owned containers, networks or volumes.
These lifecycle checks do not claim continuous service/process/mount identity
validation; that client coverage was deliberately removed.

The first full run (`snapshot-removal-BGvT8B`) failed after 17 passing scenarios
at "User approves a proposal": the expected apply response was not persisted.
Backend logs report `Agent command was cancelled`; the cancellation's root cause
and relation to this change are not established. The remaining 70 scenarios were
fail-fast skipped, not removed from inventory. Owned teardown passed. That
failed 120.366-second run is retained and excluded from performance samples;
no timeout, reset or application assertion was weakened before the passing retry.

The fresh **pre-removal** gate (`stack-invariant-check-kVEk27`) passed all
88 scenarios / 338 visible steps in **546.004 seconds** and verified one shared
stack with stable checked identities. The snapshot-free passing observation was
**115.611 seconds shorter (21.2%)**. This is one passing unchanged retry compared
with an earlier pre-removal run, not a repeated matched benchmark, a statistical
speedup estimate, or a CI guarantee.

Gitignored evidence under `acceptance-tests/reports/`:

- `snapshot-removal-retry-5DH5UO-*`: passing complete gate, manifest, results,
  lifecycle events, HTML reports and independent `audit.json`.
- `snapshot-removal-BGvT8B-*`: failed first validation, retained.
- `stack-invariant-check-kVEk27-*`: fresh pre-removal verification, retained.

Full logs are under `/private/tmp/sdd-snapshot-removal-retry.5DH5UO/` and
`/private/tmp/sdd-snapshot-removal-validation.BGvT8B/`; these temporary paths are
not durable dependencies.

## Docker identity batching: historical POC

**Superseded on 2026-11-06:** the user chose to remove all client stack snapshots,
including the startup baseline and reset/configuration comparisons. The following
results describe the previous harness, not the current implementation. Temporary
POC preloads are SHA-pinned to that earlier source and must not be applied to the
snapshot-free harness.

### Change tested

A temporary, SHA-pinned Node loader hook replaced only the Docker identity
collection within `stackSnapshot()` in
`acceptance-tests/features/support/app-lifecycle.js`. Both control and treatment
used identical measurement wrappers; only the treatment changed collection:

- Control: separate Compose lookup and Docker inspection for each of `backend`,
  `db` and `preview-controller` — **six Docker calls per snapshot**.
- Treatment: one fresh multi-service Compose lookup followed by one fresh
  multi-container Docker inspection — **two calls per snapshot**.
- Require exactly three distinct discovered/inspected container IDs and a
  one-to-one mapping to the expected services with exact project/service labels.
  Inspection order does not determine service order.
- Retain running/health status, full container IDs, start timestamps, restart
  counts and sorted named-volume identities. Preserve the actual HTTP health
  probe and authenticated control-state/backend boot-ID check.
- Retain every pre/post-reset and configuration verification, reset-generation
  acknowledgement, fatal boundary and owned final teardown. Standalone
  `backendInfo()` is unchanged. No IDs or inspection results are cached across
  snapshots; no scenario concurrency, timeout changes or assertion removal.

No application, checked-in harness or OpenSpec files changed during the trials.
The existing README diff was preserved byte-for-byte until measurement finished.
The user explicitly exempted this acceptance-tests-only POC from spec creation.

### Accepted fresh pairs — 2026-11-05 and 2026-11-06

Each pair used new control and treatment runs, in that order, with fresh owned
stacks on the same revision and installed file-write batching. All four runs
passed **88/88 scenarios / 338 visible steps**, with identical stable scenario
IDs, step text and spec fingerprint.

| Measurement | Nov 5 control | Nov 5 treatment | Nov 6 control | Nov 6 treatment |
| --- | ---: | ---: | ---: | ---: |
| Complete gate | 534.428 s | 459.104 s | 561.600 s | 469.517 s |
| Identity snapshots | 301 | 301 | 301 | 301 |
| Snapshot Docker calls | 1,806 | 602 | 1,806 | 602 |
| Docker identity-collection time | 119.635 s | 44.947 s | 124.289 s | 45.855 s |
| Scenario reset time | 122.328 s | 77.537 s | 128.249 s | 80.165 s |
| Stack startup | 19.778 s | 19.685 s | 19.703 s | 19.568 s |
| Stack teardown | 11.871 s | 11.840 s | 11.952 s | 11.923 s |

Complete-gate savings were **75.324 seconds (14.1%)** and
**92.083 seconds (16.4%)**. The descriptive average is
**548.014 → 464.311 seconds: 83.703 seconds saved (15.3%)**. Identity collection
itself fell by **74.687 / 78.435 seconds**. These component spans overlap scenario
and gate time; they are not additional savings to add to the end-to-end result.

The original ~42-second estimate counted only the **176 scenario-reset boundary
snapshots**. Actual complete runs had **301 snapshots**, including startup and
configuration verification, removing **1,204 Docker CLI calls per gate**.
Every accepted run retained 88 verified resets and one effective configuration
change. Maximum heartbeat gaps were approximately 1.007 seconds on Nov 5 and
1.005 seconds on Nov 6; sleep guards remained active and exact-owned cleanup
was verified.

**Measurement limits:** two accepted control→treatment pairs on one host,
separated across days. The planned control→treatment→treatment→control sequences
did not finish; do not describe these results as completed ABBA or randomized
trials, a stable median, or a CI guarantee. Failed subsequent attempts were
retained and excluded, not treated as successful repetitions.

### Regression and final validation

- **45 selected existing harness checks** passed: lifecycle, hooks, inventory,
  gate and installed workspace-file batching.
- **88 external focused POC checks** passed: identity/order/mount equivalence,
  fresh discovery, ownership/cardinality/shape/health/error rejection,
  pre/post-reset drift and fatal boundaries, acknowledgements, HTTP probes,
  standalone backend lookup and unchanged teardown, plus preservation of
  `execFile` callback/custom-promisified behavior.
- Final standalone treatment validation passed the **complete 88-scenario /
  338-visible-step gate in 478.585 seconds (7m 59s)** on Nov 6. It retained all
  301 snapshots / 602 Docker calls, passed heartbeat checks and verified owned
  cleanup. This is a green final validation, **not another paired saving**.

Three attempts were excluded:

1. Initial Nov 5 control: an instrumentation wrapper dropped `execFile`'s custom
   promisifier, breaking the runtime-image step after 14 passing scenarios.
   The corrected wrapper preserves the original descriptor and has explicit
   regression checks; the failed attempt was retained and cleaned up.
2. Nov 5 second treatment: a **1,004.807-second heartbeat gap** invalidated timing,
   and chat-specific preview cleanup timed out after 45 passing scenarios.
   The precise reason for the host/process pause is unestablished, despite an
   active sleep guard. Cleanup was verified; no timeout was weakened.
3. Nov 6 second treatment: Docker failed to bind the newly reserved backend host
   port because it was already in use. **Zero scenarios and identity snapshots
   ran**. Owned cleanup passed; the unchanged fresh final validation passed.
   Port-reservation race behavior was not changed for this POC.

### Evidence and next action

Gitignored reports are under `acceptance-tests/reports/`:

| Report prefix | Meaning |
| --- | --- |
| `identity-batching-cvuMIq-1-control` / `identity-batching-cvuMIq-2-batch` | Accepted Nov 5 pair. |
| `identity-batching-NE6Fx8-1-control` / `identity-batching-NE6Fx8-2-batch` | Accepted Nov 6 pair. |
| `identity-batching-pVKPT5-1-batch` | Passing standalone final validation. |
| `identity-batching-WzCwjD-1-control` | Initial instrumentation failure; excluded. |
| `identity-batching-cvuMIq-3-batch` | Heartbeat-gap/timeout failure; excluded. |
| `identity-batching-NE6Fx8-3-batch` | Startup port collision; excluded. |

Each prefix retains manifest, summary, scenario results, lifecycle events and
HTML reports. Corrected external sources, focused tests, metrics, logs and
`pair-1.json` files are in `/private/tmp/sdd-identity-batching-retry.cvuMIq/` and
`/private/tmp/sdd-identity-batching-rerun.NE6Fx8/`. Final validation sources and
`validation.json` are in `/private/tmp/sdd-identity-batching-validation.pVKPT5/`;
the initial failed source/evidence is retained in
`/private/tmp/sdd-identity-batching-poc.WzCwjD/`. These are temporary experiment
files, not durable installed dependencies. Reruns must copy corrected sources
into a new directory and use fresh report prefixes, never overwrite an attempt.

**Historical conclusion:** identity batching showed roughly **1¼–1½ minutes
saved** beyond installed file-write batching without removing infrastructure
assertions. It was not installed. Snapshot removal now supersedes this candidate
and intentionally removes those client-side assertions instead; the two changes
have different coverage and must not be described as equivalent optimizations.

## Next POCs for the current suite

Unless noted, profiling budgets below come from the original **88-scenario
control**, not the installed implementation run, and predate snapshot removal.
Re-profile the current harness; treat these as investigation budgets, not
additional measured savings.

### Serial execution

| Priority | Candidate | Current evidence and limits |
| --- | --- | --- |
| 1 | Phase-specific fake replies and explicit hold/release | Three detection completion steps total **55.140 s** in the original profiling control. Avoid replaying coordination delays into planner requests; replace sleeps only after observing the workspace change-detection before-snapshot. This is distinct from the removed infrastructure snapshots. Not all of this time is removable. |
| 2 | Warm fixture execution after file-write batching | The fresh batched treatment still made **137 helper calls / 90.158 s**, including real work. Measure incremental value against the snapshot-free harness with installed file-write batching; do not add historical worker savings to batching savings. |
| 3 | Consolidate preview readiness probes | Controller/workload checks repeatedly create Engine execs/interpreters. Profile bounded in-container waits while preserving actual source, socket/HTTP readiness, deadlines and failures. No current speedup measurement. |
| 4 | Startup/shutdown and archive transport tuning | Fresh control startup plus teardown was only **31.575 s**. Archive batching had a small historical slice gain. Neither supports a current multi-minute claim. |

Relevant source locations:

- Provider coordination: `acceptance-tests/step-definitions/develop.steps.js:107-143`
  and `backend/app/api/routes/testing_agent.py:51-58,240-246`. The fake API repeats
  its final reply and delay. Use explicit planner results where appropriate;
  retain real plans where startup is under test. "Turn active" does not establish
  that the before-snapshot finished. Hold/release must be bounded and safe during
  reset/cancellation; do not batch edits across that observation boundary.
- Reset controls: `acceptance-tests/features/support/app-lifecycle.js:238`.
  Client identity snapshots have been removed; reset request/acknowledgement and
  server-side baseline/ownership verification remain. The earlier profiling
  control's resets totalled 128.764 seconds, with 51.353 seconds of recorded
  server phases. Its remaining 77.411 seconds included now-removed client identity
  overhead plus request overhead; it is not a current budget or measured saving.
  These spans overlap scenario time.
- Fixture processes: `acceptance-tests/features/support/app-lifecycle.js:229`.
  A warm worker needs current isolation, deadline, database-pool, worker-death
  and reset-generation checks. A fresh fork is not a fresh interpreter.
- Preview probes/transport: `backend/app/services/preview_controller.py:622-696,928-943,1044-1074,1138-1146,1238-1284`.
  These are distinct from backend fixture helpers. Keep archive limits,
  extraction validation and sandboxing; "container running" is not readiness.

The current slow scenarios include chat-specific cleanup (**45.537 s**), rejected
build source (**26.415 s**), bounded startup failure (**25.557 s**) and the two
relevant-edit detection cases (**24.692 / 24.104 s**), including local hooks.
Profile them without removing intentional timeout, isolation or failure coverage.
API-context pooling is not a priority based on its historical sub-second cost.

**Recommended next serial work:** profile provider coordination against the
snapshot-free harness and installed file-write batching, using fresh matched
controls rather than adding prior savings. Old identity-batching preloads no
longer apply. No current serial result demonstrates a three-minute end-to-end
gain.

### If concurrency is acceptable

**Two isolated stacks are the strongest candidate for a three-minute target,
not a proven current result.** Fresh weights from the current 88-scenario control
balance into two disjoint **44-scenario** shards with **285.900 / 284.513 s** of
scenario/local-hook work. Including observed startup, teardown and residual
command overhead gives an idealized **approximately 326-second** makespan.
This is pre-batching arithmetic without resource contention, not an executed
benchmark or an incremental saving against installed batching. Recompute shard
weights from the installed baseline before the next trial. Docker currently has
**two CPUs / approximately 5.78 GiB RAM**.

A sharding POC must freshly coordinate extraction, execute every stable
scenario/step ID exactly once, retain serial scenarios and full resets within
each shard, isolate projects/ports/databases/volumes/credentials, aggregate status
and HTML, and handle cancellation/failure/owned teardown for both children.
**Never run concurrent resets against one shared stack.** The default gate
remains serial; old shard allocations and speedup percentages are not reusable.

## Historical experiments

All results below predate removal of infrastructure tests. Comparisons are
within each listed workload, not against the current 88-scenario suite. The
91-scenario source-only profile contained 352 visible steps / 534 steps including
local hooks; the 110-scenario effective gate contained 445 / 665 respectively.
Each accepted configuration was measured once, not as a statistical study.

### Complete workloads

| Date | POC | Workload | Control → treatment | Observed saving |
| --- | --- | --- | --- | ---: |
| 2026-11-02 | Two isolated processes | 91 source-only scenarios | 535.01 → 294.03 s | 240.97 s |
| 2026-11-02 | Two processes + faster lifecycle | Same 91 scenarios | 535.01 → 260.23 s | 274.77 s |
| 2026-11-02 | Rebalanced shards + faster lifecycle | Same 91 scenarios | 535.01 → 246.01 s | 289.00 s |
| 2026-11-02 | Warm imports, fresh child per fixture command | 91 scenarios; faster lifecycle in both variants | 444.72 → 361.57 s | 83.15 s |
| 2026-11-02 | Warm worker + archive batching + explicit provider coordination/replies | Same faster-lifecycle workload | 444.72 → 310.12 s | 134.60 s |
| 2026-11-03 | Faster health sampling + controller SIGINT | 110 effective scenarios; 23 stack invocations | 1651.70 → 1270.44 s | 381.27 s |

The 110-scenario lifecycle treatment reduced its dedicated group from 839.08 to
414.98 seconds; the normal group regressed from 812.50 to 855.32 seconds. Its net
gain therefore does not demonstrate a faster present-day normal suite.
Rebalancing also changed configuration-transition costs, not just load balance.
Warm imports and file-write batching attack overlapping overhead, and the combined
serial result is not the sum of its individual slice measurements.

### Smaller probes

| POC | Scope | Control → treatment | Interpretation |
| --- | --- | --- | --- |
| Immediate no-plan reply after delayed turn replies | Three detection scenarios | 89.11 → 69.58 s | Avoids an unrelated repeated delay; retains the turn's edit window. |
| Observation-ready hold/release | Same three scenarios, immediate planner replies in both | 46.09 → 16.14 s | Explicit synchronization rather than guessing shorter sleeps. |
| Bounded dependency-archive transfer batching | Two preview scenarios | 42.18 → 40.53 s | Direct transfer reduction was only 0.43 s; not a major full-suite result. |
| Faster health checks + controller SIGINT | One fresh stack cycle | 30.25 → 8.08 s | Single-cycle probe, not today's complete-gate saving. |

Other early probes included small isolated/shared-stack concurrency slices,
shortened fake responses, direct container lookup and API-context creation.
They do not establish current full-suite gains. Shared-stack concurrency is
incompatible with concurrent scenario resets; shorter sleeps do not establish
reliable observation boundaries. An old Cucumber-worker naming collision used
PID-only project names, not today's PID-plus-random naming.

Historical evidence is under `acceptance-tests/reports/` with prefixes
`performance-poc-`, `performance-poc-serial-` and `serial-poc-20261103-`.
Comparison/summary files retain inventory, timing and cleanup checks. Temporary
sources were under `/tmp/sdd-acceptance-performance-poc-20261102/`,
`/tmp/sdd-acceptance-serial-poc-20261102/` and `/tmp/sdd-serial-full-poc-20261103/`;
they are not durable or installed runner dependencies.

## Rules for the next measurement

1. Use the freshly discovered **current complete inventory**, matching stable
   scenario IDs and step text, not counts alone or historical report selections.
2. Run variants sequentially on the same clean revision with fresh owned stacks,
   consistent host conditions, sleep prevention and heartbeat-gap validation.
3. Include startup, tests/hooks, reports, teardown and child exit in the same
   command clock. Report overlapping component timings separately; do not sum
   them into an end-to-end claim.
4. Preserve cancelled/failed attempts, but exclude them from passing performance
   samples. Earlier rejected trials included host sleep, invalid overrides,
   bootstrap failures and incorrect audit assumptions; they are not speedups.
5. Require green results with no missing/pending/undefined coverage, exact-owned
   cleanup, and repeated matched runs before claiming stable medians or CI gains.

Python fixture batching is installed; client stack snapshots have been removed.
Docker identity batching is historical evidence superseded by snapshot removal;
other optimizations remain exploratory. Future application changes still require
a driving spec delta and separate spec/code tasks and commits.
