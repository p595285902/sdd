## 1. Baseline and backend recreation

- [ ] 1.1 Record multiple full source-of-truth suite timings, scenario counts, pass/fail results, and backend recreation counts on one host; retain a comparable scenario set for post-change measurements.
- [ ] 1.2 Add focused tests for an unchanged configured request, a configured-to-unconfigured transition and restoration, unexpected backend replacement, and failed recreation.
- [ ] 1.3 Track the effective configuration of the live acceptance backend and skip Compose recreation only when the requested configuration matches a healthy, verified backend; recreate and wait for health on genuine changes.
- [ ] 1.4 Audit process-local state previously cleared by forced recreation and add only the acceptance-specific reset needed to preserve scenario independence; verify existing scenario-owned preview cleanup and fresh browser contexts.
- [ ] 1.5 Document the optimized within-run lifecycle, fresh-stack default/CI teardown, and how to diagnose configuration or backend-health failures in acceptance-tests/README.md.

## 2. Step definitions — each pending step fails for the right reason, then passes, then is committed

- [ ] 2.1 Define `Given an acceptance run has a backend with the demo repository configured` — red → green → commit.
- [ ] 2.2 Define `When successive scenarios request that same repository configuration` — red → green → commit.
- [ ] 2.3 Define `Then the backend is not recreated between those requests` — red → green → commit.
- [ ] 2.4 Define `And each scenario retains its fresh browser context and independent test state` — red → green → commit.
- [ ] 2.5 Define `When a scenario requests an unconfigured demo repository` — red → green → commit.
- [ ] 2.6 Define `Then that scenario uses a backend with the demo repository unconfigured` — red → green → commit.
- [ ] 2.7 Define `When a later scenario requests the configured demo repository` — red → green → commit.
- [ ] 2.8 Define `Then the later scenario uses a backend with the demo repository configured` — red → green → commit.
- [ ] 2.9 Define `And another request for that configuration does not recreate it` — red → green → commit.
- [ ] 2.10 Define `Given the default acceptance suite starts a fresh project-scoped stack` — red → green → commit.
- [ ] 2.11 Define `When its scenarios finish` — red → green → commit.
- [ ] 2.12 Define `Then only that run's project is torn down` — red → green → commit.
- [ ] 2.13 Define `And a subsequent full-suite run starts a separate fresh project` — red → green → commit.

## 3. Verification

- [ ] 3.1 Extract and lint the delta; dry-run effective composition to confirm no duplicate, archived, or superseded scenarios.
- [ ] 3.2 Run focused lifecycle tests, the full effective acceptance suite after every code change, and the source-of-truth regression suite; require zero pending/undefined steps and an HTML report.
- [ ] 3.3 Verify configured/unconfigured transitions, consecutive unchanged requests, and failure recovery without changing a normal development Compose project.
- [ ] 3.4 Repeat the same fresh full-suite profile used for the baseline several times; record wall-time medians and backend recreation counts, and report the observed difference without a percentage gate or an unverified performance claim.
