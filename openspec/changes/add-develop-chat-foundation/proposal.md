## Why

Authenticated users need a durable, ownership-scoped conversation foundation before repository setup, agent execution, or streaming behavior can be added safely. Delivering chat persistence first creates a small independently testable base for the later Develop changes.

## What Changes

- Add authenticated creation, listing, opening, renaming, and persistence of Development Chats.
- Persist Development Messages and expose cursor-based incremental message history.
- Enforce User ownership at every chat and message query boundary.
- Add the minimal authenticated Develop route and navigation entry needed to exercise chat lifecycle behavior.
- Add the agreed Development Chat and Development Message terminology to the domain context.
- Sequence later work as `add-develop-workspace-setup`, `add-develop-agent-runner`, `add-develop-turn-lifecycle`, `add-develop-streaming-api`, `add-develop-interface`, `add-develop-proposal-workflow`, and `deploy-develop-runtime`, activating each only after its predecessor is implemented and archived.

## Capabilities

### New Capabilities

- `develop-chat`: Authenticated, user-owned persistent development conversations, recent-chat ordering, renaming, and incremental message history.

### Modified Capabilities

None.

## Impact

- FastAPI/SQLModel models, migrations, ownership-scoped JSON endpoints, and tests.
- Generated frontend API client.
- Authenticated navigation, a minimal Develop chat shell, and focused frontend and acceptance coverage.
- This change intentionally excludes repository workspaces, agent processes, SSE, presence behavior, proposals, and deployment changes.
