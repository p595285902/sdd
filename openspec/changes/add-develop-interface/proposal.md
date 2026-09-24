## Why

The chat, workspace, and streaming contracts need a complete native interface for users to manage conversations and observe Agent Turns. This change follows `add-develop-streaming-api` and limits itself to the exploration experience.

## What Changes

- Replace the minimal Develop shell with a responsive shadcn/TanStack workspace.
- Add recent-chat selection, creation, inline rename, confirmed deletion, and incremental history loading.
- Add safe Markdown rendering, bearer-authenticated SSE parsing, optimistic messages, reattachment, pinned scrolling, elapsed time, and expandable activity.
- Add repository setup, Stop, and Presence Mode controls.
- Maintain a bounded five-chat client cache and responsive history/context controls.

## Capabilities

### New Capabilities

- `develop-interface`: Native responsive Develop exploration UI, chat history interactions, stream rendering, reattachment, and workspace controls.

### Modified Capabilities

None.

## Impact

- React components, route, API adapter, Markdown dependency, responsive styling, and Playwright coverage.
- This change excludes proposal generation and apply controls.
- Requires `add-develop-streaming-api` to be implemented first.
