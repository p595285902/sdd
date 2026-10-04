## Context

Classification describes likely content, while the private runtime can start a chat workload. Neither knows a repository's install, start commands or ports.

## Goals / Non-Goals

**Goals:** Produce bounded chat-specific startup instructions or a request for user input.

**Non-Goals:** Guess commands, require another approval, or parse/execute Compose (later change).

## Decisions

- Supply the root README and classifier result to a bounded agent selection step. Return structured commands, working directory, local ports and optional initial paths. Resolve user-provided pointers only within the validated checkout and retain their choice per chat.
- When no usable instructions exist, ask in chat and wait; a reply containing commands or a document pointer completes resolution without a file-changing turn. Execute only in the isolated workload, with startup time/port limits and redacted failures.

## Risks / Trade-offs

- The no-approval choice trusts README content and agent selection; workload isolation is a prerequisite, not optional hardening.