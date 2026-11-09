# Develop interface

## ADDED Requirements

### Requirement: Context launches previews only through an explicit control
The Context header SHALL provide Launch beside Expand for the selected Development Chat on supported desktop and mobile layouts without changing the existing side-by-side conversation/Context behavior. Opening or expanding Context SHALL display existing status without launching a project. Launch SHALL begin the documented workflow immediately without a separate approval dialog when the selected checkout is ready, SHALL expose a meaningful pending state, and SHALL prevent duplicate launches while a preview is starting or running. Existing explicit Reload and Restart controls and visible-Context activity reporting SHALL remain available with their existing semantics. Only the main application SHALL be embedded; no supporting-tool picker or Mailpit/Adminer links SHALL be added.

#### Scenario: Launch appears next to Expand without starting the project

```gherkin
Given an authenticated user has selected a Development Chat with a ready checkout and stopped preview
When the user opens Context
Then Launch is available beside Expand
And opening Context does not execute startup commands
And the conversation remains accessible alongside Context on desktop
```

#### Scenario: Launch runs without another approval step

```gherkin
Given the selected chat has a ready checkout and resolvable Docker startup instructions
When the user clicks Launch
Then that chat's startup begins without an approval dialog
And Launch indicates progress without allowing another concurrent launch
And startup output appears in the conversation while Context remains available
```

#### Scenario: Launch remains accessible on a small screen

```gherkin
Given an authenticated user has selected a Development Chat on a small screen
When the user opens Context through its mobile control
Then Launch and Expand remain accessible without horizontal page overflow
And launching the application does not remove access to the conversation
```

#### Scenario: Context displays only the application

```gherkin
Given a Development Chat's documented Compose workflow starts an application, a mail tool and a database administration tool
When the application becomes ready
Then Context embeds the application
And Context does not list or link the supporting tools
```

### Requirement: Preview execution output remains visible in the conversation
The conversation SHALL display each preview execution as a persistent expandable operation entry, separate from ordinary user/assistant Development Messages and Agent Turn activity. It SHALL show documented commands, ordered live stdout/stderr, progress and terminal status without requiring Context to close or an Agent Turn to run. Refreshing or revisiting the chat SHALL restore persisted output and reattach to an active execution without duplicate entries or commands. Output SHALL be rendered as safe text with known secrets masked before delivery; explicit truncation markers SHALL disclose configured retention limits rather than silently dropping output.

#### Scenario: Live startup output appears alongside Context

```gherkin
Given a Development Chat has a launching Compose preview
When a command emits stdout and stderr before the application becomes ready
Then its command and both output streams appear incrementally in that chat's execution entry
And the output is not presented as an assistant reply or Agent Turn
And Context and the conversation remain usable side by side on desktop
```

#### Scenario: Refresh restores the same execution output

```gherkin
Given a Development Chat has an active preview execution with persisted output
When the user refreshes and reopens that chat
Then the same execution entry and output are restored
And new output attaches to that entry without duplicated events or another launch
```

#### Scenario: Failure remains understandable after cleanup

```gherkin
Given a Development Chat's initialization command failed and its sandbox was removed
When the user revisits the chat
Then the failed command, redacted diagnostic and exit status remain visible
And the interface does not launch a replacement preview automatically
```
