## Context

The admin Users table currently supports deleting one user at a time via
`DELETE /users/{user_id}` (see [backend/app/api/routes/users.py](backend/app/api/routes/users.py))
and the `DeleteUser` dropdown item component (see
[frontend/src/components/Admin/DeleteUser.tsx](frontend/src/components/Admin/DeleteUser.tsx)).
That endpoint already forbids a superuser from deleting their own account and
cascades deletion to the user's `Item` rows.

This change adds a second, parallel workflow: selecting several rows and
deleting them together. It touches the admin route (selection state, a new
button, a confirmation dialog), the generated API client, and a new backend
endpoint. The single-user delete flow is unaffected and stays as-is.

## Goals / Non-Goals

**Goals:**
- Let a superuser select multiple users on the current table page and delete
  them in one confirmed action.
- Guarantee the bulk operation is all-or-nothing: any invalid ID or an
  attempt to include the requester's own ID aborts the whole request with no
  partial deletion.
- Reuse the existing cascade-delete-Items behavior per targeted user.
- Keep the existing single-user delete path unchanged.

**Non-Goals:**
- Cross-page selection (select-all is scoped to the loaded page only).
- Bulk operations other than delete (e.g. bulk role change).
- Changing authorization rules beyond what the single-delete endpoint
  already enforces (superuser-only, no self-delete).

## Decisions

### One new atomic endpoint: `POST /users/bulk-delete`
A `POST` request with a JSON body of user IDs is used instead of `DELETE`
with a body (many HTTP clients and some proxies mishandle bodies on
`DELETE`) or N repeated calls to the existing per-ID `DELETE /users/{id}`.
Repeated calls cannot give atomicity — a failure partway through would
leave some users deleted and others not, contradicting the proposal's
all-or-nothing requirement. Request body:
```json
{ "user_ids": ["<uuid>", "<uuid>", ...] }
```
Response reuses the existing `Message` model on success (`204`/`200` with a
confirmation message, consistent with `delete_user`'s response shape).

### Validate before mutating, inside a single transaction
The handler loads all targeted users with one `SELECT ... WHERE id IN
(...)` query. If any requested ID is missing from the result, or the
current superuser's ID is present in the request, the handler raises an
`HTTPException` (`404` for missing users, `403` for self-inclusion) before
issuing any `DELETE`. Only after validation passes does it delete the
`Item` rows owned by the targets and then the `User` rows, mirroring
`delete_user`'s per-user sequence, and commit once. This preserves
atomicity without needing a savepoint per user: nothing is written until
every ID is confirmed valid.

### Frontend selection state lives in the Users table component
Selected IDs are tracked as component state (a `Set<string>` of user IDs)
scoped to the admin Users page, reset when the page of results changes so
"select all" never silently carries over stale selections from a
different page. The current user's ID is excluded from "select all" and
its row checkbox is rendered disabled, mirroring the backend's rejection
of self-inclusion so the UI can't produce a request the backend would
reject anyway.

### Confirmation dialog reuses the `DeleteUser` dialog pattern
A new `BulkDeleteUsers` component follows the existing `DeleteUser.tsx`
structure (dialog + `useMutation` + `LoadingButton` + toast on
success/error) but takes the selected ID list and shows the count instead
of a single username. This keeps the two flows visually and behaviorally
consistent rather than introducing a different interaction pattern for a
very similar action.

### API client regeneration
The new endpoint requires regenerating the OpenAPI-derived frontend client
(`frontend/src/client`) via the project's existing `generate-client.sh`
script, adding a `bulkDeleteUsers` service method and its request/response
types. No manual hand-editing of generated files.

## Risks / Trade-offs

- [Large selections increase the `IN (...)` query and transaction size] →
  Acceptable given admin table pages are bounded (existing pagination
  limits page size), so the number of IDs per request is naturally capped.
- [Race condition: a targeted user is deleted or changed by another admin
  between page load and confirmation] → The endpoint re-validates existence
  at request time (not relying on stale frontend state), so such a request
  fails closed with a 404 and deletes nothing.
- [Frontend and backend both encode "no self-delete"] → Minor duplication,
  but the backend check is the authoritative guard; the frontend check is
  only a UX convenience and must not be relied on for correctness.
