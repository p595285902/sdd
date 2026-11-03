# Acceptance state reset

Reset is a test-environment control mechanism operating on real acceptance data and resources, not a mock service or an arbitrary Python execution endpoint. All resource scopes come from the owned run, not caller-supplied database names, paths, or Docker projects.

## ADDED Requirements

### Requirement: Reset controls are restricted to the owned acceptance run
The system MUST expose reset, reset-status, and scenario-configuration controls only in acceptance mode with explicit run-scoped reset credentials and validated acceptance ownership. These controls MUST authenticate independently of database users being reset, reject missing or incorrect credentials and mismatched run identity before mutation, and MUST NOT disclose reset credentials or repository tokens. A caller MUST NOT select another database, filesystem root, or Docker project. Controls MUST be absent outside acceptance mode, including the controller's destructive bulk-reset control.

#### Scenario: Reset controls are unavailable outside acceptance mode

```gherkin
Given separate lifecycle validation has started the application without acceptance reset mode
When a client requests acceptance reset or configuration controls
Then those controls are unavailable
And application data and resources remain unchanged
```

#### Scenario: An unauthenticated reset cannot change state

```gherkin
Given an acceptance stack contains scenario data and workspace files
When reset is requested without the current run's valid reset credential
Then reset is rejected before any data or resource is changed
And the stack remains usable with its existing state
```

#### Scenario: Reset cannot target a different run

```gherkin
Given an acceptance stack and unrelated project resources contain distinct state
When an authenticated reset request supplies a different run identity or resource scope
Then the request is rejected before mutation
And both sets of resources remain unchanged
```

### Requirement: Reset reaches quiescence before removing mutable state
The system MUST close admissions for state-mutating scenario work, request cancellation of prior turns and setup or preview operations, and await their actual termination before deleting their data or workspaces. Quiescence MUST include completion handlers, provider requests, preview preparation and launch work, and controller maintenance that can recreate state. Clearing registries or setting cancellation flags alone MUST NOT count as quiescence. Reset MUST enforce a finite total deadline; no old operation may write data, consume a new fake reply, or recreate resources after successful reset.

#### Scenario: Active work finishes before its state is removed

```gherkin
Given a scenario has an active Agent Turn and scenario-owned preview or workspace setup work
When authenticated scenario reset is requested
Then admissions close and the prior work is stopped and joined before state is removed
And no prior operation recreates data or consumes replies after reset completes
And the next scenario can start a new turn with baseline capacity
```

#### Scenario: Mutating work cannot enter during reset

```gherkin
Given authenticated scenario reset is in progress
When another request attempts to start a turn, set up a workspace, or launch a preview
Then that request is rejected until the reset boundary completes
And it does not create partially reset scenario state
```

### Requirement: Reset restores a canonical database baseline
The system MUST remove prior scenario users, items, chats, messages, and other mutable application records from the owned acceptance database while preserving schema and migration metadata. It MUST restore the declared bootstrap administrator's credentials, privileges, active state, and concurrency settings even if a scenario changed or deleted them. Reset MUST NOT depend on retaining a possibly modified administrator row or on rollback of only the test client's transaction. All prior database work MUST have drained before baseline restoration is acknowledged.

#### Scenario: Database reset repairs modified bootstrap state

```gherkin
Given a scenario has created users, items, chats, and messages
And has changed the bootstrap administrator's credentials or privileges
When authenticated scenario reset completes
Then only the declared database baseline remains
And the bootstrap administrator can authenticate with the baseline permissions and concurrency settings
And the database schema and migration version remain unchanged
```

### Requirement: Reset removes workspace and agent state independently of database rows
The system MUST remove scenario-owned checkouts, temporary credential files, fixture outputs, and persisted agent-session or CLI state using fixed acceptance-owned roots. Resource discovery MUST NOT depend solely on surviving database chat rows. Cleanup MUST preserve mounted stack volumes and their roots, and MUST NOT follow unsafe paths into unrelated directories. Agent HOME and XDG storage used during acceptance execution MUST be confined to resettable run-owned locations; a previous scenario's session or configuration MUST NOT reach a later scenario.

#### Scenario: Orphan files and agent sessions do not survive reset

```gherkin
Given a scenario has left a checkout without a database chat row
And has persisted agent-session data and temporary credential files in acceptance-owned storage
When authenticated scenario reset completes
Then those files and session data are absent
And mounted workspace storage remains available on the same stack
And the next scenario does not inherit the previous agent session or credentials
```

### Requirement: The controller removes all scenario-owned preview state
The preview controller MUST enumerate and remove acceptance-run-owned scenario workloads, build helpers, private networks, socket volumes, and chat-owned images independently of database rows or the current page helper's tracked preview list. It MUST clear scenario routing, failure, and activity state only after relevant work has drained. Backend reset coordination MUST use the existing internal controller boundary; it MUST NOT acquire the Docker socket or manipulate unrelated projects. Long-lived stack/control resources and bounded verified immutable run-local preparation MAY remain, but mutable chat state and private resources MUST NOT be reused by another scenario.

#### Scenario: Untracked preview resources are removed without stopping stack services

```gherkin
Given a scenario has left preview resources outside its page helper's tracked list
And an unrelated project has its own preview resources
When authenticated scenario reset completes
Then every scenario-owned preview resource and routing entry is removed
And unrelated preview resources remain unchanged
And the same backend, database, and preview-controller services remain running
```

### Requirement: Reset acknowledges a verified and retry-safe baseline
Reset MUST return success only after quiescence and verification of database, workspace, agent, preview, provider, and configuration baselines. Its acknowledgement MUST identify the owned run and reset generation without exposing secrets. Requests MUST be serialized and duplicate reset identifiers MUST be safe to retry when no new scenario work has begun; concurrent conflicting requests and stale retries after new scenario work begins MUST be rejected without clearing that work. Provider replies, recorded requests, timing overrides, and effective repository configuration MUST return to their declared baseline after old work drains.

#### Scenario: A verified reset isolates the next real scenario

```gherkin
Given a scenario has modified database records, workspace files, fake-provider state, and acceptance configuration
When authenticated scenario reset reports verified completion
Then the reset acknowledgement identifies the current run and its new baseline generation
And the next scenario sees only the declared baseline through real application operations
And it uses a fresh browser and request context on the unchanged stack
```

#### Scenario: A lost reset response can be retried safely

```gherkin
Given reset has completed but its acknowledgement was lost before new scenario work started
When the same authenticated reset identifier is retried
Then the verified completion is returned without conflicting cleanup or additional baseline records
And the stack services and mounted volumes remain unchanged
```

#### Scenario: A stale retry cannot erase a new scenario

```gherkin
Given a verified reset has completed and the next scenario has created new state
When the previous reset identifier is retried
Then the stale request is rejected
And the new scenario's data and work remain unchanged
```

### Requirement: Unverified reset fails the invocation without a replacement stack
A reset that exceeds its total deadline, cannot prove quiescence, or encounters cleanup or baseline-verification failure MUST NOT report success or permit another scenario to start. The runner MUST report the failed phase without secrets, fail the invocation, and perform final owned-resource teardown rather than restart services and continue. These terminal harness behaviors MUST be verified in separate lifecycle validation so intentionally failing invocations do not run as nested stacks inside the normal suite.

#### Scenario: A reset deadline aborts the invocation

```gherkin
Given separate lifecycle validation runs an isolated acceptance invocation with work that cannot quiesce within its reset deadline
When that invocation requests scenario reset
Then reset reports failure and no later scenario starts
And the invocation fails without restarting or replacing its stack services
And final teardown removes its owned resources without changing unrelated projects
```

#### Scenario: Cleanup failure cannot produce a successful reset

```gherkin
Given separate lifecycle validation runs an isolated acceptance invocation whose workspace or preview cleanup cannot complete
When that invocation requests scenario reset
Then the failed cleanup phase is reported without a successful baseline acknowledgement
And the invocation fails and tears down rather than continuing on contaminated state
```
