# Develop proposal workflow

Develop proposal workflow turns an exploration conversation into an explicitly approved or rejected workspace-local implementation.

## ADDED Requirements

### Requirement: Users control proposal execution
The system SHALL let a User generate a proposal from their canonical Development Chat, MUST require the User to approve or reject it, and SHALL apply an approved proposal only inside that chat's Development Workspace.

#### Scenario: User requests a proposal

```gherkin
Given an authenticated user has explored a ready Development Workspace
When the user selects Make it happen
Then the stored conversation is supplied to the agent proposal workflow
And the resulting undecided proposal is stored in the Development Chat
And Approve and Reject actions are displayed
```

#### Scenario: User approves a proposal

```gherkin
Given a Development Chat contains an undecided proposal
When its owner approves the proposal
Then one apply Agent Turn starts and reports its activity and response
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
