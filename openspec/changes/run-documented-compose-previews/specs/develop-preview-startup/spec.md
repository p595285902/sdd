# Develop preview startup

## REMOVED Requirements

### Requirement: Preview starts when the selected checkout needs it

Reason: Context opening and completed Agent Turns must no longer trigger startup.
Migration: Use the explicit Launch or Restart action defined below.

## ADDED Requirements

### Requirement: Preview startup requires an explicit action
The system SHALL start a stopped preview only through an explicit Launch or Restart action for the selected Development Chat. Opening or expanding Context, resolving instructions, refreshing/reconnecting, receiving activity heartbeats, and completion of an Agent Turn MUST NOT start or restart a stopped preview. Launch SHALL execute immediately without a separate approval dialog when the workspace is ready and instructions are resolvable. Repeated launch requests while the same chat is launching or running MUST NOT create duplicate executions. Existing healthy previews SHALL remain available for documented hot reload and workspace synchronization without implicit relaunches. After idle expiry, another explicit user action SHALL be required to start a new workload.

#### Scenario: First Context visit leaves the original checkout stopped

```gherkin
Given a Development Chat has a ready checkout and resolved startup instructions
When the user opens or expands Context before any file-changing Agent Turn
Then that chat's preview remains stopped
And no startup command is executed
```

#### Scenario: Relevant turn does not start a stopped preview

```gherkin
Given a Development Chat has a stopped preview and resolved startup instructions
When an Agent Turn completes after changing a non-ignored source file
Then that chat's preview remains stopped
And no startup command is executed
```

#### Scenario: Launch explicitly starts the selected checkout

```gherkin
Given an authenticated user has selected a Development Chat with a ready checkout and documented Compose workflow
When the user clicks Launch beside Expand
Then startup begins only for that chat without another approval dialog
And startup commands and output appear in that chat while execution is in progress
```

#### Scenario: Repeated launch does not create another execution

```gherkin
Given a Development Chat already has a launching or running preview
When another Launch request arrives for that chat
Then no duplicate command sequence or sandbox is created
And the existing execution status is returned
```

#### Scenario: Refresh and idle expiry do not trigger startup

```gherkin
Given a Development Chat's preview has expired after inactivity
When the user reloads the chat and opens Context
Then the previous launch output remains available
And the preview remains stopped until another explicit Launch or Restart action
```

### Requirement: Native Compose readiness follows the application
The system SHALL determine native Compose readiness from the documented main application's response inside the sandbox and SHALL respect required dependency startup ordering. It MUST NOT wait for a long-running `watch` or foreground server command to exit, treat mere process creation as readiness, or substitute an auxiliary tool's responding port for the application. A failed initialization, fatal startup failure, or readiness timeout SHALL report the failed step and useful redacted output in chat.

#### Scenario: Watch keeps running after the application becomes ready

```gherkin
Given the selected chat's documented Compose watch command is running
When the main application begins responding on its resolved entry point
Then the preview becomes ready without waiting for the watch command to exit
And Context displays the application rather than a supporting tool
```

#### Scenario: A responding supporting tool does not make the application ready

```gherkin
Given a Development Chat's database administration tool responds while its application is still starting
When readiness is checked
Then the preview is not marked ready for that tool
And startup status continues to describe the application's progress
```
