## Context

This change follows `add-develop-interface`. Users can explore a ready workspace but cannot turn the conversation into an explicitly approved implementation. A proposal is a persisted assistant message with one atomic decision.

## Goals / Non-Goals

**Goals:**

- Generate a proposal from the canonical stored conversation.
- Require one irreversible approve or reject decision.
- Run approved apply work only inside the owning workspace.
- Expose proposal state and controls in Develop.

**Non-Goals:**

- Publishing changes, pushing branches, or creating pull requests.
- Editing generated proposal text in the application.
- Reversing a recorded decision.

## Decisions

### Summarize canonical server-side history

Build the propose prompt from persisted conversation rather than client payloads, then invoke `/openspec propose` through the agent service. Store the result with proposal kind and no decision.

Alternative considered: trust client-supplied history. It can omit or alter canonical context.

### Decide atomically before apply

Approve uses a conditional update from undecided to approved and starts exactly one weighted apply turn. Reject conditionally records rejected and starts nothing. Repeated or conflicting decisions fail even when UI controls are disabled.

Alternative considered: client-only decision state. Direct API calls could apply rejected or already-decided proposals.

### Confine apply to the Development Workspace

Invoke `/openspec apply` with the workspace as both working directory and explicit directory boundary. Do not configure remote publication credentials or commands.

## Risks / Trade-offs

- [Two approval requests race] -> Use one atomic state transition and start only after it succeeds.
- [Conversation exceeds prompt limits] -> Use bounded canonical summarization from the agent service.
- [Apply modifies unexpected local files] -> Constrain process directory; stronger OS sandboxing remains future work.

## Migration Plan

Add proposal state migration and models, propose/decision endpoints, agent operations, controls, and tests, then implement the three scenarios. Rollback hides controls and rejects new decisions while retaining historical proposal messages.

## Open Questions

None.
