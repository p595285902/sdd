## Why

Some documented website startups need an API or other service, and the repository may already define those dependencies in Docker Compose.

## What Changes

- Use Compose only when the root README describes an existing Compose file in the selected checkout.
- Start the website and required API in a chat-unique private project; preserve non-Compose startup when no documented Compose file exists.
- Never generate Compose files or expose host resources and public ports.

## Capabilities

### New Capabilities

- `develop-preview-compose`: Optional documented multi-service previews per chat.

### Modified Capabilities

None.

## Impact

Trusted preview controller's Compose adapter and multi-chat lifecycle tests. Follows instruction resolution and isolated runtime.