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