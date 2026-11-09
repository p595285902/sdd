# Develop interface

## Purpose

Developers need one responsive workspace to manage exploration conversations, configure repositories, and follow or control live Agent Turns without leaving the application.

## Requirements

### Requirement: Develop presents and controls streamed exploration
The application SHALL provide an authenticated responsive workspace for chat history, conversation, context, repository setup, safe Markdown, incremental Agent Turn activity, reattachment, Stop, and Presence Mode controls. The selected chat's header MUST contain the repository setup/status control, a rename control beside the title, and a Presence Mode dropdown beside Delete. The Context panel and its mobile entry point SHALL remain available and SHALL show the selected chat's interactive Compose-based website or Swagger preview when ready, with meaningful setup, loading, stopped, and error states otherwise. Explore, Propose and Apply SHALL share the same incremental activity and response streaming behavior: ordered expandable activity and safe Markdown response updates MUST be visible while the Agent Turn is running, and the complete response and expandable activity MUST remain available after completion. Agent activity SHALL show elapsed time while a turn runs and its final duration when a completed assistant message is displayed.

Context SHALL provide address entry, Reload and Restart for Compose-based previews. It SHALL NOT provide preview history or Back/Forward controls. Registered localhost addresses entered in Context MUST route to the selected chat's preview. External navigation from the preview SHALL be permitted and SHALL use the browser directly rather than proxying external destinations through the chat gateway. Non-Compose preview integration and non-Compose restart fixes are outside this change's scope.

#### Scenario: Streamed exploration is displayed

```gherkin
Given an authenticated user starts the Explore workflow in a ready Development Workspace
When normalized Agent Turn events arrive
Then expandable activity is displayed in order
And safe Markdown response text is displayed incrementally
And partial response text is visible while the Agent Turn is still running
When the Agent Turn completes
Then the complete assistant response is displayed once
And its activity remains expandable
```

#### Scenario Outline: Propose and Apply share the same streaming checks as Explore

```gherkin
Given an authenticated user starts the <workflow> workflow in a ready Development Workspace
When normalized Agent Turn events arrive
Then expandable activity is displayed in order
And safe Markdown response text is displayed incrementally
And partial response text is visible while the Agent Turn is still running
When the Agent Turn completes
Then the complete assistant response is displayed once
And its activity remains expandable

Examples:
| workflow |
| Propose  |
| Apply    |
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
And the Context panel shows that chat's preview or current status
```

#### Scenario: Agent activity retains its elapsed time

```gherkin
Given an authenticated user has a running Agent Turn
When the assistant response is displayed
Then the elapsed timer appears beside Agent activity
When the Agent Turn completes and the user reloads the chat
Then the final duration appears beside Agent activity on the completed assistant message
```

#### Scenario: User interacts with a chat-local website

```gherkin
Given an authenticated user has selected a Development Chat with a ready Compose website preview
When the user opens Context
Then the website can be used inside Context
And the browser shows its localhost address
And the preview toolbar offers address entry, Reload and Restart
When the user enters a registered localhost path in the URL bar
Then that path loads from the selected chat's preview
```

#### Scenario: User opens Swagger inside Context

```gherkin
Given an authenticated user has selected a Development Chat with a ready Compose API preview
When the user enters its localhost Swagger address in Context
Then Swagger loads inside Context
```

#### Scenario: User restarts the Compose preview

```gherkin
Given an authenticated user has selected a Development Chat with a ready Compose website preview
When the user selects Restart preview
Then Context shows startup progress until that chat's preview is ready
And the website can be used inside Context
```

#### Scenario: Context does not show another chat's page

```gherkin
Given an authenticated user has selected a Development Chat without a ready Compose preview
When the user opens Context
Then Context shows that chat's setup or failure status
And another chat's preview is not displayed
```

### Requirement: Preview space adapts to the user's task
The application SHALL let the user expand the selected Development Chat's browser preview on desktop and mobile without hiding essential conversation controls or overlapping the page, and SHALL keep the embedded viewport stable during navigation.

#### Scenario: User expands the website preview

```gherkin
Given an authenticated user has selected a Development Chat with a ready website preview
When the user expands Context
Then the website has a wider interactive viewport
And the conversation controls remain accessible
```

### Requirement: Preview activity reflects visible use
The application SHALL report preview activity only while the selected chat's Context panel and browser tab are visible, and MUST stop reporting activity when the panel closes, the tab hides or the selected chat changes.

#### Scenario: Hidden Context does not keep a preview alive

```gherkin
Given a Development Chat has a running preview in a visible Context panel
When the user hides Context or switches browser tabs
Then Context stops reporting preview activity for that chat
```
