# Develop agent runner

## Purpose

Provide deterministic, bounded, and secret-safe agent exploration inside ready Development Workspaces.

## Requirements

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

#### Scenario: User updates a repository through OpenCode

```gherkin
Given an authenticated user owns a Development Chat with a ready workspace
And OpenCode is connected to an OpenAI-compatible LLM
When the user types "update the readme file to append `test`" in the chatbox
Then OpenCode sends the prompt to the configured LLM
And OpenCode appends "test" to the README file
And the chatbox displays OpenCode's response
```

### Requirement: Agent execution failures are bounded and safe
The system MUST provide the configured provider credential to OpenCode as `OPENAI_API_KEY`, bound agent activity, terminate command process groups on cancellation or failure, and scrub configured secrets before output is logged, raised, returned, or persisted.

#### Scenario: OpenCode receives the provider credential

```gherkin
Given the OPENAI_API_KEY environment variable is configured
When an OpenCode exploration starts
Then OpenCode connects to the OpenAI provider using OPENAI_API_KEY
```

#### Scenario: Agent output contains a configured secret

```gherkin
Given agent output contains the configured OPENAI_API_KEY or repository secret
When the output is logged, stored, or returned
Then the complete secret value is not present
And a redacted value is used instead
```