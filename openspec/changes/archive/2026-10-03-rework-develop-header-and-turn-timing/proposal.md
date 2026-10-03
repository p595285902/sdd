## Why

The Develop chat header separates essential chat controls from repository and presence information in the Context panel, making routine actions harder to find. Turn timing currently disappears when a streamed reply becomes a persisted message, so developers cannot review how long completed turns took.

## What Changes

- Move repository status and setup into the chat header as a green ready, yellow setting-up, or red setup-required icon with an explanatory hover tooltip.
- Place the rename control beside the chat title and a persistent Presence Mode dropdown beside Delete; wrap the header controls on small screens.
- Keep the Context panel and its mobile access, with a "No additional context" empty state after moving its existing controls.
- Display the running timer beside "Agent activity" in the assistant response and persist each completed Agent Turn's elapsed time so its final duration remains visible after reload.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `develop-interface`: Define the chat-header layout, repository status feedback, Context empty state, Presence Mode control, and live/completed activity timing.
- `develop-chat`: Persist and return a completed Agent Turn's duration with its assistant message.

## Impact

- Develop React workspace, responsive header, repository setup state, and message activity rendering.
- Development Message storage, API response schema, generated TypeScript client, and database migration for completed turn duration.
- Focused frontend, backend, and executable acceptance coverage for header controls and persisted timing.