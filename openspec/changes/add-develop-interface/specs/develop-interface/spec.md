# Develop interface

Develop interface provides the complete responsive exploration experience over Development Chat, Workspace, and Agent Turn APIs.

## ADDED Requirements

### Requirement: Develop presents and controls streamed exploration
The application SHALL provide an authenticated responsive workspace for chat history, conversation, context, repository setup, safe Markdown, incremental Agent Turn activity, reattachment, Stop, and Presence Mode controls.

#### Scenario: Streamed exploration is displayed

```gherkin
Given an authenticated user starts exploration in a ready Development Workspace
When normalized Agent Turn events arrive
Then expandable activity is displayed in order
And safe Markdown response text is displayed incrementally
```
