## Context

The admin Users page ([frontend/src/routes/_layout/admin.tsx](frontend/src/routes/_layout/admin.tsx)) loads users once (`skip: 0, limit: 100`) and renders them through the shared TanStack-Table wrapper [frontend/src/components/Common/DataTable.tsx](frontend/src/components/Common/DataTable.tsx), which owns client-side pagination via `getPaginationRowModel()` and currently exposes no row-selection state. Per-row actions live in a dropdown ([frontend/src/components/Admin/UserActionsMenu.tsx](frontend/src/components/Admin/UserActionsMenu.tsx)); single-user deletion is [frontend/src/components/Admin/DeleteUser.tsx](frontend/src/components/Admin/DeleteUser.tsx), a `Dialog` with a `LoadingButton`, `useCustomToast` notifications, `handleError`, and `queryClient.invalidateQueries()` on settle.

The backend has no batch operation. `delete_user` in [backend/app/api/routes/users.py](backend/app/api/routes/users.py) is guarded by `get_current_active_superuser`, 404s on an unknown id, 403s when the target is `current_user`, deletes the owned `Item` rows with a bulk `delete(Item).where(col(Item.owner_id) == user_id)` statement, then deletes the `User` and commits — one implicit transaction per request.

The frontend client is generated from the OpenAPI schema by [scripts/generate-client.sh](scripts/generate-client.sh), so any new endpoint reaches the UI as a generated `UsersService` method rather than hand-written code.

The acceptance stack is declared as `javascript` in [openspec/config.yaml](openspec/config.yaml), but no `acceptance-tests/` project exists yet; this change is the first that needs one.

## Goals / Non-Goals

**Goals:**

- Add row selection to the admin Users table, scoped to the currently visible page, with the current user's row unselectable.
- Add an always-visible, selection-gated `Delete User(s)` action beside `Add User`.
- Add one superuser-only backend endpoint that deletes a set of users all-or-nothing, reusing the existing Item cascade behaviour.
- Surface the backend's rejection reason verbatim in the failure notification.
- Keep the existing single-user delete flow untouched.

**Non-Goals:**

- A generic bulk-action framework for other entities or other user operations (activate, deactivate, role change).
- Selection that persists across pages, filters, or refetches.
- Server-side pagination for the admin table.
- Any change to self-deletion through `/users/me`.

## Decisions

### 1. Row selection lives in the shared `DataTable`, not in the admin route

TanStack Table already manages `rowSelection` state; enabling it means adding an opt-in `enableRowSelection` / `onSelectionChange` pair to `DataTable` and a checkbox column in [frontend/src/components/Admin/columns.tsx](frontend/src/components/Admin/columns.tsx). Selection is read from `table.getRowModel()` (current page) rather than `getPrePaginationRowModel()`, which gives the "select-all applies to the visible page only" requirement for free.

*Alternative considered:* holding a `Set<string>` of ids in the admin route. Rejected — it duplicates state the table already owns and would have to re-derive page membership manually.

The current user's row is already flagged: `UserTableData.isCurrentUser` is computed in the route from `useAuth()`. The checkbox column uses it for `enableRowSelection: (row) => !row.original.isCurrentUser`, so the guard is data-driven and the select-all header checkbox skips that row automatically.

### 2. One atomic endpoint, not N single-delete calls

Add `POST /users/bulk-delete` taking a body of user ids (`UsersDelete`-style SQLModel) and returning the existing `Message`. A single request keeps authorization and atomicity in one place; looping `DELETE /users/{id}` from the client cannot be made all-or-nothing and would half-delete on the first failure.

*Method choice:* `POST` with a body rather than `DELETE` with a body, because request bodies on `DELETE` are poorly supported by proxies and generated clients.

*Path choice:* `bulk-delete` is a literal segment registered **before** the `/{user_id}` routes so it is never captured as a UUID path parameter.

### 3. Validate the entire target set before any mutation

The handler validates in this order, raising on the first failure: empty list → 422/400, duplicate ids → 400, `current_user.id` present → 403, any id not found → 404. Only after the whole set resolves does it issue `delete(Item).where(col(Item.owner_id).in_(ids))` and delete the users, then a single `session.commit()`. Since nothing is flushed before validation completes, "reject deletes nothing" holds without needing an explicit savepoint; a `session.rollback()` in the failure path keeps the session clean regardless.

Each rejection carries a distinct `detail` string — the specs require the reason to reach the user, and the frontend's `handleError` already renders `detail` in the error toast.

### 4. Bulk confirmation reuses the single-delete dialog pattern

A new `DeleteUsers` component mirrors `DeleteUser`: `Dialog` + `LoadingButton` (`loading={mutation.isPending}` gives the disabled-with-spinner state for free), the existing "items … permanently deleted" warning text plus the selected count, `showSuccessToast`/`showErrorToast`, and `queryClient.invalidateQueries()` on settle. Closing on response is `setIsOpen(false)` in both `onSuccess` and `onError`; the selection is cleared on success only.

*Alternative considered:* extracting a shared confirmation component for both flows. Deferred — the two dialogs differ in wording, trigger, and payload, and premature extraction would churn a working flow.

### 5. Regenerate the client rather than hand-writing types

Run [scripts/generate-client.sh](scripts/generate-client.sh) after the endpoint lands so `UsersService.bulkDeleteUsers` and its request type come from the OpenAPI schema. Hand-written client code would silently drift from the contract.

## Risks / Trade-offs

- **A selected user is deleted by someone else between selection and confirmation** → the whole request is rejected with "user not found" and nothing is deleted; the toast tells the superuser why and the table refetches.
- **Adding selection to the shared `DataTable` could affect the Items table** → the new options are opt-in and default to off, so existing call sites render unchanged; cover both tables in frontend tests.
- **A large selection produces a large request body** → selection is bounded by the current page size, and the route itself only loads 100 users; if server-side pagination arrives later this needs revisiting.
- **The `bulk-delete` path could collide with a future user id route** → the literal route is registered first and the segment is not a valid UUID.
- **This change also has to bootstrap `acceptance-tests/`** → scaffold the javascript pack verbatim from the acceptance-test-authoring skill in its own step, before writing step definitions, so runner setup failures stay separable from feature failures.

## Migration Plan

No database migration: the change reuses the existing `User`/`Item` relationship and adds no columns. Deploy backend and frontend together — the UI depends on the new endpoint, and the endpoint is inert without it. Rollback is removing the route and the UI action; single-user deletion is unaffected and remains the fallback.

## Open Questions

- Should the confirmation dialog list the selected users' emails in addition to the count, or is the count sufficient for larger selections?
- Should a rejected request name the offending user id in `detail`, or is a generic per-category reason preferable so the endpoint does not confirm the existence of ids to a caller?
