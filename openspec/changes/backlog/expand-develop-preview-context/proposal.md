## Why

A narrow Context sidebar does not provide enough room to use many websites, and the idle timer must track actual visible use rather than background tabs.

## What Changes

- Let the user expand the preview without losing access to chat controls, on desktop and small screens.
- Send activity heartbeats only while Context and the browser tab are visible; preserve stable browser dimensions.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `develop-interface`: Add an expandable Context layout and visible-use activity tracking.

## Impact

Develop layout, viewport tests, activity heartbeat integration. Follows the interactive Context change after its delta is synced.