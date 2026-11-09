# Develop preview execution

## ADDED Requirements

### Requirement: Preview execution is an explicit owner-scoped operation
The system SHALL record an execution attempt when the authenticated owner explicitly launches or restarts the selected Development Chat's preview, including instruction-resolution failures. The operation SHALL identify its owning chat, documented workflow, ordered commands, timestamps and status, independently of user/assistant Development Messages and Agent Turns. Starting, running and terminal states SHALL be distinguishable from application readiness; becoming ready MUST NOT complete a still-running watch session. At most one execution SHALL own active runtime resources for a chat. Concurrent/retried launch requests SHALL reattach to the current execution rather than repeat initialization. Another user's launch, history, status or output request MUST be rejected without exposing the owning chat's records.

#### Scenario: Launch produces an operation rather than an assistant turn

```gherkin
Given an authenticated user owns a ready Development Chat with documented Compose startup
When the user launches its preview
Then a preview execution attempt is recorded for that chat
And no assistant message or Agent Turn is created merely to run the commands
And command execution begins without a second approval request
```

#### Scenario: Concurrent launches share one execution

```gherkin
Given a Development Chat has no active preview execution
When two Launch requests for that chat arrive concurrently
Then exactly one execution owns the new sandbox
And initialization executes once
And both requests identify the same active execution
```

#### Scenario: Another owner cannot access execution records

```gherkin
Given a Development Chat has persisted command output owned by another user
When the current user requests that execution's launch controls, history or stream
Then access is denied
And no command or output from the other chat is disclosed
```

### Requirement: Commands and output are durably ordered and replayable
The system SHALL durably persist command-start, stdout, stderr, command-exit and execution-status events with a stable execution identity and monotonically ordered event cursor. Events SHALL be persisted before being acknowledged to the browser and SHALL stream incrementally while startup or watch is running. History/replay SHALL restore the same event ordering and resume after the last received cursor without duplicate display or command execution. A bounded live stream or stored-output limit SHALL produce an explicit gap/truncation marker and MUST NOT lose final command or execution status. Execution records SHALL survive workload cleanup and remain accessible only through the owning chat until chat deletion.

#### Scenario: Output streams before startup finishes

```gherkin
Given a Development Chat has an active initialization command
When the command emits output while still running
Then the chat receives its command-start and output events before command completion
And those events are already durable when displayed
```

#### Scenario: Reconnection resumes ordered output

```gherkin
Given a browser disconnected after receiving part of a preview execution's output
When it reconnects with the last received event cursor
Then the remaining persisted events are replayed in order
And new live events continue without duplicate display or another command execution
```

#### Scenario: Output retention limits are visible

```gherkin
Given a preview execution emits output beyond its configured retention limit
When the retained output is displayed or replayed
Then a truncation marker identifies omitted output
And command exit statuses and the execution's final status remain available
```

### Requirement: Preview diagnostics are safe and actionable
The system SHALL mask known project-secret and credential values before persisting, streaming or logging command/output records, including secrets split across output chunks. It SHALL escape untrusted output for safe text rendering and SHALL NOT expose platform credentials. Missing/conflicting instructions, failed setup, denied configuration and startup timeouts SHALL retain a useful diagnostic identifying the failed phase, redacted command and exit status when available. Diagnostics MUST NOT automatically edit project code/configuration, invent replacement commands or require an execution approval dialog. Redaction SHALL be described as masking known values, not a guarantee against arbitrary deliberate disclosure by hostile project code.

#### Scenario: A secret split across output chunks is masked

```gherkin
Given a documented project environment file supplies a known secret to a preview execution
When a command prints that value across multiple stdout or stderr chunks
Then the secret is masked before those events are stored or delivered
And replay and operational logs do not reveal the original value
```

#### Scenario: Instruction-resolution failure is retained

```gherkin
Given a Development Chat's documentation does not identify a complete startup workflow
When the owner clicks Launch
Then a failed execution record explains the missing instructions in that chat
And no undocumented command or sandbox application service starts
```

#### Scenario: Project output is not executable conversation content

```gherkin
Given a preview command prints markup or terminal control sequences
When its output is displayed in the chat
Then the output is rendered as safe operation text
And it cannot execute scripts or become an instruction for an Agent Turn
```
