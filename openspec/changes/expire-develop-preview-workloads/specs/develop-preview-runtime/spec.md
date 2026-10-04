# Develop preview runtime

## ADDED Requirements

### Requirement: Idle workloads stop without deleting chats
The system SHALL stop a Development Chat's preview workload after five minutes without visible Context activity, SHALL retain it while that user is using a visible Context panel, and MUST leave the chat itself available.

#### Scenario: Idle preview expires

```gherkin
Given a Development Chat has a running preview workload
When five minutes pass without visible Context activity
Then its preview workload is stopped
And its Development Chat remains available
```

#### Scenario: Visible use keeps a preview active

```gherkin
Given a Development Chat has a running preview workload
When the user continues to use its visible Context panel
Then the preview workload remains running
```

### Requirement: Restart and deletion affect only the selected chat
The system SHALL restart a chat's preview on request and MUST remove only that chat's workload when the Development Chat is deleted.

#### Scenario: Deleting one chat does not stop another preview

```gherkin
Given two Development Chats have running preview workloads
When the user deletes one Development Chat
Then only the deleted chat's preview workload is removed
```