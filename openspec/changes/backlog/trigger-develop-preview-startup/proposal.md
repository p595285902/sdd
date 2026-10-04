## Why

Resolved commands must start only for the correct checkout and at the right time; a successful chat message alone is not a reason to restart a healthy preview.

## What Changes

- Start the original checkout on first opening Context, and start a stopped preview after a completed Agent Turn changes non-ignored files.
- Keep healthy servers running for hot reload; expose not-configured, starting, ready, stopped and failed status.
- Default to the website when present, otherwise the API's Swagger page.

## Capabilities

### New Capabilities

- `develop-preview-startup`: Trigger chat-specific startup and select its initial page.

### Modified Capabilities

None.

## Impact

Develop turn completion integration, preview status/start endpoint and tests. Depends on file-change detection, classification, instruction resolution and runtime.