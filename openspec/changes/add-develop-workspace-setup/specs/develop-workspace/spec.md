# Develop workspace

Develop workspace gives each Development Chat an isolated checkout of one configured repository.

## ADDED Requirements

### Requirement: Repository setup creates an isolated Development Workspace
The system SHALL let a user set up either the configured repository or the demo repository in a workspace dedicated to one Development Chat, SHALL initialize `opencode` and `openspec` there, and MUST keep credentials out of client-visible responses and process arguments. The demo repository action SHALL use only `DEMO_GITHUB_REPO` and `DEMO_GITHUB_TOKEN` and SHALL appear next to the configured repository action.

#### Scenario: User sets up the configured repository

```gherkin
Given an authenticated user owns a Development Chat without a ready workspace
When the user selects Set up repository
Then the configured repository is cloned into that chat's isolated Development Workspace
And opencode and openspec are initialized in the Development Workspace
```

#### Scenario: Repository setup is unavailable when configuration is missing

```gherkin
Given the configured repository credentials are incomplete
When a user attempts to set up a repository
Then repository setup fails with a safe configuration error
And no credential value is returned
```

#### Scenario: User sets up the demo repository

```gherkin
Given an authenticated user owns a Development Chat without a ready workspace
And the demo repository is configured
When the user selects Set up demo repository next to Set up repository
Then the configured demo repository is cloned into that chat's isolated Development Workspace
And opencode and openspec are initialized in the Development Workspace
```

#### Scenario: Demo repository setup is unavailable when configuration is missing

```gherkin
Given the demo repository credentials are incomplete
When a user attempts to set up the demo repository
Then demo repository setup fails with a safe configuration error
And no demo credential value is returned
```

#### Scenario: Development Workspaces are isolated

```gherkin
Given two Development Chats have ready workspaces
When a command runs for one Development Chat
Then the command runs inside only that chat's Development Workspace
And the other Development Workspace is unchanged
```

### Requirement: Development Workspace deletion is confirmed and complete
The system MUST require confirmation before permanently deleting a Development Chat and SHALL safely delete its messages and isolated Development Workspace.

#### Scenario: User cancels Development Chat deletion

```gherkin
Given an authenticated user has opened the delete confirmation for a Development Chat
When the user cancels deletion
Then the Development Chat and its Development Workspace remain available
```

#### Scenario: User confirms Development Chat deletion

```gherkin
Given an authenticated user owns a Development Chat with a ready workspace
When the user confirms permanent deletion
Then the Development Chat and all of its messages are deleted
And its isolated Development Workspace is deleted
```
