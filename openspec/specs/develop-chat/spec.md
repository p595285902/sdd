# Develop chat

## Purpose

Develop chat provides the authenticated, persistent conversation foundation used by later repository and agent capabilities.

## Requirements

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

### Requirement: Completed Agent Turn duration is persisted with its response
The system SHALL record the elapsed duration of each completed Agent Turn with its assistant message and MUST return that duration when its owner reloads or pages through the chat history. Messages that predate this capability SHALL remain readable without a duration.

#### Scenario: Completed turn duration survives reload

```gherkin
Given an authenticated user owns a Development Chat with an active Agent Turn
When the Agent Turn finishes and stores an assistant message
Then that message contains the completed turn duration
When the user requests that chat's messages again
Then the same duration is returned with the assistant message
```

#### Scenario: Older messages without duration remain readable

```gherkin
Given a Development Chat contains assistant messages from before turn duration was recorded
When its owner requests those messages
Then the messages are returned without a duration
```