## Why

Checked-out application code must not run inside the authenticated backend or share a process with another chat's preview.

## What Changes

- Add a trusted controller boundary for starting and inspecting one isolated, resource-bounded preview workload per Development Chat.
- Mount only the selected checkout, without app credentials, Docker control sockets, host ports, or another chat's files.
- Defer idle/restart/deletion lifecycle and README startup selection to later changes.

## Capabilities

### New Capabilities

- `develop-preview-runtime`: Isolated chat-owned preview workload startup and status.

### Modified Capabilities

None.

## Impact

Preview controller/deployment boundary, backend runtime adapter and two-chat isolation tests. Follows checkout classification.