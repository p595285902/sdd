# Develop agent runner

Develop agent runner executes deterministic exploration operations inside ready Development Workspaces.

## ADDED Requirements

### Requirement: Exploration produces durable normalized results
The system SHALL execute an exploration in the owning chat's ready Development Workspace and SHALL persist its user message, normalized bounded activity, assistant response, and validated agent session.

#### Scenario: User explores a ready repository

```gherkin
Given an authenticated user owns a Development Chat with a ready workspace
When the user submits an exploration message
Then the user message is stored before agent execution starts
And ordered agent activity and response text are normalized
And the completed assistant response is stored with the validated agent session
```

### Requirement: Agent execution failures are bounded and safe
The system MUST bound agent activity, terminate command process groups on cancellation or failure, and scrub configured secrets before output is logged, raised, returned, or persisted.

#### Scenario: Agent output contains a configured secret

```gherkin
Given agent output contains a configured repository or provider secret
When the output is logged, stored, or returned
Then the complete secret value is not present
And a redacted value is used instead
```
