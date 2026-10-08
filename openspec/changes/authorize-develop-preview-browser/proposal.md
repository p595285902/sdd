## Why

The app's local-storage bearer token cannot authenticate iframe assets and must not be exposed to untrusted checkout pages on the main application origin.

## What Changes

- Serve browser previews on a dedicated origin with short-lived, chat-bound credentials issued to an authorized user.
- Check ownership for every preview request and revoke access when a chat is deleted or a credential expires.
- Keep the application bearer token out of preview pages and URLs.

## Capabilities

### New Capabilities

- `develop-preview-browser-auth`: Authenticate an isolated-origin browser session for one chat's preview.

### Modified Capabilities

None.

## Impact

Preview gateway origin/configuration, credential exchange and ownership tests. Follows chat-scoped runtime; URL forwarding is a separate change.