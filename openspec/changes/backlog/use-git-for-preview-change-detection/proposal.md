## Why

Development Workspaces are Git checkouts, but preview-change detection currently walks and hashes the entire workspace before and after each Agent Turn. Use Git to identify checkout changes without treating an already-dirty checkout as a new change or waiting on arbitrary fixture delays.

## What Changes

- Replace filesystem snapshot-based preview-change detection with Git-based observation around each Agent Turn.
- Preserve detection of new files and repeated edits to already-dirty files, while excluding application-controlled paths regardless of checkout configuration.
- Treat Git observation failures or resource limits as unavailable rather than emitting a false preview-change event.
- Make acceptance tests synchronize on the observation boundary instead of relying on a ten-second fake agent response.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `develop-preview-detection`: Require Git-based detection of preview-relevant changes made during an Agent Turn, including changes to an already-dirty checkout.

## Impact

The Development Workspace preview-detection service, Agent Turn integration, and its backend and acceptance tests. No preview API response shape or production Git history is intended to change.