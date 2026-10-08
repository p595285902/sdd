## Why

Users must browse website and Swagger pages from their chat's private services without exposing container ports or contacting arbitrary destinations.

## What Changes

- Map registered `localhost` ports to the selected chat's service through the authenticated preview origin.
- Forward assets, forms, redirects and interactive connections; reject external and unregistered destinations and cross-chat access.

## Capabilities

### New Capabilities

- `develop-preview-routing`: Route allowed chat-local pages and resources through the private browser gateway.

### Modified Capabilities

None.

## Impact

Gateway forwarding/port registry, URL policy and website/Swagger integration tests. Depends on browser authentication and preview startup.