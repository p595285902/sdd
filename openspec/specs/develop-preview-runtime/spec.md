# Develop preview runtime

## Purpose

Keep each Development Chat's preview workload isolated from backend credentials, host control, and other chats' checkouts while bounding its resource use.

## Requirements

### Requirement: Preview workloads are private to their Development Chat
The system SHALL run preview code in a bounded isolated workload owned by exactly one Development Chat. It MUST NOT give that workload backend secrets, a host control socket, public ports, privileged host access, or access to another chat's checkout.

#### Scenario: Two chats preview the same repository independently

```gherkin
Given two Development Chats have separate checkouts of the same repository
When a preview workload starts for each chat
Then each workload uses only its own chat's checkout
And neither workload can read the other chat's checkout
```

#### Scenario: Preview receives no host privileges

```gherkin
Given a Development Chat has a ready checkout
When its preview workload starts
Then the workload has resource limits and no backend credentials
And it has no host control socket or publicly published service port
```

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