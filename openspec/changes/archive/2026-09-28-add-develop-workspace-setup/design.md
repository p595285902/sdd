## Context

This change follows `add-develop-chat-foundation`. Development Chats exist, but they have no repository checkout. The reference behavior lives in AIDev's Develop agent service; the target must port behavior without requiring the AIDev checkout at runtime.

## Goals / Non-Goals

**Goals:**

- Create one isolated checkout per chat under a configured root.
- Set up only the server-configured demo repository without accepting client-supplied repository URLs or credentials.
- Keep repository credentials out of arguments, persisted Git configuration, logs, and API payloads.
- Make setup retry and deletion safe and deterministic.

**Non-Goals:**

- Running exploration or retaining agent sessions.
- Coordinating active turns or streaming events.
- Connecting, selecting, or authenticating user-owned repositories. That remains a future feature.

## Decisions

### Derive and validate every workspace path

Resolve the configured root and target path, require the target to be a direct child named for the chat ID, and perform filesystem operations only after containment validation. Missing directories are successful cleanup. Database deletion proceeds only after workspace cleanup succeeds.

Alternative considered: shelling out to `rm -rf`. Validated `shutil.rmtree` is shell-independent and prevents traversal mistakes.

### Use environment-backed Git credentials

Clone a tokenless repository URL and provide credentials through the process environment and a temporary credential helper. Never place credentials in command arguments or repository configuration. Return only scrubbed setup errors.

Alternative considered: embedding the token in the clone URL. Process listings and Git metadata could expose it.

### Use one server-configured demo repository source

Expose one setup action for the demo repository and resolve it only from `DEMO_GITHUB_REPO` and `DEMO_GITHUB_TOKEN`. The action calls the credential-safe workspace service and accepts no repository configuration from the client.

Alternative considered: retaining a configured user-repository action or accepting client-provided values. Deferring user-repository connection keeps authentication and repository selection outside the current contract.

### Recreate partial setup on retry

A setup retry removes a validated partial chat directory and starts clean before cloning, `opencode init`, and `openspec init --tools opencode`. A deterministic setup runner replaces real commands in tests.

Alternative considered: resume partial setup. Tool-specific intermediate state makes correctness difficult to prove.

## Risks / Trade-offs

- [Local workspaces consume disk] -> Delete them with chats; quotas and retention remain future work.
- [Cleanup can fail after confirmation] -> Keep database state intact and return a retryable safe error.
- [Repository setup depends on external tools] -> Isolate invocation behind a runner and use deterministic tests.

## Migration Plan

Add demo workspace settings and service, extend confirmed chat deletion, add the demo setup endpoint and control, then implement the scenarios. Remove the superseded configured-repository settings, endpoint behavior, and control. Rollback disables setup and deletion routes before removing workspace configuration; existing directories remain recoverable.

## Open Questions

None.
