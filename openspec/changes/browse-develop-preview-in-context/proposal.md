## Why

The Develop Context panel is currently a static empty state. Users need to interact with the selected chat's checkout website or Swagger without leaving their conversation.

## What Changes

- Replace the static panel with an interactive browser showing the selected chat's website, or Swagger for an API-only checkout.
- Add local URL entry, Back, Forward, Reload and Restart controls, with setup, loading and error states.
- Keep user interaction in scope; agent browser automation and external URLs are not supported.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `develop-interface`: Context displays and controls a chat-scoped preview instead of only the empty state.

## Impact

Develop frontend, mobile Context access, browser integration and acceptance tests. Depends on startup, browser auth and localhost routing; expansion follows separately.