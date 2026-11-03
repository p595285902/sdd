# Acceptance suite performance POCs

The original sections below contain local slice measurements from 2026-10-30,
not full-suite benchmarks. The 2026-11-02 follow-up records a fresh full
source-of-truth regression baseline and additional experiments. No application
or checked-in runner code was changed for these experiments. Each executable
acceptance trial started fresh, project-scoped Compose resources and checked
scenario and step results.

**Latest serial full-suite POC:** warm forked Python fixtures, explicit fake
provider synchronization/phase-specific replies, and bounded archive batching
passed **91 scenarios / 534 reported steps** in **310.12 seconds**, versus a
matched **444.72-second** faster-lifecycle serial control: **134.60 seconds
saved (30.3%)**, with no scenario concurrency. The warm-fixture-only trial took
361.57 seconds (18.7% faster). See the
[new serial POCs](#2026-11-02-new-serial-pocs-no-scenario-concurrency).

**Earlier concurrent full-suite POC:** the 2026-11-02 source-of-truth regression profile
passed the same **91 scenarios / 534 reported steps** in **246.01 seconds**,
versus **535.01 seconds** serially: **54.0% less wall time (2.17x)**. This uses
two isolated processes, faster acceptance-stack lifecycle settings, and
updated timing-based shard assignments. It does not change the default runner.
See the [rebalanced full regression trial](#2026-11-02-rebalanced-full-regression-trial)
for scope, evidence, and limitations.

## Repeated backend lookup

The acceptance runner already reuses a healthy backend container when its
configuration matches. The proposed optimization was to inspect its remembered
container ID directly instead of running `docker compose ps -q backend` before
`docker inspect` on every same-configuration request.

No acceptance backend was running for this POC. Using an existing project-owned
`sdd/mailpit` container as a read-only Docker CLI latency proxy, 12 repeated
probes produced:

| Probe | Median | Minimum | Maximum | Total for 12 |
| --- | ---: | ---: | ---: | ---: |
| Compose `ps -q` plus `docker inspect` | 92.9 ms | 79.8 ms | 99.4 ms | 1109.9 ms |
| Direct `docker inspect` by ID | 21.6 ms | 19.0 ms | 30.7 ms | 265.3 ms |

The median difference is about 71 ms per call. The step definitions contain
31 call sites for `configureDemoRepository`, but that is not a measured runtime
call count. A stored Cucumber JSON report had only 55 scenarios; its 11.71-second
"the demo repository is configured" step cannot be attributed to this lookup
or treated as a current full-suite measurement. **Result:** this proxy does not
support a substantial full-suite speedup from removing the lookup.

## Parallel Cucumber workers

The same eight named scenarios were discovered by a dry run (54 steps). A
serial run passed in 59.95 seconds. Running the slice with Cucumber's built-in
`--parallel 2` failed after 31.77 seconds: both workers used the same
`sdd-acceptance-9498` Compose project name and raced to create its `db`
container. They did not run eight passing scenarios. The failed project's
containers, networks, and volumes were absent after teardown.

**Result:** `--parallel 2` cannot be used with the current project naming
scheme, which uses the process ID shared by these workers.

## Two independent runner processes

Instead of Cucumber workers, two separate Cucumber processes ran disjoint
scenario-name selections. Each process had its own PID, port, Compose project,
database, and backend. The second started after the first had extracted its
features. The timed serial and concurrent trials selected exactly the same
scenarios, and all their steps passed.

| Matched slice | Serial, one project | Concurrent, two projects | Difference |
| --- | ---: | ---: | ---: |
| 8 scenarios, 54 steps (4 per shard) | 59.95 s | 53.07 s | 6.88 s faster (11.5%) |
| 24 scenarios, 157 steps (12 per shard) | 81.90 s | 65.89 s | 16.01 s faster (19.5%) |

The 24-scenario slice was selected from the slowest scenarios in the existing
55-scenario JSON report, split alternately between shards, and verified by dry
run (24 total, 12 per shard). In its concurrent run, shard A passed 12 scenarios
and 81 steps in 65.89 seconds; shard B passed 12 scenarios and 76 steps in
61.82 seconds. Both project IDs were distinct, and neither project left
containers, networks, or volumes behind.

One earlier launcher attempt started shard B only after shard A exited; its
91.70-second total for eight passing scenarios was **not a parallel result**.
The launcher was corrected before the 53.07- and 65.89-second measurements.

**Result:** process-isolated sharding is promising on these slices, but a
full-suite improvement has not been measured. Each process still pays for
Compose startup, migrations, health checks, and teardown, and simultaneous
builds may contend for Docker resources. A real runner also needs coordinated
feature extraction, disjoint scenario selection, per-shard report paths, and
one aggregated result and HTML report before it can replace the default suite.

## Concurrent scenarios on one shared stack

The backend service is already reused within a suite run. This POC did **not**
speed up the suite by reusing the backend more. It started one fresh acceptance
Compose project, then ran two separate Cucumber processes against its existing
backend and preview controller. Each process had its own browser and ran two
different, chat-owned preview scenarios. The parent stopped the shared project
after both processes finished.

| Matched slice | Serial, one project | Concurrent, one project | Difference |
| --- | ---: | ---: | ---: |
| 4 preview scenarios, 24 steps | 125.25 s (all passed) | 87.23 s (all passed) | 38.02 s faster (30.4%) |
| Same 4 preview scenarios, three processes | 125.25 s (all passed) | 77.10 s (all passed) | 48.15 s faster (38.4%) |
| Same 4 preview scenarios, one per process | 125.25 s (all passed) | 79.84 s (all passed) | 45.41 s faster (36.3%) |

The concurrent pairs covered website/API startup, Compose dependency isolation,
unsupported build rejection, and removing one chat's preview without removing
another's. Each pair passed two scenarios and 12 steps. Both processes used the
same backend, database, and preview controller; no extra backend stack was
started. The project left no containers, networks, or volumes after teardown.
An initial launcher trial started the second pair only after the first ended:
its 128.12-second result was **not a concurrent measurement**. The corrected
trial started the second process at 20.45 seconds, after the first had loaded
its features, and finished in 87.23 seconds.

A later trial used four processes against one fresh stack, each running one of
the same preview scenarios. All four scenarios and 24 steps passed, the stack
cleaned up, and elapsed time was 79.84 seconds. That is 7.39 seconds faster
than the two-process trial, with diminishing returns as worker count grows.
Another trial used three processes, running the longest two scenarios separately
and the remaining two together. All four scenarios and 24 steps passed in
77.10 seconds. This is 2.74 seconds faster than four processes, but each worker
count was measured only once, so the small difference could be timing noise.

**Result:** independent preview scenario work can overlap on one reused backend.
This is not evidence that the whole suite is safe to parallelize: other
scenarios modify process-wide fake LLM state, repository configuration, or
shared user data. The POC bypassed each child runner's own stack lifecycle;
production use needs explicit stack ownership, isolated state, coordinated
feature extraction, and a single combined result and HTML report. The speedup
comes from concurrency, not from eliminating a repeated backend restart.

## Other probes

The normal fresh-stack startup took 19.06 seconds. Removing `--build` only
from its final backend `up --wait` (while keeping the build used for migrations)
reduced startup to 18.29 seconds: a 0.77-second difference, too small to pursue
as the main suite optimization. Ten fresh Compose exec calls importing a
backend Python module took 1.73 seconds; ten requests to one resident
interpreter took 0.032 seconds. That is a real per-call cost but does not
explain a multi-minute suite.

A separate seven-scenario Compose preview slice passed 41 steps in 135.76
seconds. Its slowest scenario, removing one chat's preview, spent 30.34 seconds
in a step that exercises multiple restarts, a failed restart, expiration, and
deletion. The controller already asks Docker for a one-second graceful stop;
this timing does not demonstrate a redundant default stop delay.

## Shorter fake agent responses

Three preview-change scenarios each configure a ten-second fake agent response,
edit the checkout while the turn is running, and assert the resulting
`preview-change` event. A matched POC shortened just those scripted responses
to two seconds in memory, without changing application or test files:

| Slice | Ten-second responses | Two-second responses |
| --- | ---: | ---: |
| 3 preview-change scenarios, 15 steps | 88.54 s (all passed) | 47.74 s (all passed) |

The observed wall-time difference was 40.80 seconds in one run per setting;
do not attribute all of that difference to the 24 seconds of configured delays
removed. Other startup and host timing varied. As a control, the scenario that
rejects a third Agent Turn at user capacity passed with both delays and took
32.01 seconds normally versus 32.19 seconds with two-second responses: it
stops its turns before their scripted delay matters. Shortening every fake
response therefore does not produce a general speedup.

**Result:** shorter waits in preview-change fixtures are promising, but their
purpose is to keep the turn active long enough for an edit. A two-second delay
passing once on this host does not establish reliability on slower CI workers.
The fake provider currently has timed delays but no explicit hold/release
barrier; one would need a separate spec and isolation checks before replacing
time-based coordination. These slices do not establish a full-suite speedup.

## 2026-11-02: fresh full regression baseline

The comparison workload is the entire source-of-truth profile, not a selection
of its slowest scenarios and not the effective profile containing active deltas:

```sh
npm --prefix acceptance-tests run test:specs -- \
  --format progress --format json:reports/performance-poc-baseline.json
```

This run passed **91 scenarios and 534 Cucumber-reported steps**. The JSON
contains 352 visible Gherkin steps and 182 per-scenario Before/After hook
entries; all passed. Cucumber also reported two passing global hooks. The
runner reported 533.680 seconds; log creation through final output took
535.007 seconds. Subsequent comparisons use approximately **535.01 seconds**
as the process-wall baseline. This is a new workload/run, not a reproduction
of the older 88-scenario, approximately 423-second results in the runner README.
Docker had two CPUs and approximately 5.78 GiB of memory available.

The baseline JSON apportioned 502.47 seconds to scenarios and their local
hooks. The slowest scenarios were:

| Scenario | Seconds |
| --- | ---: |
| A completed run does not leave a reusable stack | 61.50 |
| Removing one chat cleans up only its project | 42.16 |
| Repository configuration changes and is restored | 25.28 |
| Startup exceeds its bound | 22.38 |
| An already dirty checkout changes again | 22.27 |
| Unsupported build source is rejected | 22.11 |
| A relevant file changes | 22.10 |

The first scenario deliberately starts and tears down two additional fresh
stacks. Those lifecycle checks must remain in any matched full-suite trial;
removing them would change the workload rather than optimize it. Four backend
recreations occurred in the baseline. The baseline Compose project was
`sdd-acceptance-60540`.

Experiment code/configuration lives outside the repository in
`/tmp/sdd-acceptance-performance-poc-20261102/`; machine-readable reports live in
the ignored `acceptance-tests/reports/` directory. Only this README is changed
in the repository. No spec, application, fixture, runner, or default test
command is changed, and no default parallelization is being installed.

## 2026-11-02: two isolated processes, entire regression suite

| Workload | Process wall time | Scenarios | Reported steps | Result |
| --- | ---: | ---: | ---: | --- |
| Serial full source-of-truth profile | 535.01 s | 91 | 534 | All passed |
| Same full profile, two isolated processes | 294.03 s | 91 | 534 | All passed |

This is **240.97 seconds less wall time (45.0% faster, approximately 1.82x)**
in one matched full-suite trial. It is not a slice extrapolation.

The coordinator used the baseline scenario durations to greedily balance
longest scenarios first, then retained the original relative execution order
within each shard. Extraction ran once, before either child. Separate temporary
Cucumber configurations selected exact `feature:line` locations without
running the normal extraction-on-config-load concurrently. A dry run verified
a disjoint union of exactly the baseline scenario identities and visible
step names, keywords, and source lines before executing either shard.

| Shard | Project | Scenarios | Reported steps | Process wall time |
| --- | --- | ---: | ---: | ---: |
| 1 | `sdd-acceptance-75959` | 46 | 270 | 293.07 s |
| 2 | `sdd-acceptance-75960` | 45 | 264 | 293.93 s |

Both child processes exited zero. Every scenario step and per-scenario hook
passed, as did both global hooks in each process. The visible Gherkin step
counts were 178 + 174 = 352, matching the baseline. Each shard performed two
backend recreations, matching four in the serial run. The two nested fresh
lifecycle checks were retained. Project-scoped queries verified no Compose or
preview containers, networks, or volumes remained for either shard.

The 294.03-second measurement includes 0.106 seconds for coordinated extraction
plus the elapsed interval covering both concurrent processes, including each
process's fresh stack startup, tests, HTML/JSON reporting, and teardown. It
excludes the short dry-run preflight and manifest generation. The serial
535.01-second log-observed wall time also includes npm launch overhead. These
sub-second launcher differences do not explain the approximately 241-second
gap, but the measurements are not identical harness-overhead accounting.

Evidence under `acceptance-tests/reports/`:

- `performance-poc-baseline.json`
- `performance-poc-isolated-2-manifest.json`
- `performance-poc-isolated-2-{1,2}-dry.json`
- `performance-poc-isolated-2-{1,2}.{json,html}`
- `performance-poc-isolated-2-summary.json`

The experiment command on this machine was:

```sh
node /tmp/sdd-acceptance-performance-poc-20261102/shard-trial.cjs 2 isolated-2
```

The first launcher attempt failed during dry-run configuration loading because
this Cucumber version resolved an absolute CommonJS config path relative to
its working directory. No stack or executable scenario started in that
attempt. Passing the config path relative to the runner directory fixed it;
the table contains only the subsequent successful full-suite trial.

**Result:** process-isolated sharding now has a measured full-suite benefit on
this host. This is still a POC: one trial is not a CI reliability result, two
stacks consume more resources, and the temporary launcher does not provide a
single aggregated HTML report or production cancellation handling. A permanent
runner needs a driving spec delta and those lifecycle/reporting guarantees;
simply adding Cucumber `--parallel 2` remains incorrect.

## 2026-11-02: acceptance-stack startup and shutdown

Separate fresh lifecycle probes used the unmodified `startApplication` and
`stopApplication` exports. A temporary Docker CLI wrapper inserted additional
Compose files only after the acceptance override; it did not alter application
code, credentials, migration commands, build flags, or health-check predicates.
Every successful probe verified that its project containers, networks, and
volumes had been removed.

| Acceptance-stack settings | Startup | Teardown | Whole cycle |
| --- | ---: | ---: | ---: |
| Existing settings | 19.51 s | 10.74 s | 30.25 s |
| One-second health checks | 7.12 s | 10.84 s | 17.96 s |
| One-second checks + controller `SIGINT` | 7.17 s | 0.90 s | 8.08 s |

An earlier unchanged control reproduced the normal cost: 19.51-second startup,
10.89-second teardown, 30.41 seconds total. The successful probe project IDs
were `sdd-acceptance-82636`, `sdd-acceptance-82891`, and
`sdd-acceptance-83088`; the earlier control was `sdd-acceptance-82001`.

### Health-check cadence

The temporary override changed database and backend health-check intervals
from ten seconds to one second and retries from five to fifty, retaining the
same successful-probe predicate, per-probe timeout, and at least the nominal
50-second failure allowance. The database's 30-second start period remained
unchanged, with `start_interval: 1s` added there. The backend has no start
period, so it received no `start_interval`. Faster successful readiness is
not achieved by ignoring a failing health check or skipping migrations.
This does change sampling/retry behavior; matching the nominal allowance is
not a claim that every possible failure pattern is identical.

The first health-only probe was rejected before application startup because
Docker requires `start_period` when `start_interval` is specified. Removing
that invalid backend field fixed the temporary configuration. Its project
`sdd-acceptance-82258` was torn down and checked for leftover resources. The
table excludes that failed configuration probe.

### Controller shutdown signal

This is different from the earlier investigation of **preview workload**
stops, which already request one second. The acceptance stack's controller
itself uses a plain Python server as PID 1 and no explicit SIGTERM handler.
Docker events from the first normal probe show:

1. Controller received signal 15 (`SIGTERM`).
2. 10.017 seconds later it received signal 9 (`SIGKILL`).
3. It exited with code 137.

The temporary acceptance-only override set
`preview-controller.stop_signal: SIGINT`; no stop timeout was shortened.
The resulting complete teardown took 0.90 seconds instead of approximately
10.8 seconds. A live, exact-container-name event capture in the subsequent
full-suite trial also observed `sdd-acceptance-83247-preview-controller-1`
receive signal 2 and exit with code 130 approximately 0.145 seconds later,
without a SIGKILL in its shutdown sequence. This is measured acceptance-stack
lifecycle behavior, not a claim that a preview's own stop operation was
previously waiting ten seconds.

Evidence: `performance-poc-lifecycle-summary.json` and
`performance-poc-lifecycle-normal-events.json` under
`acceptance-tests/reports/`, plus the temporary `fast-health.yml`,
`controller-stop.yml`, and Docker wrapper in the POC directory.

**Result:** a fresh start/teardown cycle fell from 30.25 to 8.08 seconds in
these probes. That is not by itself a full-suite timing result. The full-suite
lifecycle scenarios intentionally repeat this cycle, so they must retain their
assertions when measuring these settings with the whole regression workload.

## 2026-11-02: full suite with sharding and faster lifecycle

The next full regression trial retained the exact same shard assignments and
all original step implementations, including ten-second detection-turn replies,
preview builds, intentional timeout cases, isolation checks, and nested fresh
lifecycle checks. The only additional changes were the two temporary
acceptance-stack Compose overrides described above.

| Entire 91-scenario / 534-reported-step workload | Wall time | Result |
| --- | ---: | --- |
| Serial, existing lifecycle settings | 535.01 s | All passed |
| Two isolated processes, existing settings | 294.03 s | All passed |
| Same two shards, faster health checks and controller shutdown | 260.23 s | All passed |

The combined trial saved **274.77 seconds (51.4%)** against the serial
baseline, or another **33.80 seconds (11.5%)** against sharding alone. One run
per full-suite configuration is not a guaranteed performance threshold, and
this does not isolate a serial full-suite effect of the lifecycle changes.

| Shard | Project | Scenarios | Reported steps | Process wall time |
| --- | --- | ---: | ---: | ---: |
| 1 | `sdd-acceptance-83247` | 46 | 270 | 214.78 s |
| 2 | `sdd-acceptance-83248` | 45 | 264 | 260.15 s |

Both exited zero, with every visible step and local/global hook passed. Each
shard still performed two backend recreations. Resource checks found no
remaining Compose/preview containers, networks, or volumes for either project.
Live events filtered by the **exact controller container names**, not only
inherited image labels, recorded SIGINT followed by exit code 130 for both
controllers. The faster lifecycle made the original, baseline-timed partition
uneven; its roughly 45-second gap is a reason to test rebalancing, not evidence
that a further speedup has already been achieved.

Evidence under `acceptance-tests/reports/`:

- `performance-poc-isolated-2-fast-lifecycle-manifest.json`
- `performance-poc-isolated-2-fast-lifecycle-{1,2}.{json,html}`
- `performance-poc-isolated-2-fast-lifecycle-summary.json`
- `performance-poc-exact-controller-shutdown-events.ndjson`

The local full-suite experiment used:

```sh
PATH=/tmp/sdd-acceptance-performance-poc-20261102/bin:$PATH \
POC_CONTROLLER_SIGINT=1 \
node /tmp/sdd-acceptance-performance-poc-20261102/shard-trial.cjs \
  2 isolated-2-fast-lifecycle
```

## 2026-11-02: rebalanced full regression trial

The final full-suite experiment kept the faster lifecycle settings but computed
shard weights from the preceding fast-lifecycle reports, rather than from the
slower serial baseline. It still used the original baseline as the authority
for scenario/step coverage and required all observed results to pass. No
fixture reply shortening, preview-preparation cache, build skipping, or
application-code optimization was included.

| Entire source-of-truth regression workload | Wall time | Reduction vs serial |
| --- | ---: | ---: |
| Serial baseline | 535.01 s | — |
| Two isolated processes | 294.03 s | 45.0% |
| Same two shards + faster lifecycle | 260.23 s | 51.4% |
| Two shards rebalanced for the faster lifecycle | **246.01 s** | **54.0%** |

Every row passed **91 scenarios and 534 reported steps**, representing the
same 352 visible Gherkin steps and 182 per-scenario hook entries. Each process
also passed its global hooks. The final row saved **289.00 seconds** against
the serial baseline and **14.22 seconds** against the preceding partition.

| Final shard | Project | Scenarios | Reported steps | Process wall time |
| --- | --- | ---: | ---: | ---: |
| 1 | `sdd-acceptance-89165` | 45 | 265 | 245.16 s |
| 2 | `sdd-acceptance-89166` | 46 | 269 | 245.76 s |

Both exited zero. The coordinator verified disjoint discovery and identical
visible step identities, checked every result, and found no remaining
Compose/preview containers, networks, or volumes for either project. The
reported 246.01 seconds includes coordinated extraction (0.251 seconds) and
the complete concurrent child-process interval; the short preflight remains
excluded, as in the earlier sharded measurements.

The partition change also reduced parent-backend recreations from four to
three: shard 1 recreated three times, shard 2 zero times. All configuration
transition scenarios and their assertions still executed. Therefore the
additional 14.22-second improvement is a **partitioning effect combining load
balance and setup transitions**, not an isolated measurement of balancing
alone. The original nested lifecycle checks were retained.

Evidence under `acceptance-tests/reports/`:

- `performance-poc-isolated-2-rebalanced-fast-lifecycle-manifest.json`
- `performance-poc-isolated-2-rebalanced-fast-lifecycle-{1,2}.{json,html}`
- `performance-poc-isolated-2-rebalanced-fast-lifecycle-summary.json`

The local command used the two preceding successful reports only as timing
weights; the comparison inventory still came from `performance-poc-baseline.json`:

```sh
PATH=/tmp/sdd-acceptance-performance-poc-20261102/bin:$PATH \
POC_CONTROLLER_SIGINT=1 \
POC_WEIGHTS='acceptance-tests/reports/performance-poc-isolated-2-fast-lifecycle-1.json:acceptance-tests/reports/performance-poc-isolated-2-fast-lifecycle-2.json' \
node /tmp/sdd-acceptance-performance-poc-20261102/shard-trial.cjs \
  2 isolated-2-rebalanced-fast-lifecycle
```

**Result:** a measured full-profile reduction from approximately 8m55s to
4m06s on this two-CPU Docker host. There is one run per configuration, not a
statistical or CI reliability study. The fastest row is not a measurement of
the effective profile containing active deltas, and none of these temporary
settings or partitioning rules have been installed into the default runner.

## 2026-11-02: remove a repeated fake delay, without shortening the turn

A separate matched slice tested a more conservative alternative to the older
ten-to-two-second response experiment. It retained the original **ten-second
edit window** and all Gherkin assertions, and changed only the subsequent
fake reply used to resolve startup instructions.

The fake provider repeats its last scripted reply. The detection fixture
scripts one delayed `Turn finished` reply; the two relevant-edit scenarios
subsequently request startup instructions from the provider. Repeating the
turn reply makes that unrelated lookup sleep ten more seconds before its
non-JSON text is treated as no startup plan.

Request-body auditing found an important detail: OpenCode first makes a title
generation request as well as the main agent request. The observed sequences
in **both** successful settings were:

| Scenario | Observed provider requests, in order |
| --- | --- |
| A relevant file changes | title, agent, startup plan |
| An already dirty checkout changes again | title, agent, startup plan |
| Only ignored files change | title, agent |

The temporary client wrapper therefore supplied **two unchanged ten-second
replies**, followed by immediate JSON `null`. The third reply was verified to
serve only the startup-plan request in the relevant-edit cases. `null` retains
the original no-plan result without waiting for delayed invalid text. The
ignored-only case made no plan request and left the extra reply unused; normal
scenario reset cleared it. The provider's global repeat-last behavior, main
turn output, application code, and original test steps were not changed.

| Same three detection scenarios | Whole slice | Result |
| --- | ---: | --- |
| Existing repeating delayed reply, with request audit | 89.11 s | All passed |
| Preserve title/agent delays; immediate explicit no-plan reply | 69.58 s | All passed |

The observed difference was **19.53 seconds (21.9%)** in one run per setting.
Both runs executed the same nine visible Gherkin steps. Cucumber reported 18
steps each: those nine plus six normal scenario hooks and three added audit
hooks. All 18 and both global hooks passed. The local scenario times were:

| Scenario | Control | Explicit no-plan reply |
| --- | ---: | ---: |
| A relevant file changes | 22.81 s | 12.62 s |
| An already dirty checkout changes again | 22.26 s | 12.75 s |
| Only ignored files change | 12.18 s | 12.28 s |

The unchanged ignored-only case is a useful control: the gain occurs in the
additional plan lookup, not by making the turn complete earlier. Fresh
projects `sdd-acceptance-93760` and `sdd-acceptance-94368` were checked for
remaining Compose/preview containers, networks, and volumes; none remained.
These trials used the original lifecycle settings, not the faster overrides.

The first instrumented control used an incorrect call-count assumption of
2/2/1 instead of the observed 3/3/2. All original Gherkin assertions passed,
but the three added After audit checks failed. That attempt was excluded;
the corrected experiment logged and checked the request roles and ordering
before accepting both successful measurements. It did not merely suppress
the unexpected request or remove the audit.

Evidence under `acceptance-tests/reports/`:

- `performance-poc-detection-{repeat-delay-control,immediate-plan}.{json,html}`
- `performance-poc-detection-summary.json`, including request-role evidence
- `performance-poc-detection-incorrect-call-count-audit.json`, the rejected audit

The local experiment command was:

```sh
node /tmp/sdd-acceptance-performance-poc-20261102/detection-trial.cjs
```

**Result:** avoid repeating a turn-coordination delay for a different provider
operation. This slice does **not** establish an additional full-suite speedup,
and its approximately 20-second saving must not be subtracted from the
246.01-second full-suite result. A durable fixture should identify response
purposes explicitly rather than assume this OpenCode version's exact request
count. The active Git-detection change also calls for an observation-ready
boundary; that signal was not implemented or bypassed by this POC.

## 2026-11-02: new serial POCs (no scenario concurrency)

These follow-up experiments use **one Cucumber runner, with scenarios executed
serially**. Trials also run one after another. Existing lifecycle scenarios that
start temporary fresh stacks are retained, not used to shard the workload.
All executable prototypes are outside the repository in
`/tmp/sdd-acceptance-serial-poc-20261102/`; the normal runner is unchanged.

The matched control already includes the preceding faster acceptance health
checks and controller SIGINT teardown. It is not the earlier 535.01-second
original-settings baseline, nor the 246.01-second two-runner result.

### Warm Python imports with a fresh child per fixture command

Profiling the complete serial regression found **276 Python fixture calls**,
taking **131.03 seconds** inside `runBackendPython`. Each normally starts a
Docker Compose exec and a new Python interpreter, importing the backend models
and configuration again. By contrast, creating **698 API request contexts**
took only **0.43 seconds** in total; context pooling is not a useful main target
on this measurement.

The external preload instead opens a persistent `docker exec -i` Python parent
for the verified backend container, preimports SQLModel/backend modules, and
**forks one fresh child per fixture command**. Commands remain strictly serial.
The parent never executes fixture code or opens a database session. Each child
gets a new execution namespace and disposes inherited SQLAlchemy engine pools
before executing the unchanged fixture script and arguments. Output and errors
return through a JSON-line protocol. A backend ID change starts another worker;
the worker closes before normal application teardown.

| Complete serial `specs` profile | Wall time | Python helper time | Result |
| --- | ---: | ---: | --- |
| Matched faster-lifecycle control | 444.72 s | 131.03 s | 91 scenarios / 534 reported steps passed |
| Same settings + warm forked fixture worker | 361.57 s | 46.35 s | 91 scenarios / 534 reported steps passed |

**Measured full-suite saving: 83.15 seconds (18.7%)**, without test concurrency.
Both runs made the same 276 fixture calls and recorded four backend
recreations. Their fresh discovery and executed inventories matched: 91
scenarios, 352 visible Gherkin steps, and 182 per-scenario hook entries, making
534 reported steps. Global hooks also passed. Scoped Compose/preview
containers, networks, and volumes were absent afterward.

The worker trial created two parents, processing 274 and ten requests
respectively. These 284 requests include eight isolation/error probes, leaving
276 actual fixture commands. Every request had a distinct child PID within its
worker. The probes verified that child changes to globals, environment,
`sys.path`, and a settings object did not reach the next child, and that an
expected fixture error was reported without breaking the following command.
A preceding five-scenario worker smoke test also passed (25.19 seconds).

**Limitations:** a fresh fork is not a fresh interpreter. Import-time state is
inherited, and these probes plus one full regression do not prove equivalence
for arbitrary fixture code, fork-unsafe libraries, or future import-time side
effects. Persistent database/workspace effects remain intentional fixture
behavior. A durable implementation needs explicit supported-script semantics,
request timeouts, worker-death handling, backend lifecycle ownership, and CI
repeatability checks. No stack or worker is reused across suite runs.

### Batched dependency-archive transfer

The preview controller transfers dependency inputs/outputs through Docker
Engine execs, not the host Docker CLI. This POC changes only that transport:
input chunks grow from 24 to 64 KiB, output chunks from 24 to 128 KiB, and
extraction/unlink/manifest checks share one checked exec. The bounded output
read grows from 64 to 256 KiB to accommodate the larger base64 response.
Archive limits remain 16 MiB. Non-root exec, safe extraction, downstream
path/type/count/size validation, builds, readiness checks, and sandbox settings
remain in force. There is no dependency-preparation cache or skipped build.

The matched slice contains `First Context visit starts the original checkout`
and `Unsupported build source is rejected`. Both settings passed the same two
scenarios / seven visible steps / 11 reported steps and all global hooks.

| Matched two-scenario slice | Wall time | Input/output transfer execs | Transfer time |
| --- | ---: | ---: | ---: |
| Original transport + instrumentation | 42.18 s | 17 | 1.388 s |
| Batched transport + same instrumentation | 40.53 s | 10 | 0.957 s |

Both transferred identical byte counts: 20,480 input bytes and 92,160 output
bytes. Each executed two successful calls apiece to input transfer, output
transfer, dependency preparation, and image build. Transfer Engine requests
fell from 66 to 38. The instrumentation attributes nested transfer operations
separately rather than counting them again in dependency-preparation totals.

**Result:** 1.65 seconds (3.9%) less slice wall time in one pair, with a directly
measured 0.43-second transport reduction. Dependency preparation itself varied
from 3.93 to 4.39 seconds, so the whole wall-time difference should not be
attributed to transport or extrapolated to a full-suite gain. This is a small,
lower-priority optimization, not the main serial bottleneck. Reports use
`archive-control-inline` and `archive-batched`; both scoped cleanups passed.

### Explicit provider hold/release boundary

The three detection fixtures use a ten-second fake response as an edit window.
Instead of guessing a shorter sleep, an external acceptance-only backend
bootstrap observes the **original before snapshot completing**, then holds the
main fake-agent request until the fixture has finished editing the workspace.
It releases after one real edit for the relevant/dirty cases and two for the
ignored-only case. The original after snapshot, change comparison,
`preview-change` event, and Gherkin assertions still run unmodified.

The matched control uses the same observation/auditing wrappers but does not
block the request; it retains the ten-second title/agent replies. Both settings
already supply the preceding POC's explicit immediate no-plan reply, so this
pair isolates synchronization rather than counting that earlier saving again.
The treatment uses zero-delay title/agent replies, with the main request held
at the explicit boundary instead of relying on their sleep.

| Same three detection scenarios | Whole slice | Result |
| --- | ---: | --- |
| Ten-second replies + observation-only control | 46.09 s | All passed |
| Explicit hold/release + immediate replies | 16.14 s | All passed |

**Measured slice saving: 29.94 seconds (65.0%)**. Each run passed the same three
scenarios / nine visible steps / 15 reported steps and all global hooks. No
extra Cucumber hooks were added. Audits verified a valid observed baseline,
that the turn had not completed before/during either edit, the correct edit
count, explicit release, an observed after snapshot, and exactly one blocked
main request per treatment scenario (zero in the control).

Provider purposes remained `title, agent, plan` for both relevant-change
scenarios and `title, agent` for ignored-only edits. The actual provider route
still supplies the configured response after release; the wrapper does not
substitute the change event or snapshot contents. Gate polling is bounded by
ten seconds; server-side waiting by 15 seconds. Normal fake-provider reset
clears/releases the scenario gate. Both scoped resource cleanups passed.
Reports use `gate-control` and `gate-explicit-release`.

The acceptance-only Compose command override imports the existing FastAPI app
and starts Uvicorn with one worker; it does not edit the backend image or its
default command. The controller experiment likewise imports the image's
controller and wraps/replaces only the measured transport functions.

**Limitations:** the prototype recognizes the current main-agent system prompt
and response ordering. A permanent fixture protocol should express request
purposes and the observation-ready/release boundary explicitly, rather than
freeze those prompt conventions. This is not an implementation of the active
Git observer: it instruments the existing content snapshots. The slice saving
must not be added to other experiments as a substitute for a combined full
regression, which was measured separately below.

### Combined full serial regression — passed

| Complete serial `specs` profile | Wall time | Saving versus matched control |
| --- | ---: | ---: |
| Faster-lifecycle control | 444.72 s | — |
| Same + warm forked fixture worker | 361.57 s | 83.15 s (18.7%) |
| Same + warm worker + batched archives + explicit synchronization/phase-specific replies | **310.12 s** | **134.60 s (30.3%)** |

This is a directly measured reduction from **7m25s to 5m10s**, not a sum of
slice savings. All three full runs executed the same freshly discovered
**91 scenarios / 352 visible steps / 534 reported steps**, and all steps,
scenario hooks, and global hooks passed. There was no scenario sharding or
overlapping trial execution. The combined setting also includes the earlier
explicit immediate no-plan reply; that improvement is not attributed to the
new hold/release boundary alone.

The combined run made the same 276 Python fixture calls (46.57 seconds), had
four backend recreations, and passed both workers' isolation/error probes.
Its two workers processed 274 and ten requests, each with a fresh child PID;
eight requests were the probes. All three detection fixtures passed their
snapshot/edit/release and provider-purpose audits. Controller instrumentation
recorded 46 operation events, all in batched mode. Maximum driver heartbeat lag
was 2.99 ms. All six scoped cleanup queries were empty: Compose/preview
containers, networks, and volumes. The only running container afterward was
the pre-existing `mailpit` development service.

`compare.cjs` passed cross-run scenario/visible-step inventory comparisons,
full-suite counts, fixture-call counts, worker-isolation/child-PID checks,
three gate audits per relevant run, transport-mode checks, and matched archive
operation success/call counts and transferred byte counts. It writes
`acceptance-tests/reports/performance-poc-serial-comparison.json`.

### Measurement controls and excluded attempts

Each serial trial performs fresh `specs` dry-run discovery and compares the
executed scenario/visible-step inventory against it. Historical timing reports
do not define the scenario inventory. Wall time includes Node startup,
extraction, fresh stack startup, all tests and hooks, reports, teardown, and
child exit; it excludes the preliminary dry run and post-run result checks.

The first control was excluded: the host slept for 176 and 781 seconds during
the run, which took 1483.31 seconds and had three timed-out scenarios. The
experiment did not patch application code in response. Subsequent benchmark
runs use process-scoped `caffeinate -i -s` and a driver heartbeat that rejects
runs with more than ten seconds of event-loop lag. Maximum recorded heartbeat
lag was 4.64 ms for the clean control and 3.62 ms for the full worker trial.

An initial archive-control attempt failed during BeforeAll: Docker did not
expose the `/tmp`-bound bootstrap as a file, and Python reported that it could
not find `__main__` in `/poc/controller.py`. It executed zero scenarios and is
not a performance result. Its evidence is retained under the original
`archive-control` label. The external overlays were changed to deliver the
bootstrap through an inline command rather than a host bind mount; a bounded
standalone import/boot smoke check passed before resuming the matched trials.

Evidence under `acceptance-tests/reports/` uses the prefix
`performance-poc-serial-`:

- `lifecycle-control-awake`, `warm-fixtures`, and `combined`: full JSON/HTML
  reports, `-summary.json`, and `-metrics.json`.
- `archive-control-inline`, `archive-batched`, `gate-control`, and
  `gate-explicit-release`: the matched slice reports, summaries, and metrics.
- `comparison.json` (with the same prefix): verified cross-trial results;
  controller-instrumented trials also retain raw `-controller.log` diagnostics.
- `warm-smoke`: passing five-scenario preliminary check.
- `lifecycle-control` and `archive-control`: rejected attempts, retained rather
  than substituted for successful measurements.

The local driver is `trial.cjs`; `batch.cjs` awaits each trial before starting
the next. With the temporary scripts still present, all successful settings can
be rerun sequentially with the following commands. Rerunning regenerates their
canonical reports, so preserve existing reports first if needed.

```sh
poc=/tmp/sdd-acceptance-serial-poc-20261102
node "$poc/make-overlays.cjs"
caffeinate -i -s node "$poc/batch.cjs"
node "$poc/compare.cjs"
```

The resumed batch that produced the successful remaining measurements used
`caffeinate -i -s node "$poc/batch.cjs" archive-control-inline`; it did not
repeat the already passing clean control or warm-worker full suite. Logs are
`batch.log` (initial batch) and `batch-resumed.log`. The new Docker wrapper
chains through the preceding POC's lifecycle wrapper under
`/tmp/sdd-acceptance-performance-poc-20261102/`, which must also remain present.
Neither the wrappers nor the temporary scripts are checked in, and `/tmp` is
not durable. The README documents the experiment, not an installed runner.
These results concern the source-of-truth **`specs` profile**, not the effective
profile that includes active unimplemented deltas. There is one accepted run
per setting, not a statistical or CI reliability study.

## Recommended next implementation

For the current **no-concurrency** goal:

1. Specify warm fixture execution with a fresh child per command, explicit
   isolation semantics, bounded protocol/requests, worker failure recovery,
   backend-ID lifecycle checks, and teardown on failure/cancellation. This has
   the strongest new isolated full-suite measurement.
2. Make phase-specific fake replies and observation-ready/explicit-release
   synchronization first-class acceptance fixtures. Keep the actual snapshot,
   event, isolation, and bounded-startup assertions; do not merely lower their
   timeouts or shorten an uncoordinated sleep.
3. Incorporate acceptance-only health-check cadence and prompt controller
   shutdown, preserving real readiness checks and project ownership. Consider
   proper SIGTERM handling/init as an alternative to the POC's SIGINT override.
4. Treat bounded archive batching as a smaller follow-up, retaining extraction
   and sandbox checks. Do not equate transport batching with a dependency cache
   or extrapolate its small slice difference into a major full-suite gain.
5. Repeat matched trials on CI before claiming stable medians or reliability.
   Always discover the current complete workload rather than using a historical
   timing report as the scenario inventory. API-context pooling is not a
   priority on the measured 0.43-second total creation cost.

If concurrency is wanted later, the earlier process-isolated runner experiment
is separate work: coordinated extraction, complete/disjoint discovery, fresh
per-shard stacks, bounded worker count, aggregate status/reporting, and failure
cleanup are still required. None of the new serial gains requires that runner.

Permanent runner/lifecycle changes need a driving spec delta and the project's
separate spec/code tasks and commits. This POC leaves that implementation for
a subsequent task: only this README changed in the repository, all final
executable trials passed, and no acceptance stack is kept warm between runs.
