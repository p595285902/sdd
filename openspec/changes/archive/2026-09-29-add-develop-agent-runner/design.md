## Context

This change follows `add-develop-workspace-setup`. Ready workspaces exist, but no agent can explore them. Port the algorithms in AIDev `aidev/api/v1/services/agent.py` into target conventions without a runtime dependency on AIDev.

## Goals / Non-Goals

**Goals:**

- Execute exploration deterministically inside the owning workspace.
- Normalize OpenCode newline-delimited JSON and retain validated session continuity.
- Bound persisted activity and scrub secrets at every output boundary.
- Exercise the production runner and real OpenCode process in acceptance tests without external provider calls.

**Non-Goals:**

- Subscriber management, background turns, or weighted admission.
- SSE transport or frontend stream state.
- Proposal and apply prompts.

## Decisions

### Exercise the production runner through real OpenCode

Production uses process groups, concurrent stderr draining, bounded waits, and termination on cancellation or failure. Acceptance tests use that same runner to launch real OpenCode against a programmable local OpenAI-compatible fake LLM. A test-only control API scripts completions, tool calls, malformed streams, delays, disconnects, and provider failures without encoding control behavior in user prompts. Acceptance startup rejects any external provider endpoint.

A narrow fixture executable covers OS-level states that OpenCode cannot reliably produce, such as descendants that ignore graceful termination. It tests the production runner directly without adding a second application runner implementation.

Alternative considered: use an application-level fake runner. That is deterministic but bypasses OpenCode invocation, provider configuration, event emission, and the production process lifecycle in acceptance tests.

### Port event normalization rather than raw output

Parse newline-delimited JSON into a small normalized event model, ignore unknown event types, validate `ses_...` identifiers, and cap retained activity parts. Persist only normalized scrubbed data.

Alternative considered: expose raw OpenCode events. That couples persistence and clients to an external CLI format that can drift.

### Use one scrubber at every process-output boundary

Scrub repository token, configured repository value, provider key, and credential-bearing URLs before logging, raising, returning, or persisting output. Credentials enter child processes only through a minimal environment.

Alternative considered: log-only scrubbing. Errors and persisted tool output are also user-visible.

## Risks / Trade-offs

- [OpenCode event formats drift] -> Keep parsing isolated, ignore unknown events, and cover representative fixtures.
- [The fake LLM drifts from the OpenAI protocol] -> Cover captured protocol fixtures.
- [A child process survives cancellation] -> Start a process group and terminate the group with a bounded escalation path.
- [Activity grows without bound] -> Cap retained parts and content lengths through settings.

## Migration Plan

Add the production runner and process fixture, port normalization and scrubbing, add the programmable fake LLM and exploration service, then implement the acceptance scenarios. Rollback unregisters exploration and removes the test endpoint while leaving ready workspaces intact.

## Open Questions

None.
