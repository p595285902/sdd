# Acceptance stack reuse

## Purpose

TBD: Describe why the acceptance runner reuses an unchanged backend configuration while retaining a fresh stack for each full-suite run.

## Requirements

### Requirement: Unchanged acceptance configuration reuses the backend within a run
The acceptance runner MUST NOT recreate its backend when a scenario requests the demo-repository configuration already active in that backend. It MUST preserve scenario-specific cleanup and fresh browser contexts without relying on a redundant restart to clear process-local test state.

#### Scenario: Consecutive scenarios request the same repository configuration

```gherkin
Given an acceptance run has a backend with the demo repository configured
When successive scenarios request that same repository configuration
Then the backend is not recreated between those requests
And each scenario retains its fresh browser context and independent test state
```

### Requirement: Changed acceptance configuration is applied
When the requested demo-repository configuration differs from the configuration active in the backend, the acceptance runner MUST apply the change before the requesting scenario executes. It MUST NOT report an unchanged configuration as a reason to use stale or unverified backend state.

#### Scenario: Repository configuration changes and is restored

```gherkin
Given an acceptance run has a backend with the demo repository configured
When a scenario requests an unconfigured demo repository
Then that scenario uses a backend with the demo repository unconfigured
When a later scenario requests the configured demo repository
Then the later scenario uses a backend with the demo repository configured
And another request for that configuration does not recreate it
```

### Requirement: Fresh-run lifecycle remains unchanged
The default acceptance runner and CI MUST continue using a fresh project-scoped stack for each full-suite run, and MUST tear down only that run's containers, networks, and volumes after execution, including a failed run. Avoiding redundant backend recreation within a run MUST NOT retain the stack across runs or reset unrelated projects.

#### Scenario: A completed run does not leave a reusable stack

```gherkin
Given the default acceptance suite starts a fresh project-scoped stack
When its scenarios finish
Then only that run's project is torn down
And a subsequent full-suite run starts a separate fresh project
```
