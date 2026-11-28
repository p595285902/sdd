# Acceptance tests

Cucumber-js suite that extracts the Gherkin specs under `openspec/` and runs
the **effective spec** — the source of truth plus every active change's delta —
against one fresh Docker Compose stack per invocation.

The spec format, extraction, composition, and Page Object Model conventions
are defined by the `acceptance-test-authoring` skill; this project is the
`stack: javascript` binding of them.

## Prerequisites

- Node.js 20+
- Docker with Compose v2 (the daemon must be running)

## Install

```sh
cd acceptance-tests
npm install
npx playwright install chromium
```

## Run

```sh
npm test           # effective spec: source of truth + active change deltas
npm run test:specs # source-of-truth-only regression run
npm run lint:specs # extract, then gherkin-lint the extracted specs
```

`npm test` starts `db` and `backend` under a unique Compose project on a free
localhost port, applies migrations and the first superuser, waits for
`/api/v1/utils/health-check/`, runs Chromium headless, then tears the stack
down with volumes. Backend logs are printed if the stack fails to become
healthy.

The HTML report is always written to
`acceptance-tests/reports/cucumber-report.html`.

## Layout

- `extract-gherkin.cjs`, `cucumber.cjs`, `openspec-effective-paths.cjs`,
  `.gherkin-lintrc` — copied verbatim from the skill; do not edit them here.
- `support/app-lifecycle.js` — Compose stack lifecycle (unique project, free
  port, migrations, health poll, teardown).
- `support/hooks.js` — one browser per suite, one fresh context per scenario.
- `support/world.js` — thin HTTP client plus the Playwright page/context.
- `support/pages/` — page objects; all UI selectors live here.
- `step-definitions/` — step implementations, expressed in page-object calls.
- `compose.yml` — override of the root `compose.yml` for the test stack.

`.extracted/` is generated on every run and gitignored — never edit it.
Extraction preserves line numbers, so a runner or lint position
`.extracted/X/spec.feature:12` is `openspec/X/spec.md:12`.

## Specs

Specs live in `openspec/specs/<capability>/spec.md` and, for active changes,
`openspec/changes/<id>/specs/<capability>/spec.md`. Structure is Markdown
headings; only Given/When/Then steps sit in column-0 ` ```gherkin ` fences.
Never edit or tag a spec to skip a scenario — superseded rules are excluded by
the runner's composition instead.
