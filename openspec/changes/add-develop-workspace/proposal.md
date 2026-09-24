## Why

Authenticated users currently have no in-application workflow for exploring a configured repository, turning a conversation into an implementation proposal, and applying an approved proposal in an isolated workspace. Adding Develop brings that existing AIDev workflow into this application while preserving user ownership, operational limits, and explicit approval before code execution.

## What Changes

- Add a Develop menu item and authenticated workspace for user-owned Development Chats.
- Let users create, rename, review, and permanently delete Development Chats and their isolated repository workspaces.
- Set up the configured repository for a chat, explore it through streamed Agent Turns, and retain conversation and agent-session continuity.
- Let users turn an exploration into a proposal, approve or reject it, and apply an approved proposal only inside the isolated Development Workspace.
- Support `Stop when I leave` and `Continue in background` presence policies, explicit cancellation, reattachment, concurrency limits, timeouts, and secret scrubbing.
- Add configurable repository, credential, model, workspace, timeout, history, and concurrency settings.

## Capabilities

### New Capabilities

- `develop-workspace`: Authenticated, user-owned AI development conversations and isolated repository workspaces, including exploration, proposal approval, streamed execution, presence behavior, lifecycle management, and resource controls.

### Modified Capabilities

None.

## Impact

- Frontend navigation, protected routing, Develop chat/history components, Markdown rendering, SSE consumption, and generated API client.
- FastAPI routes, SQLModel persistence, database migration, authorization dependencies, background turn management, subprocess lifecycle, and configuration.
- Runtime images and deployment configuration for `git`, `opencode`, `openspec`, workspace storage, repository credentials, and OpenAI credentials.
- Backend, frontend, and acceptance coverage for ownership, lifecycle, streaming, proposal decisions, cancellation, and resource limits.