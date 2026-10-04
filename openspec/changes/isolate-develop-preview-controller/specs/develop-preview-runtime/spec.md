# Develop preview runtime

## ADDED Requirements

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