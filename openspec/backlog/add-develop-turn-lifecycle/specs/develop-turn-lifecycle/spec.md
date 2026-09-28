# Develop turn lifecycle

Develop turn lifecycle coordinates active agent operations, subscribers, presence policy, and bounded capacity in one backend process.

## ADDED Requirements

### Requirement: Agent Turns support exclusive execution and explicit stop
The system MUST allow only one active Agent Turn per Development Chat and SHALL let its owner stop that turn explicitly.

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
When its owner stops the Agent Turn
Then the agent process for that Development Chat is terminated
And the Agent Turn is no longer running
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

### Requirement: Agent Turn resources are bounded
The system MUST enforce weighted concurrency and turn timeouts.

#### Scenario: Agent Turn waits for capacity

```gherkin
Given active Agent Turns consume the configured concurrency capacity
When another admissible Agent Turn is started
Then the Agent Turn reports that it is waiting for capacity
And the Agent Turn begins when sufficient capacity is available
```

#### Scenario: Agent Turn times out

```gherkin
Given an Agent Turn exceeds the configured timeout without producing a response
When the timeout expires
Then the agent process is terminated
And a safe timeout error is recorded
```
