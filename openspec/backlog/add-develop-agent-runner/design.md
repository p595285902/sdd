## Context

This change follows `add-develop-workspace-setup`. Ready workspaces exist, but no agent can explore them. Port the algorithms in AIDev `aidev/api/v1/services/agent.py` into target conventions without a runtime dependency on AIDev.

## Goals / Non-Goals

**Goals:**

- Execute exploration deterministically inside the owning workspace.
- Normalize OpenCode newline-delimited JSON and retain validated session continuity.
- Bound persisted activity and scrub secrets at every output boundary.
- Make production process behavior replaceable in tests.

**Non-Goals:**

- Subscriber management, background turns, or weighted admission.
- SSE transport or frontend stream state.
- Proposal and apply prompts.

## Decisions

### Put subprocess behavior behind a command-runner protocol

Production uses process groups, concurrent stderr draining, bounded waits, and termination on cancellation or failure. Tests use a deterministic fake with scripted events, blocking, failure, and cancellation hooks. Acceptance startup rejects accidental real-runner selection.

Alternative considered: patching `subprocess` directly in each test. That produces brittle tests and cannot model blocking lifecycle behavior consistently.

### Port event normalization rather than raw output

Parse newline-delimited JSON into a small normalized event model, ignore unknown event types, validate `ses_...` identifiers, and cap retained activity parts. Persist only normalized scrubbed data.

Alternative considered: expose raw OpenCode events. That couples persistence and clients to an external CLI format that can drift.

### Use one scrubber at every process-output boundary

Scrub repository token, configured repository value, provider key, and credential-bearing URLs before logging, raising, returning, or persisting output. Credentials enter child processes only through a minimal environment.

Alternative considered: log-only scrubbing. Errors and persisted tool output are also user-visible.

## Risks / Trade-offs

- [OpenCode event formats drift] -> Keep parsing isolated, ignore unknown events, and cover representative fixtures.
- [A child process survives cancellation] -> Start a process group and terminate the group with a bounded escalation path.
- [Activity grows without bound] -> Cap retained parts and content lengths through settings.

## Migration Plan

Add runner interfaces and fixtures, port normalization and scrubbing, add the exploration service and session fields, then implement the two scenarios. Rollback unregisters exploration while leaving ready workspaces intact.

## Open Questions

None.
