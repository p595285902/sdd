## Context

This change follows `add-develop-chat-foundation`. Development Chats exist, but they have no repository checkout. The reference behavior lives in AIDev's Develop agent service; the target must port behavior without requiring the AIDev checkout at runtime.

## Goals / Non-Goals

**Goals:**

- Create one isolated checkout per chat under a configured root.
- Keep repository credentials out of arguments, persisted Git configuration, logs, and API payloads.
- Make setup retry and deletion safe and deterministic.

**Non-Goals:**

- Running exploration or retaining agent sessions.
- Coordinating active turns or streaming events.
- Selecting repositories or credentials per user.

## Decisions

### Derive and validate every workspace path

Resolve the configured root and target path, require the target to be a direct child named for the chat ID, and perform filesystem operations only after containment validation. Missing directories are successful cleanup. Database deletion proceeds only after workspace cleanup succeeds.

Alternative considered: shelling out to `rm -rf`. Validated `shutil.rmtree` is shell-independent and prevents traversal mistakes.

### Use environment-backed Git credentials

Clone a tokenless repository URL and provide credentials through the process environment and a temporary credential helper. Never place credentials in command arguments or repository configuration. Return only scrubbed setup errors.

Alternative considered: embedding the token in the clone URL. Process listings and Git metadata could expose it.

### Recreate partial setup on retry

A setup retry removes a validated partial chat directory and starts clean before cloning, `opencode init`, and `openspec init --tools opencode`. A deterministic setup runner replaces real commands in tests.

Alternative considered: resume partial setup. Tool-specific intermediate state makes correctness difficult to prove.

## Risks / Trade-offs

- [Local workspaces consume disk] -> Delete them with chats; quotas and retention remain future work.
- [Cleanup can fail after confirmation] -> Keep database state intact and return a retryable safe error.
- [Repository setup depends on external tools] -> Isolate invocation behind a runner and use deterministic tests.

## Migration Plan

Add workspace settings and service, extend confirmed chat deletion, add setup endpoints and controls, then implement the five scenarios. Rollback disables setup and deletion routes before removing workspace configuration; existing directories remain recoverable.

## Open Questions

None.
