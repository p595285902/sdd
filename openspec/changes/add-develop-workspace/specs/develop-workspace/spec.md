# Develop workspace

Develop provides authenticated users with persistent AI-assisted development conversations backed by isolated checkouts of one configured repository.

## ADDED Requirements

### Requirement: Authenticated users can open Develop
The application SHALL display a Develop navigation item to every authenticated User and MUST deny Develop data and operations to unauthenticated clients.

#### Scenario: Authenticated user opens Develop

```gherkin
Given an authenticated user is viewing the application
When the user selects Develop from the navigation
Then the Develop workspace is displayed
```

#### Scenario: Unauthenticated client cannot access Develop data

```gherkin
Given an unauthenticated client
When the client requests Development Chats
Then the request is rejected as unauthorized
```

### Requirement: Development Chats are user-owned and persistent
The system SHALL let a User create, list, open, rename, and persist their Development Chats and messages, and MUST prevent access to another User's Development Chats.

#### Scenario: First message creates a Development Chat

```gherkin
Given an authenticated user has opened a new Development Chat
When the user submits a nonempty first message
Then a Development Chat is created for that user
And the first message is stored
And the configured repository setup action is offered
```

#### Scenario: Recent Development Chats are listed by activity

```gherkin
Given an authenticated user owns more Development Chats than the configured history limit
When the user opens Develop
Then only the configured number of most recently active Development Chats is listed
And the most recently active Development Chat appears first
```

#### Scenario: User renames a Development Chat

```gherkin
Given an authenticated user owns a Development Chat
When the user renames the Development Chat with a nonempty title
Then the new title is stored without changing the chat activity order
```

#### Scenario: User cannot access another user's Development Chat

```gherkin
Given two users own separate Development Chats
When one user requests the other user's Development Chat
Then the request is rejected without revealing the chat
```

#### Scenario: Older messages are loaded incrementally

```gherkin
Given a Development Chat contains more messages than one message page
When the user requests messages older than the oldest displayed message
Then the next older message page is returned in conversation order
```

### Requirement: Repository setup creates an isolated Development Workspace
The system SHALL set up the configured repository in a workspace dedicated to one Development Chat, SHALL initialize `opencode` and `openspec` there, and MUST keep credentials out of client-visible responses and process arguments.

#### Scenario: User sets up the configured repository

```gherkin
Given an authenticated user owns a Development Chat without a ready workspace
When the user selects Set up repository
Then the configured repository is cloned into that chat's isolated Development Workspace
And opencode and openspec are initialized in the Development Workspace
And an initial exploration uses the chat's first message
```

#### Scenario: Repository setup is unavailable when configuration is missing

```gherkin
Given the configured repository credentials are incomplete
When a user attempts to set up a repository
Then repository setup fails with a safe configuration error
And no credential value is returned
```

#### Scenario: Development Workspaces are isolated

```gherkin
Given two Development Chats have ready workspaces
When an Agent Turn runs for one Development Chat
Then the agent runs inside only that chat's Development Workspace
And the other Development Workspace is unchanged
```

### Requirement: Exploration streams durable Agent Turns
The system SHALL stream ordered activity and response events for an exploration Agent Turn, SHALL persist its user message, assistant response, bounded activity parts, and agent session, and MUST allow only one active Agent Turn per Development Chat.

#### Scenario: User explores a ready repository

```gherkin
Given an authenticated user owns a Development Chat with a ready workspace
When the user submits an exploration message
Then the user message is stored before the Agent Turn starts
And ordered agent activity and response text are streamed
And the completed assistant response is stored with the agent session
```

#### Scenario: User reattaches to an active Agent Turn

```gherkin
Given a Development Chat has an active Agent Turn
When its owner reopens the Development Chat
Then buffered Agent Turn events are replayed in order
And new events continue streaming until the turn completes
```

#### Scenario: Concurrent turn for one chat is rejected

```gherkin
Given a Development Chat has an active Agent Turn
When its owner starts another Agent Turn in the same chat
Then the second Agent Turn is rejected
And the active Agent Turn continues
```

#### Scenario: User explicitly stops an Agent Turn

```gherkin
Given a Development Chat has an active Agent Turn
When its owner selects Stop
Then the agent process for that Development Chat is terminated
And the interface no longer shows the turn as running
```

### Requirement: Users control proposal execution
The system SHALL let a User generate a proposal from their Development Chat, MUST require the User to approve or reject the proposal, and SHALL apply an approved proposal only inside that chat's Development Workspace.

#### Scenario: User requests a proposal

```gherkin
Given an authenticated user has explored a ready Development Workspace
When the user selects Make it happen
Then the conversation is supplied to the agent proposal workflow
And the resulting proposal is stored in the Development Chat
And Approve and Reject actions are displayed
```

#### Scenario: User approves a proposal

```gherkin
Given a Development Chat contains an undecided proposal
When its owner approves the proposal
Then an apply Agent Turn streams its activity and response
And changes are confined to that chat's Development Workspace
And no repository changes are published remotely
```

#### Scenario: User rejects a proposal

```gherkin
Given a Development Chat contains an undecided proposal
When its owner rejects the proposal
Then the proposal is marked rejected
And no apply Agent Turn starts
```

### Requirement: Presence Mode controls disconnected Agent Turns
Each Development Chat SHALL offer `Stop when I leave` and `Continue in background` Presence Modes, MUST default to `Stop when I leave`, and SHALL persist the selected mode for later Agent Turns.

#### Scenario: Stop when I leave cancels after the grace period

```gherkin
Given an active Agent Turn uses Stop when I leave
When no client remains attached for the configured grace period
Then the agent process is terminated
And an interruption message is stored in the Development Chat
```

#### Scenario: Reattachment within the grace period preserves the turn

```gherkin
Given an active Agent Turn uses Stop when I leave
When its owner reattaches before the configured grace period expires
Then the pending cancellation is withdrawn
And the Agent Turn continues
```

#### Scenario: Continue in background survives disconnection

```gherkin
Given an active Agent Turn uses Continue in background
When all clients disconnect
Then the Agent Turn continues to completion
And its completed response is stored
```

#### Scenario: Background turn limit is enforced per user

```gherkin
Given a user has reached the configured active background-turn limit
When the user starts another Continue in background Agent Turn
Then the new Agent Turn is rejected
```

### Requirement: Agent resources are bounded and failures are safe
The system MUST enforce configurable weighted concurrency, timeouts, history limits, message page size, and activity-part bounds, and MUST scrub configured secrets from all user-visible agent output and errors.

#### Scenario: Agent Turn waits for capacity

```gherkin
Given active Agent Turns consume the configured concurrency capacity
When another admissible Agent Turn is started
Then the user is informed that the turn is waiting for capacity
And the Agent Turn begins when sufficient capacity is available
```

#### Scenario: Agent Turn times out

```gherkin
Given an Agent Turn exceeds the configured timeout without producing a response
When the timeout expires
Then the agent process is terminated
And a safe timeout error is shown to the user
```

#### Scenario: Agent output contains a configured secret

```gherkin
Given agent output contains a configured repository or provider secret
When the output is logged, stored, or streamed
Then the complete secret value is not present
And a redacted value is used instead
```

### Requirement: Development Chat deletion is confirmed and complete
The system MUST require confirmation before permanently deleting a Development Chat and SHALL stop its active Agent Turn before deleting its messages, agent-session reference, and isolated Development Workspace.

#### Scenario: User cancels Development Chat deletion

```gherkin
Given an authenticated user has opened the delete confirmation for a Development Chat
When the user cancels deletion
Then the Development Chat and its Development Workspace remain available
```

#### Scenario: User confirms Development Chat deletion

```gherkin
Given an authenticated user owns a Development Chat with an active Agent Turn
When the user confirms permanent deletion
Then the active Agent Turn is stopped
And the Development Chat and all of its messages are deleted
And its isolated Development Workspace is deleted
```