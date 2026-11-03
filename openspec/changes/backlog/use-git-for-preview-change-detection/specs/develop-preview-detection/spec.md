# Develop preview detection

## MODIFIED Requirements

### Requirement: Relevant Agent Turn changes are reported
The system SHALL use Git commands in the Development Workspace to observe preview-relevant checkout state before and after a completed Agent Turn, and SHALL report a preview-relevant change only when that turn changed a relevant file. It MUST detect changes to tracked and untracked files, including a further change to a file already dirty before the turn. Git ignore rules MUST NOT conceal a preview-relevant file from detection. The application-controlled ignore list MUST include `openspec/` and `.claude/` and MUST NOT be editable through the checkout. If Git observation fails or exceeds its resource limits, the system MUST NOT report a change based on incomplete evidence.

#### Scenario: A relevant file changes

```gherkin
Given an Agent Turn has recorded its initial Git state in a ready Development Workspace
When the turn completes after creating or changing a website source file
Then a preview-relevant change is reported for that Development Chat
```

#### Scenario: An already dirty checkout changes again

```gherkin
Given a ready Development Workspace has a dirty checkout and an Agent Turn with its initial Git state recorded
When an Agent Turn completes after changing that source file again
Then a preview-relevant change is reported for that Development Chat
```

#### Scenario: Only ignored files change

```gherkin
Given an Agent Turn has recorded its initial Git state in a ready Development Workspace
When the turn completes after changing only files under openspec and .claude
Then no preview-relevant change is reported for that Development Chat
```

#### Scenario: An untracked file changes again

```gherkin
Given a Development Workspace has an untracked website source file and an Agent Turn with its initial Git state recorded
When the turn completes after editing that untracked file again
Then a preview-relevant change is reported for that Development Chat
```

#### Scenario: A checkout-ignored source file changes

```gherkin
Given a Development Workspace ignores a website source file through its Git configuration
And an Agent Turn has recorded its initial Git state
When the turn completes after changing that website source file
Then a preview-relevant change is reported for that Development Chat
```

#### Scenario: Git observation is unavailable

```gherkin
Given an Agent Turn has recorded its initial Git state in a ready Development Workspace
When the turn completes after Git observation becomes unavailable
Then no preview-relevant change is reported for that Development Chat
```