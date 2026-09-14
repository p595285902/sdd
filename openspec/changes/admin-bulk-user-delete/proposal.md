## Why

Superusers can currently delete only one user at a time from the admin page. Managing several obsolete accounts requires repeated destructive flows and provides no way to select visible users for a coordinated action. This change adds a clear, atomic bulk-delete workflow while preserving the existing protection against deleting the current superuser.

## What Changes

- Add a checkbox to each user row in the admin Users table.
- Disable selection for the current user's row.
- Add a `Delete User(s)` button next to `Add User`, always visible and disabled when no user is selected.
- Limit select-all behavior to the currently visible table page.
- Confirm bulk deletion with the number of selected users and the existing warning that their Items are also permanently deleted.
- Add a dedicated atomic backend bulk-delete endpoint for selected user IDs.
- Reject the entire bulk operation when any target is invalid or includes the current user; delete nothing in that case.
- Preserve cascading deletion of Items owned by deleted users.

## Capabilities

### New Capabilities

- `admin-bulk-user-delete`: Select and atomically delete multiple users from the admin page.

### Modified Capabilities

- None.

## Impact

- Frontend admin route, user table columns/selection state, and bulk confirmation UI.
- Generated frontend API client types and service methods.
- FastAPI users route, request/response models, authorization, validation, and transaction handling.
- Backend and frontend unit/acceptance tests for selection, permissions, confirmation, success, and rollback behavior.
- No database migration is expected; the operation reuses existing user and Item deletion relationships.
