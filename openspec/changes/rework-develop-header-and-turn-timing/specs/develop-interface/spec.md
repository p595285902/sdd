# Develop interface

## MODIFIED Requirements

### Requirement: Develop presents and controls streamed exploration
The application SHALL provide an authenticated responsive workspace for chat history, conversation, context, repository setup, safe Markdown, incremental Agent Turn activity, reattachment, Stop, and Presence Mode controls. The selected chat's header MUST contain the repository setup/status control, a rename control beside the title, and a Presence Mode dropdown beside Delete. The Context panel and its mobile entry point SHALL remain available, with an empty state when no additional context exists. Agent activity SHALL show elapsed time while a turn runs and its final duration when a completed assistant message is displayed.

#### Scenario: Streamed exploration is displayed

```gherkin
Given an authenticated user starts exploration in a ready Development Workspace
When normalized Agent Turn events arrive
Then expandable activity is displayed in order
And safe Markdown response text is displayed incrementally
```

#### Scenario: Chat header exposes controls and repository state

```gherkin
Given an authenticated user has selected a Development Chat that requires repository setup
When the user views the chat header
Then a red repository icon offers setup and explains the required state on hover
And the rename control appears beside the chat title
And the Presence Mode dropdown appears beside Delete and shows the selected mode
When the user starts repository setup
Then the repository icon is yellow while setup is in progress
When the repository becomes ready
Then the repository icon is green and explains the ready state on hover
```

#### Scenario: User changes Presence Mode from the header

```gherkin
Given an authenticated user has selected a Development Chat
When the user chooses Continue in background from the header dropdown
Then the selected Presence Mode is persisted for that chat
And the dropdown shows Continue in background
```

#### Scenario: Header and Context remain accessible on a small screen

```gherkin
Given an authenticated user has selected a Development Chat on a small screen
When the user views the chat header
Then the title and controls wrap without hiding any chat action
And the user can open the Context panel from its mobile control
And the Context panel displays No additional context
```

#### Scenario: Agent activity retains its elapsed time

```gherkin
Given an authenticated user has a running Agent Turn
When the assistant response is displayed
Then the elapsed timer appears beside Agent activity
When the Agent Turn completes and the user reloads the chat
Then the final duration appears beside Agent activity on the completed assistant message
```