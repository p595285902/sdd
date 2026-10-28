# Acceptance stack reuse

The local opt-in workflow retains a dedicated acceptance application while each test invocation starts from known-clean state. The default and CI workflows remain isolated.

## ADDED Requirements

### Requirement: Warm acceptance runs start clean
An opt-in local warm acceptance run MUST reuse only its dedicated acceptance stack when its inputs are current, and MUST reset and verify database records, development workspaces, captured mail, and preview workloads before running any scenario. It MUST give each scenario a fresh browser context and MUST NOT depend on data left by other scenarios.

#### Scenario: Repeated full run reuses a clean stack

```gherkin
Given an opt-in warm acceptance stack completed a test run
And that run left acceptance data, a development workspace, captured mail, and a preview workload
When the next full acceptance run starts without source or configuration changes
Then the same backend is reused
And database records, development workspaces, captured mail, and preview workloads from the earlier run are absent before scenarios execute
And the initial acceptance administrator is available
```

#### Scenario: A filtered warm run starts clean

```gherkin
Given an opt-in warm acceptance stack completed a test run with persisted state
When a filtered acceptance run starts on that stack
Then persisted state from the earlier run is absent before its scenario executes
And the scenario receives a fresh browser context
```

#### Scenario: Failed reset prevents execution

```gherkin
Given an opt-in warm acceptance stack has state that cannot be reset or verified
When an acceptance run starts on that stack
Then no scenario executes
And the runner reports the failed reset and how to recover with a fresh acceptance stack
```

### Requirement: Warm reuse respects freshness and exclusive ownership
The warm runner MUST detect changes to relevant application build inputs and acceptance configuration, including uncommitted changes, and rebuild and restart its acceptance stack before testing changed code. It MUST NOT allow concurrent invocations to share one warm stack or modify any non-acceptance Compose project.

#### Scenario: Relevant changes restart the warm backend

```gherkin
Given an opt-in warm acceptance stack completed a test run
When backend, frontend, or acceptance configuration inputs change locally
And another acceptance run starts
Then the acceptance stack is rebuilt and restarted with the changed inputs
And its persistent state is verified clean before scenarios execute
```

#### Scenario: Simultaneous invocation is rejected

```gherkin
Given an acceptance run owns the opt-in warm stack
When another run tries to use the same warm stack
Then the second run fails with a stack-in-use error
And the first run's state is not reset or stopped
```

### Requirement: Default acceptance runs remain isolated
The default acceptance runner and CI MUST continue using a fresh project-scoped stack for each run and MUST tear down only that run's containers, networks, and volumes after execution, including a failed run.

#### Scenario: Default run does not reuse warm state

```gherkin
Given an opt-in warm acceptance stack exists
When the default acceptance suite runs
Then it starts in a separate fresh acceptance project
And it tears down only its own project after execution
And the opt-in warm acceptance stack remains available
```
