# Acceptance tests

The acceptance suite is an independent JavaScript project that extracts the
OpenSpec Markdown scenarios and runs them against an isolated application stack.

```sh
npm --prefix acceptance-tests install
```

Run the effective source-of-truth plus active-delta suite and generate
`acceptance-tests/reports/cucumber-report.html`:

```sh
npm --prefix acceptance-tests test
```

Run only the source-of-truth regression profile, excluding active deltas:

```sh
npm --prefix acceptance-tests run test:specs
```

Extract and lint every spec:

```sh
npm --prefix acceptance-tests run lint:specs
```

Inspect effective scenario discovery without executing steps:

```sh
cd acceptance-tests && npx cucumber-js --dry-run
```

Each run uses a unique `sdd-acceptance-<pid>` Compose project and removes only
that project's containers, network, and volumes during teardown.
The test stack uses fixed fake provider and repository credentials rather than
credentials from the host environment.
The backend starts with the demo repository configured. Within a run, a request
for the already-active configuration reuses the healthy backend; a request for
the other configuration recreates the backend and waits for health. The runner
checks the container identity, environment, and health before reusing it, and
resets acceptance-only fake LLM replies, recorded requests, and turn settings
before each scenario. Each scenario still opens a fresh browser context and
cleans up its own preview workloads.

Both `npm test` and `npm run test:specs`, including their CI invocations, start
a fresh project and tear it down after the suite, even on a failed scenario.
No acceptance stack is kept warm between invocations. If a configuration or
health check fails, inspect the explicit error and the backend logs printed on
scenario failure. Check `docker compose --project-name sdd-acceptance-<pid>
--file compose.yml --file acceptance-tests/compose.yml ps` for the affected
run; do not use `docker compose down` without the acceptance project name,
because that could affect a development stack.

Run the focused lifecycle checks with
`node --test acceptance-tests/features/support/app-lifecycle.test.cjs` and
`cd backend && uv run --no-sync pytest --confcutdir=tests/api/routes
tests/api/routes/test_testing_agent.py -q`.

## Fresh source-of-truth suite timings

Measured on the same host with `npm --prefix acceptance-tests run test:specs`
and a fresh project for each run. Backend recreations exclude initial startup.

| Version | Run | Scenarios | Steps | Result | Backend recreations | Wall time (s) |
| --- | ---: | ---: | ---: | --- | ---: | ---: |
| Before reuse | 1 | 88 | 514 | Passed | 62 | 1111.78 |
| Before reuse | 2 | 88 | 514 | Passed | 62 | 1113.66 |

Run specific scenario
```sh
cd acceptance-tests & PWDEBUG=1 npx cucumber-js --name "^User updates a repository through OpenCode$"
```