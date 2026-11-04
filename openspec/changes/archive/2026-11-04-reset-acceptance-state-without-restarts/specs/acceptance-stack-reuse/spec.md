# Acceptance stack reuse

The normal scenario suite uses one unchanged real application stack. Dedicated lifecycle and terminal harness-failure checks execute separately, not as nested stack probes in that suite. The complete acceptance gate includes both reported groups.

## MODIFIED Requirements

### Requirement: Unchanged acceptance configuration reuses the backend within a run
The acceptance runner MUST execute normal scenarios serially against one fresh project-scoped stack. Backend, database, preview-controller, and mounted stack-volume identities MUST remain unchanged between scenarios, including when reset is performed. The normal suite MUST NOT launch additional lifecycle-probe stacks. The runner MUST preserve fresh browser and request contexts and await verified scenario-state reset before starting the next scenario. Disposable chat-preview workloads MAY be created, stopped, or restarted as required by their existing specifications; they are not long-lived stack services.

#### Scenario: Consecutive scenarios request the same repository configuration

```gherkin
Given an acceptance run has a backend with the demo repository configured
When successive scenarios request that same repository configuration
Then the backend is not recreated between those requests
And each scenario retains its fresh browser context and independent test state
```

#### Scenario: Normal scenarios retain one stack across resets

```gherkin
Given a normal acceptance scenario suite has recorded its stack service and volume identities
When successive scenarios complete with a verified reset between them
Then all scenarios use the same healthy stack services and mounted volumes without restarts
And no additional acceptance stack is started inside the normal suite
And the scenarios execute without overlapping one another
```

### Requirement: Changed acceptance configuration is applied
When the requested demo-repository configuration differs from the effective acceptance configuration, the runner MUST apply and verify an acceptance-only scenario override before the requesting operation executes, without restarting or recreating a stack service. The override MUST use only the runner's declared demo-repository baseline and unavailable configuration, MUST NOT accept arbitrary repositories or credentials, and MUST return to baseline during scenario reset. Configuration transitions within one scenario MUST NOT erase its database or workspace fixtures. Production environment-based repository configuration MUST remain unchanged.

#### Scenario: Repository configuration changes and is restored

```gherkin
Given an acceptance run has a backend with the demo repository configured
When a scenario requests an unconfigured demo repository
Then that scenario uses a backend with the demo repository unconfigured
When a later scenario requests the configured demo repository
Then the later scenario uses a backend with the demo repository configured
And another request for that configuration does not recreate it
And neither configuration transition restarts a stack service
```

#### Scenario: Reset restores configuration without losing fixtures inside a scenario

```gherkin
Given a scenario has database and workspace fixtures in the shared stack
When that scenario changes the effective demo-repository configuration and restores it
Then its existing fixtures remain available throughout those configuration changes
When the scenario finishes with the demo repository unavailable
And scenario state is reset
Then the next scenario observes the declared demo-repository baseline on the same backend
```

### Requirement: Fresh-run lifecycle remains unchanged
Each normal scenario-suite invocation MUST start a fresh project-scoped stack and MUST tear down only its owned containers, networks, and volumes after execution, including failure and controlled cancellation. Stack reuse MUST NOT persist across invocations or reset unrelated projects. Real fresh-run and teardown probes MUST run in separately reported serial lifecycle validation, with no normal-suite stack left running when those probes start. Lifecycle validation MUST remain a required part of complete acceptance verification and CI.

#### Scenario: A completed run does not leave a reusable stack

```gherkin
Given dedicated acceptance lifecycle validation runs separately from the normal scenario suite
When it completes two fresh acceptance lifecycle invocations serially
Then those invocations use distinct project-scoped stacks
And each completed invocation leaves no owned containers, networks, or volumes
And neither invocation modifies unrelated project resources
```

#### Scenario: A failed invocation removes only its owned stack

```gherkin
Given dedicated lifecycle validation has started an isolated acceptance invocation
And unrelated project resources exist
When that acceptance invocation fails during execution
Then the failed invocation removes its owned stack and preview resources
And unrelated project resources remain unchanged
```

#### Scenario: Controlled cancellation removes the owned stack

```gherkin
Given dedicated lifecycle validation has started an isolated acceptance invocation
When that invocation receives a supported cancellation signal
Then it reports cancellation and removes its owned stack and preview resources
And it does not start a replacement stack
```

## ADDED Requirements

### Requirement: Separate validation groups retain complete effective-spec coverage
The complete acceptance command MUST freshly discover the effective specification and assign every effective scenario exactly once to either the single-stack normal suite or separate lifecycle and terminal harness-validation execution. It MUST run those groups serially, report their assignments and results explicitly, generate HTML reporting, and fail if either group fails or discovery is incomplete or duplicated. Standalone group runs MUST be identified as partial validation and MUST NOT authorize sync or archive. Source-of-truth regression MUST support the same explicit grouping without executing active deltas. Superseded and archived scenarios MUST remain excluded by the existing composition rules, not marked skipped. Command-level validation MUST execute separately from the normal suite using freshly composed isolated test inventories without recursively invoking its own validation scenarios; those probes MUST NOT substitute for running the complete repository inventory.

#### Scenario: Complete validation includes both disjoint groups

```gherkin
Given separate command validation has freshly composed an isolated effective-spec inventory containing normal and lifecycle scenarios
When the complete acceptance command executes that test inventory
Then every test-inventory scenario is assigned to and executed in exactly one reported group
And the normal suite finishes and tears down before separate lifecycle validation starts
And the combined status fails if either group fails
And the HTML reporting identifies both groups without silently skipped coverage
```

#### Scenario: A newly discovered scenario cannot disappear from validation

```gherkin
Given separate command validation has added an effective scenario to its isolated test inventory since the previous report
When the complete acceptance command freshly discovers that test inventory's validation groups
Then the new scenario appears exactly once in the appropriate group
And historical reports do not determine the scenario inventory
```
