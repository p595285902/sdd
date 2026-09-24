## Why

Development Chats need isolated checkouts of the configured repository before an agent can inspect or modify code. This change follows `add-develop-chat-foundation` and delivers workspace lifecycle independently from agent execution.

## What Changes

- Set up one isolated Development Workspace per Development Chat from the configured repository.
- Initialize `opencode` and `openspec` in each workspace through a replaceable command runner boundary.
- Keep repository credentials out of client responses and process arguments.
- Support safe setup retry and validated workspace deletion.
- Permanently delete a confirmed chat only after its workspace is safely removed.

## Capabilities

### New Capabilities

- `develop-workspace`: Configured-repository setup, isolated per-chat workspaces, safe cleanup, and confirmed chat deletion.

### Modified Capabilities

None.

## Impact

- Develop configuration, workspace service, command-runner boundary, chat deletion API, setup/deletion controls, and tests.
- Requires `add-develop-chat-foundation` to be implemented first.
