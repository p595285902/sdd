# Develop chat

## ADDED Requirements

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