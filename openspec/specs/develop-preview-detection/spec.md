# Develop preview detection

## Purpose
Report preview-relevant file changes from completed Agent Turns while excluding application-controlled paths, so later preview orchestration can react to meaningful checkout edits.

## Requirements

### Requirement: Relevant Agent Turn changes are reported
The system SHALL compare workspace files before and after a completed Agent Turn and SHALL report a preview-relevant change only when that turn changed a file outside an application-controlled ignore list. The list MUST include `openspec/` and `.claude/` and MUST NOT be editable through the checkout.

#### Scenario: A relevant file changes

```gherkin
Given an Agent Turn starts in a ready Development Workspace
When the turn completes after creating or changing a website source file
Then a preview-relevant change is reported for that Development Chat
```

#### Scenario: An already dirty checkout changes again

```gherkin
Given a ready Development Workspace contains an existing uncommitted source edit
When an Agent Turn completes after changing that source file again
Then a preview-relevant change is reported for that Development Chat
```

#### Scenario: Only ignored files change

```gherkin
Given an Agent Turn starts in a ready Development Workspace
When the turn completes after changing only files under openspec and .claude
Then no preview-relevant change is reported for that Development Chat
```