## Context

The admin page currently renders users through the shared DataTable and supports single-user edit/delete actions. The backend exposes a superuser-only single-user delete endpoint that removes owned Items before deleting the User, but it has no batch operation. The change crosses the React admin table, generated API client, FastAPI users route, and acceptance coverage.

## Goals / Non-Goals

**Goals:**

- Add visible row selection and current-page select-all behavior.
- Preserve the current-user deletion invariant in both UI and backend validation.
- Add a dedicated, transactional bulk-delete endpoint with all-or-nothing semantics.
- Reuse the existing cascade behavior for owned Items.
- Keep the destructive action discoverable but disabled without a selection.

**Non-Goals:**

- Generic bulk-action infrastructure for future actions.
- Cross-page selection or selection persistence between pages.
- Bulk activation, deactivation, editing, or role changes.
- Changes to self-deletion through the existing `/users/me` endpoint.

## Decisions

1. **Use the table's row-selection state.** Add a checkbox column and select-all checkbox through the existing table abstraction, keeping selection tied to the current page. The current user's checkbox is disabled and excluded from selection.

2. **Add a dedicated bulk endpoint.** Introduce a superuser-only endpoint accepting a list of user UUIDs, likely under `/users/bulk-delete`. The backend validates the full target set before mutating data, then deletes owned Items and Users inside one transaction. A single request is preferred over N frontend calls because it gives the backend one place to enforce authorization and atomicity.

3. **Use the existing destructive confirmation pattern.** The bulk dialog displays the selected count and the existing Item-deletion warning. Cancel performs no request; confirmation calls the generated bulk service method and invalidates the relevant queries after success.

4. **Regenerate the API client.** Update the OpenAPI-generated client through the repository's existing generation script after the backend contract is finalized rather than maintaining handwritten client types.

## Risks / Trade-offs

- [A stale selection can reference a user deleted elsewhere] -> Validate every ID before mutation and roll back the entire transaction on failure.
- [A large selection may produce a large request] -> Keep the initial scope to the current page; the page size bounds the request.
- [Generated client output can drift from the API] -> Regenerate and run frontend type checking as part of implementation.
- [The shared DataTable may not expose row selection yet] -> Extend its existing table options minimally and cover the admin path with focused tests.

## Migration Plan

No database migration is expected. Deploy the backend endpoint and frontend together after regenerating the client. Roll back by removing the UI action and endpoint; existing single-user deletion remains available.

## Open Questions

- Confirm the exact acceptance-test stack in `openspec/config.yaml` before scaffolding or changing acceptance infrastructure; the current file does not declare `stack:`.
