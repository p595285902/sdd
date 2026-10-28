## 1. Establish the measured opportunity

- [ ] 1.1 Add acceptance-only diagnostics for preview dependency preparation, image builds, and workload creation/start, reporting counts and elapsed time per run without exposing checkout contents or credentials.
- [ ] 1.2 Run the effective suite with a fresh project when Docker registry access permits; record successful scenario counts, preview operation counts, and wall time, distinguishing the README's historical 496.90-second result from the current baseline.

## 2. Reuse prepared inputs safely

- [ ] 2.1 Identify the measured repeated preparation path; remove harness-side redundant work first and do not cache an operation that does not materially affect suite time.
- [ ] 2.2 If necessary, implement a bounded, acceptance-only, controller-lifetime cache of validated immutable preparation keyed by complete staged inputs and effective runtime/build settings; preserve production behavior, validation, explicit errors, and per-chat containers.
- [ ] 2.3 Add focused tests for identical-input reuse, source/dependency/build/runtime invalidation, failed preparation, cache bounds, fresh controller/project state, and preserved chat-owned cleanup and image labels.

## 3. Acceptance step definitions

Implement each pending step through intent-level methods in `acceptance-tests/support/pages/` and thin definitions in `acceptance-tests/step-definitions/`; verify a targeted red-to-green result for each, then keep the effective suite green before completing code work.

- [ ] 3.1 Implement `Given an acceptance run has prepared a preview for a Development Chat` using an independently owned chat and observable preparation count.
- [ ] 3.2 Implement `When a different Development Chat starts a preview with identical preparation inputs` with a separate checkout.
- [ ] 3.3 Implement `Then the second preview reuses the prepared inputs without repeating their preparation` using diagnostics rather than timing alone.
- [ ] 3.4 Implement `And each chat has a distinct running preview workload using only its own checkout`.
- [ ] 3.5 Implement `Given an acceptance run has prepared preview inputs for a Development Chat` for the changed-input cases.
- [ ] 3.6 Implement `When another chat starts a preview with changed dependency inputs`.
- [ ] 3.7 Implement `Then the changed inputs are prepared afresh`.
- [ ] 3.8 Implement `And the second chat receives a preview of its changed checkout`.
- [ ] 3.9 Implement `When another chat starts a preview with changed source or build instructions`.
- [ ] 3.10 Implement `Given an acceptance run has prepared preview inputs` for the separate-run case.
- [ ] 3.11 Implement `When a separate acceptance run starts a preview with identical inputs` using a distinct project and explicit cleanup.
- [ ] 3.12 Implement `Then the separate run does not inherit the first run's prepared preview inputs`.
- [ ] 3.13 Implement `And the first run's preview workloads and private resources remain unavailable to the separate run`.

## 4. Completion and documentation

- [ ] 4.1 Run spec extraction/lint, focused controller and lifecycle tests, and an effective-suite dry run; confirm new scenarios are discovered once and archived scenarios are excluded.
- [ ] 4.2 Run the full effective acceptance suite after code changes, with zero failed, pending, or undefined steps and an HTML report. Verify isolation, restart/deletion behavior, and cleanup, then compare successful wall time and operation counts against the recorded baseline.
- [ ] 4.3 Document the measurement, cache lifetime/invalidation, and failure diagnostics in `acceptance-tests/README.md`; if the suite is not faster, report that outcome and remove or revise the ineffective optimization rather than claiming success.
