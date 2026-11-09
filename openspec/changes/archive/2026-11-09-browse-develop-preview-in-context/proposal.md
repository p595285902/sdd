## Why

The Develop Context panel is currently a static empty state. Users need to interact with the selected chat's Compose-based checkout website or Swagger without leaving their conversation.

## What Changes

- Replace the static panel with an interactive browser showing the selected chat's Compose-based website, or Swagger for an API-only Compose checkout.
- Add address entry, Reload and Restart controls, with setup, loading, stopped and error states. Preview history and Back/Forward controls are not included.
- Allow external navigation from the preview; external destinations are visited directly by the browser, not proxied through the chat gateway.
- Keep user interaction in scope; agent browser automation and non-Compose preview support are not included.
- Apply the same live activity and response streaming behavior to Explore, Propose and Apply.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `develop-interface`: Context displays and controls a chat-scoped Compose preview instead of only the empty state; Explore, Propose and Apply share the same activity and response streaming checks.

## Impact

Develop frontend, proposal streaming integration, mobile Context access, browser integration and acceptance tests. Reuses Compose startup, browser authorization and registered localhost routing. No preview-history service, external-navigation containment or non-Compose restart changes are required. Expansion follows separately.
